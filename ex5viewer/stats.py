"""Traffic meters and CPU/GPU/RAM readings for this computer and the car."""
import glob
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque

import psutil

from . import adb, vehicle


class Meter:
    """Thread-safe byte counter for one stream."""

    def __init__(self):
        self._lock = threading.Lock()
        self._down = self._up = 0

    def add(self, down=0, up=0):
        with self._lock:
            self._down += down
            self._up += up

    def take(self):
        with self._lock:
            down, up, self._down, self._up = self._down, self._up, 0, 0
        return down, up


class History:
    """Per-second down/up rates (Mb/s) for the graph, plus moments a stream dropped."""

    def __init__(self, seconds=60):
        self.samples = deque(maxlen=seconds)
        self.drops = deque(maxlen=seconds)  # sample index counted from the end when the drop happened
        self._last = time.monotonic()

    def resize(self, seconds):
        self.samples = deque(self.samples, maxlen=seconds)

    def tick(self, down_bytes, up_bytes):
        now = time.monotonic()
        elapsed = max(now - self._last, 1e-3)
        self._last = now
        sample = (down_bytes * 8 / elapsed / 1e6, up_bytes * 8 / elapsed / 1e6)
        self.samples.append(sample)
        self.drops = deque(((age + 1) for age in self.drops if age + 1 < self.samples.maxlen),
                           maxlen=self.samples.maxlen)
        return sample

    def mark_drop(self):
        self.drops.append(0)

    def peak(self):
        return max((max(d, u) for d, u in self.samples), default=0.0)


