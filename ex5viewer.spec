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
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="EX5Viewer", console=False,
          icon="packaging/icon.ico" if sys.platform.startswith("win") else None)
coll = COLLECT(exe, a.binaries, a.datas, name="EX5Viewer")
if is_mac:
    app = BUNDLE(coll, name="EX5Viewer.app", icon="packaging/icon.icns",
                 bundle_identifier="com.antony12s.ex5viewer",
                 info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "1.0.1"})
