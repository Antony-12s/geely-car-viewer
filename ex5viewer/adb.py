"""Thin adb wrapper: run commands, list devices, connect, read props."""
import re
import subprocess
import sys

from . import paths

# windowed build on Windows: every child would flash a console without this
NO_WINDOW = {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}

ADB = paths.find_adb()


def run(*args, timeout=15, check=False):
    result = subprocess.run([ADB, *args], capture_output=True, text=True, errors="replace",
                            timeout=timeout, stdin=subprocess.DEVNULL, **NO_WINDOW)
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"adb {args[0]} failed")
    return result


def popen(*args, **kwargs):
    return subprocess.Popen([ADB, *args], **NO_WINDOW, **kwargs)


def parse_address(text, default_port):
    """'192.168.1.114' or '192.168.1.114:5566' -> '192.168.1.114:5566'; None if invalid."""
    match = re.fullmatch(r"\s*(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?\s*", text or "")
    if not match or any(int(part) > 255 for part in match.group(1).split(".")):
        return None
    port = int(match.group(2) or default_port)
    return f"{match.group(1)}:{port}" if 0 < port < 65536 else None


def parse_devices(output):
    """`adb devices -l` -> [(serial, model)] of ready devices."""
    found = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), "")
            found.append((parts[0], model))
    return found


def usb_devices():
    """Devices attached over USB (network ones have host:port serials, emulators are skipped)."""
    out = run("devices", "-l", timeout=8).stdout
    return [(s, m) for s, m in parse_devices(out) if ":" not in s and not s.startswith("emulator-")]


def connect(address):
    """Return (ok, message)."""
    result = run("connect", address, timeout=12)
    output = (result.stdout + result.stderr).strip()
    if "connected to" not in output:  # also matches "already connected to"
        return False, output or "adb connect failed"
    return True, output


def install_apk(serial, filename):
    """Install or update an APK on the explicitly selected device."""
    result = run("-s", serial, "install", "-r", filename, timeout=180)
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode or "Success" not in output.splitlines():
        raise RuntimeError(output or "ADB install failed")
    return output


def disconnect(address):
    try:
        run("disconnect", address, timeout=5)
    except subprocess.TimeoutExpired:
        pass


def props(serial, *names):
    """Several getprop values in one adb round trip."""
    script = "; ".join(f"echo \"$(getprop {n})\"" for n in names)
    out = run("-s", serial, "shell", script, timeout=10).stdout.splitlines()
    out += [""] * (len(names) - len(out))
    return {n: v.strip() for n, v in zip(names, out)}


def detect_model(info):
    """getprop dict -> 'EX5', 'EX2' or None.

    EX5: SiEngine se1000. Original EX2: Android 9 with ro.hardware=xecarx.
    """
    text = " ".join(info.values()).lower()
    if "ex2" in text or "xecarx" in text:
        return "EX2"
    if "ex5" in text or "se1000" in text:
        return "EX5"
    return None
