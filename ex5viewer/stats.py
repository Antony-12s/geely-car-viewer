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

from . import adb


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
    "/sys/class/misc/mali0/device/utilization",             # Mali
    "/sys/kernel/debug/pvr/status",                         # PowerVR (needs debugfs)
]


def parse_gpu(text):
    digits = "".join(ch if ch.isdigit() or ch == " " else " " for ch in text).split()
    if not digits:
        return None
    value = int(digits[0])
    return float(value) if 0 <= value <= 100 else None


class CarStats:
    """CPU/RAM/GPU of the head unit through one adb shell call per sample."""

    def __init__(self, serial):
        self.serial = serial
        self._cpu = None
        gpu = " ".join(f"cat {path} 2>/dev/null | head -1;" for path in CAR_GPU_FILES)
        self.script = f"head -1 /proc/stat; echo ---; head -3 /proc/meminfo; echo ---; {gpu} echo"

    def sample(self):
        out = adb.run("-s", self.serial, "shell", self.script, timeout=8).stdout
        parts = out.split("---")
        if len(parts) < 3 or not parts[0].strip().startswith("cpu"):
            return None
        times = cpu_times(parts[0].strip())
        cpu = cpu_percent(self._cpu, times) if self._cpu else None
        self._cpu = times
        used, total = mem_used(parts[1])
        gpu = next((v for v in map(parse_gpu, parts[2].strip().splitlines()) if v is not None), None)
        return {"cpu": cpu, "gpu": gpu, "ram": (used, total)}


class HostStats:
    """CPU/RAM via psutil on every OS. GPU: Intel (RC6 idle time) or NVIDIA (nvidia-smi); else None."""

    def __init__(self):
        psutil.cpu_percent(None)
        self._rc6 = next(iter(glob.glob("/sys/class/drm/card*/gt/gt0/rc6_residency_ms")
                              + glob.glob("/sys/class/drm/card*/power/rc6_residency_ms")), None)
        self._rc6_last = None
        self._nvidia = shutil.which("nvidia-smi") if not self._rc6 else None

    def _gpu(self):
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
                out = subprocess.run([self._nvidia, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=3, **adb.NO_WINDOW).stdout
                return float(out.split()[0])
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                return None
        return None

    def sample(self):
        memory = psutil.virtual_memory()
        return {"cpu": psutil.cpu_percent(None), "gpu": self._gpu(), "ram": (memory.total - memory.available, memory.total)}


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
