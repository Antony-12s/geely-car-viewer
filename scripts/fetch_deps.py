"""Download the binaries the app bundles: scrcpy-server (pinned, hash-checked) and adb for one OS.

    python scripts/fetch_deps.py [--os linux|windows|darwin]

Both go to ex5viewer/resources/ (gitignored).
"""
import argparse
import hashlib
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

RESOURCES = Path(__file__).resolve().parent.parent / "ex5viewer" / "resources"
SERVER_URL = "https://github.com/Genymobile/scrcpy/releases/download/v5.0.1/scrcpy-server-v5.0.1"
SERVER_SHA256 = "764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536"
TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-{os}.zip"
TOOLS_FILES = {"windows": ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt"],
               "linux": ["adb", "NOTICE.txt"], "darwin": ["adb", "NOTICE.txt"]}


def download(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def fetch_server():
    target = RESOURCES / "scrcpy-server"
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == SERVER_SHA256:
        print("scrcpy-server: up to date")
        return
    data = download(SERVER_URL)
    digest = hashlib.sha256(data).hexdigest()
    if digest != SERVER_SHA256:
        sys.exit(f"scrcpy-server hash mismatch: {digest}")
    target.write_bytes(data)
    print("scrcpy-server: ok")


def fetch_adb(os_name):
    target = RESOURCES / "platform-tools"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(download(TOOLS_URL.format(os=os_name)))) as archive:
        for name in TOOLS_FILES[os_name]:
            path = target / name
            path.write_bytes(archive.read(f"platform-tools/{name}"))
            if not name.endswith((".dll", ".txt")):
                path.chmod(0o755)
    print("adb:", ", ".join(TOOLS_FILES[os_name]))


def main():
    default = {"win32": "windows", "darwin": "darwin"}.get(sys.platform, "linux")
    parser = argparse.ArgumentParser()
    parser.add_argument("--os", choices=sorted(TOOLS_FILES), default=default)
    parser.add_argument("--no-adb", action="store_true", help="only the scrcpy server (dev with an SDK adb)")
    args = parser.parse_args()
    RESOURCES.mkdir(parents=True, exist_ok=True)
    fetch_server()
    if not args.no_adb:
        fetch_adb(args.os)


if __name__ == "__main__":
    main()
