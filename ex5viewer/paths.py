"""Where things live: bundled resources, adb, config/log dir (works from source and from a PyInstaller build)."""
import os
import shutil
import sys
from pathlib import Path

APP = "ex5-viewer"  # kept from the old name so existing settings and logs carry over
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
EXE = ".exe" if IS_WIN else ""


def resource_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)  # PyInstaller unpack dir
    return Path(base) / "resources" if base else Path(__file__).resolve().parent / "resources"


def config_dir() -> Path:
    if IS_WIN:
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif IS_MAC:
        root = Path.home() / "Library/Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = root / APP
    path.mkdir(parents=True, exist_ok=True)
    return path


def sdk_adb_candidates():
    home = Path.home()
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(env):
            yield Path(os.environ[env]) / "platform-tools" / f"adb{EXE}"
    if IS_WIN:
        yield Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local")) / "Android/Sdk/platform-tools/adb.exe"
    elif IS_MAC:
        yield home / "Library/Android/sdk/platform-tools/adb"
    else:
        yield home / "Android/Sdk/platform-tools/adb"


def find_adb() -> str:
    """$ADB, then an installed Android SDK, then the bundled copy, then PATH.

    The SDK copy wins over the bundled one: two adb versions on one machine kill each
    other's server and the car drops off adb.
    """
    if os.environ.get("ADB"):
        return os.environ["ADB"]
    for path in sdk_adb_candidates():
        if path.is_file():
            return str(path)
    bundled = resource_dir() / "platform-tools" / f"adb{EXE}"
    if bundled.is_file():
        return str(bundled)
    return shutil.which("adb") or "adb"


def find_server() -> str:
    """scrcpy-server jar that matches scrcpy.SERVER_VERSION."""
    bundled = resource_dir() / "scrcpy-server"
    if bundled.is_file():
        return str(bundled)
    raise FileNotFoundError("scrcpy-server missing; run: python scripts/fetch_deps.py")