# ---- /proc parsing (car side, and Linux generally) ----
def cpu_times(stat_line):
    """'cpu  user nice system idle iowait irq softirq ...' -> (idle, total)."""
    values = [int(v) for v in stat_line.split()[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return idle, sum(values[:8])


def cpu_percent(before, after):
    idle = after[0] - before[0]
    total = after[1] - before[1]
    return max(0.0, min(100.0, 100.0 * (1 - idle / total))) if total > 0 else 0.0


def mem_used(meminfo):
    """/proc/meminfo text -> (used_bytes, total_bytes)."""
    values = {}
    for line in meminfo.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            values[parts[0].rstrip(":")] = int(parts[1]) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    return total - available, total


# Car GPUs expose load in different places; the first readable one wins, else GPU shows "–".
CAR_GPU_FILES = [
    "/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage",        # Qualcomm Adreno: "37 %"
    "/sys/kernel/gpu/gpu_busy",                             # some vendor kernels: "37 %"
    "/sys/class/misc/mali0/device/utilisation",             # Mali (EX5 SE1000, Mali-G76): "gpu utilisation    : 58", no root
    "/sys/kernel/debug/pvr/status",                         # PowerVR (needs debugfs)
]


def parse_gpu(text):
    digits = "".join(ch if ch.isdigit() or ch == " " else " " for ch in text).split()
    if not digits:
        return None
    value = int(digits[0])
    return float(value) if 0 <= value <= 100 else None


NETWORKS = {"FiveG": "5G", "FourG": "4G", "ThreeG": "3G", "TwoG": "2G"}
OPERATORS = {"chinamobile": "China Mobile", "chinaunicom": "China Unicom", "chinatelecom": "China Telecom"}


# MCC+MNC from the eSIM's IMSI -> carrier. The status log's operator says China Mobile on Thai cars
# whose eSIM is TrueMove H, so the IMSI wins whenever TcamService has it.
CARRIERS = {
    "52000": "my by NT", "52001": "AIS", "52003": "AIS", "52004": "TrueMove H", "52005": "dtac",
    "52015": "NT", "52018": "dtac", "52047": "NT", "52099": "TrueMove",
    "46000": "China Mobile", "46002": "China Mobile", "46007": "China Mobile", "46001": "China Unicom",
    "46006": "China Unicom", "46003": "China Telecom", "46011": "China Telecom",
    "50501": "Telstra", "50502": "Optus", "50503": "Vodafone AU", "50219": "Celcom", "50212": "Maxis",
}
TCAM_INFO_FIELDS = ["du", "hw", "sxbl", "sxdi", "swbl", "swlx", "swlm", "imsi", "iccid", "msisdn", "imei", "tcam_id"]


def parse_tcam_info(text):
    """`service call tcam 133` (ITcamService.getTcamInfo, TcamService's cached copy) -> dict, or None.

    Reply: status, non-null flag, then 12 String16 in writeToParcel order (part numbers, IMSI, ICCID...)."""
    import re
    words = [int(w, 16) for w in re.findall(r"0x[0-9a-f]+: ((?:[0-9a-f]{8} ?){1,4})", text) for w in w.split()]
    if len(words) < 3 or words[0] != 0 or words[1] != 1:
        return None
    raw = b"".join(w.to_bytes(4, "little") for w in words)
    pos, info = 8, {}
    for name in TCAM_INFO_FIELDS:
        if pos + 4 > len(raw):
            return None
        length = int.from_bytes(raw[pos:pos + 4], "little", signed=True)
        pos += 4
        if length < 0:
            info[name] = None
            continue
        if length > 64:
            return None
        info[name] = raw[pos:pos + 2 * length].decode("utf-16-le", "replace").strip("\x00\x04 ")
        pos += (2 * length + 2 + 3) // 4 * 4
    iccid = (info.get("iccid") or "").rstrip("Ff")
    if not iccid.isdigit():
        return None
    info["iccid"] = iccid
    info["msisdn"] = info["msisdn"] if (info.get("msisdn") or "").strip("0") else None
    return info


def carrier(imsi):
    if not imsi or not imsi.isdigit():
        return None
    return CARRIERS.get(imsi[:5]) or CARRIERS.get(imsi[:6]) or f"MCC {imsi[:3]} / {imsi[3:5]}"


def parse_tcam(line):
    """The T-Box (TCAM) status the head unit logs every 2 s, e.g. `.eSIMConnectionStatus__ =
    ESIMConnectionStatus_FourGnetwork, .signallevl__ = 4, ... .operator__ = Operator_Chinamobile}`."""
    import re
    fields = dict(re.findall(r"\.(\w+?)__ = ([\w.]+)", line))
    if "eSIMConnectionStatus" not in fields:
        return None
    status = fields["eSIMConnectionStatus"].split("_", 1)[-1]
    network = next((name for key, name in NETWORKS.items() if status.startswith(key)), None)
    operator = fields.get("operator", "").split("_", 1)[-1]
    level = fields.get("signallevl", "")
    return {"network": network,
            "level": min(int(level), 4) if level.isdigit() else None,
            "operator": OPERATORS.get(operator.lower(), operator if operator not in ("", "Unknown") else None)}


class CarStats:
    """CPU/RAM/GPU of the head unit through one adb shell call per sample; T-Box status every 5th."""

    TCAM_EVERY = 5  # the log dump reads ~1 MB on the car: every 10 s is plenty for a signal icon

    def __init__(self, serial):
        self.serial = serial
        self._cpu = None
        self._count = 0
        self.tcam = self.gps = self.tcam_info = None
        gpu = " ".join(f"cat {path} 2>/dev/null | head -1;" for path in CAR_GPU_FILES)
        # GPU clock in Hz from devfreq (EX5: /sys/class/devfreq/e5000000.gpu), readable without root
        self.script = (f"head -1 /proc/stat; echo ---; head -3 /proc/meminfo; echo ---; {gpu} echo; echo ---;"
                       " cat /sys/class/devfreq/*.gpu/cur_freq 2>/dev/null | head -1; echo ---;"
                       " grep eth0.11: /proc/net/dev")  # the DHU <-> T-Box link (car internet without Wi-Fi)

    def sample(self):
        script = self.script
        if self._count % self.TCAM_EVERY == 0:
            script += "; echo ---; logcat -d -b main | grep -E 'onEsimStatus|posnFromSatlt' | tail -40"
            if self.tcam_info is None:  # IDs and part numbers do not change: ask until we have them once
                script += "; echo ---; service call tcam 133"
        self._count += 1
        out = adb.run("-s", self.serial, "shell", script, timeout=8).stdout
        parts = out.split("---")
        if len(parts) < 3 or not parts[0].strip().startswith("cpu"):
            return None
        if len(parts) > 5:  # keep the last known value when the line rotated out of the log
            lines = parts[5].strip().splitlines()
            status = [line for line in lines if "onEsimStatus" in line]
            self.tcam = (parse_tcam(status[-1]) if status else None) or self.tcam
            if len(parts) > 6:
                self.tcam_info = parse_tcam_info(parts[6]) or self.tcam_info
            if self.tcam and self.tcam_info and carrier(self.tcam_info.get("imsi")):
                self.tcam = {**self.tcam, "operator": carrier(self.tcam_info["imsi"])}
            gps = [p for p in map(vehicle.parse_position, lines) if p]
            if gps:
                self.gps = gps[-1]
        tbox_bytes = None
        if len(parts) > 4 and ":" in parts[4]:
            fields = parts[4].split(":", 1)[1].split()
            if len(fields) >= 9 and fields[0].isdigit() and fields[8].isdigit():
                tbox_bytes = (int(fields[0]), int(fields[8]))  # rx, tx since the head unit booted
        hz = parts[3].split()[0] if len(parts) > 3 and parts[3].split() else ""
        times = cpu_times(parts[0].strip())
        cpu = cpu_percent(self._cpu, times) if self._cpu else None
        self._cpu = times
        used, total = mem_used(parts[1])
        gpu = next((v for v in map(parse_gpu, parts[2].strip().splitlines()) if v is not None), None)
        return {"cpu": cpu, "gpu": gpu, "gpu_mhz": int(hz) // 1_000_000 if hz.isdigit() else None,
                "ram": (used, total), "tcam": self.tcam, "tcam_info": self.tcam_info, "gps": self.gps, "tbox_bytes": tbox_bytes}


class HostStats:
    """CPU/RAM via psutil on every OS. GPU: Intel (RC6 idle time) or NVIDIA (nvidia-smi); else None."""

    def __init__(self):
        psutil.cpu_percent(None)
        self._rc6 = next(iter(glob.glob("/sys/class/drm/card*/gt/gt0/rc6_residency_ms")
                              + glob.glob("/sys/class/drm/card*/power/rc6_residency_ms")), None)
        self._rc6_last = None
        # Intel actual GPU clock next to the RC6 file (newer kernels) or on the card (older ones)
        self._freq = None
        if self._rc6:
            card = self._rc6.split("/gt/")[0].split("/power/")[0]
            # cur, not act: act reads 0 whenever the GPU naps between frames, so the value kept vanishing
            self._freq = next((p for p in (os.path.join(os.path.dirname(self._rc6), "rps_cur_freq_mhz"),
                                           os.path.join(card, "gt_cur_freq_mhz")) if os.path.exists(p)), None)
        self._nvidia = shutil.which("nvidia-smi") if not self._rc6 else None

    def _gpu_mhz(self):
        if self._freq:
            try:
                return int(open(self._freq).read())
            except (OSError, ValueError):
                return None
        return self._nvidia_mhz

    def _gpu(self):
        self._nvidia_mhz = None
        if self._rc6:
            # busy = time not spent in RC6 sleep; no root needed (perf counters are locked down)
            try:
                now = (time.monotonic(), int(open(self._rc6).read()))
            except OSError:
                return None
            last, self._rc6_last = self._rc6_last, now
            if not last:
                return None
            wall_ms = (now[0] - last[0]) * 1000
            return max(0.0, min(100.0, 100 - 100 * (now[1] - last[1]) / wall_ms)) if wall_ms > 0 else None
        if self._nvidia:
            try:
                out = subprocess.run([self._nvidia, "--query-gpu=utilization.gpu,clocks.gr",
                                      "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=3, **adb.NO_WINDOW).stdout
                load, mhz = out.splitlines()[0].split(",")
                self._nvidia_mhz = int(mhz)
                return float(load)
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                return None
        return None

    def sample(self):
        memory = psutil.virtual_memory()
        gpu = self._gpu()
        return {"cpu": psutil.cpu_percent(None), "gpu": gpu, "gpu_mhz": self._gpu_mhz(),
                "ram": (memory.total - memory.available, memory.total)}


def tcp_ping(address, timeout=2.0):
    """TCP connect time to the car's adb port in ms (real network RTT, no ICMP rights needed)."""
    import socket
    host, port = address.rsplit(":", 1)
    start = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return (time.perf_counter() - start) * 1000
    except OSError:
        return None


def human_gb(used, total):
    return f"{used / 2**30:.1f}/{total / 2**30:.0f}G" if total else "–"
