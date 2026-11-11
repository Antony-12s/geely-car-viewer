# PyInstaller spec, same for all three OSes: pyinstaller ex5viewer.spec
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

is_mac = sys.platform == "darwin"

# Only the runtime resources, listed one by one: anything else that happens to sit in
# ex5viewer/resources/ (local scratch such as assets/) must never end up in a release.
RES = "ex5viewer/resources"
datas = [(f"{RES}/{name}", "resources") for name in ("icon.png", "selftest.h264", "scrcpy-server")]
if os.path.isdir(f"{RES}/platform-tools"):  # adb from scripts/fetch_deps.py; optional for a local build
    datas.append((f"{RES}/platform-tools", "resources/platform-tools"))

a = Analysis(
    ["run.py"],
    datas=datas + collect_data_files("tkinterdnd2"),  # native file drop for the APK tab
    hiddenimports=collect_submodules("av") + ["PIL._tkinter_finder"],  # ImageTk loads it lazily
    excludes=["numpy", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GeelyCarViewer", console=False,
          icon="packaging/icon.ico" if sys.platform.startswith("win") else None)
coll = COLLECT(exe, a.binaries, a.datas, name="GeelyCarViewer")
if is_mac:
    app = BUNDLE(coll, name="GeelyCarViewer.app", icon="packaging/icon.icns",
                 bundle_identifier="com.antony12s.geelycarviewer",
                 info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "1.2.0"})
