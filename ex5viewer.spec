# PyInstaller spec, same for all three OSes: pyinstaller ex5viewer.spec
import sys

from PyInstaller.utils.hooks import collect_submodules

is_mac = sys.platform == "darwin"

a = Analysis(
    ["run.py"],
    datas=[("ex5viewer/resources", "resources")],
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
                 info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "1.1.0"})
