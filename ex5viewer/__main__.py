"""Entry point: `python -m ex5viewer` or the frozen GeelyCarViewer executable.

--selftest        open the window, decode the bundled clip into every screen, check adb, exit 0/1
--screenshot PNG  with --selftest: save the window (used by CI on all three OSes)
"""
import argparse
import logging
import os
import sys
import time
import tkinter as tk
from pathlib import Path

from . import __version__, paths


def setup_logging():
    handler = logging.FileHandler(paths.config_dir() / "ex5-viewer.log", encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("paramiko").setLevel(logging.WARNING)


def report(*parts):
    """stdout is None in a windowed (no console) build; keep a copy in the config dir for CI."""
    line = " ".join(str(p) for p in parts)
    if sys.stdout:
        print(line, flush=True)
    with open(paths.config_dir() / "selftest.txt", "a", encoding="utf-8") as file:
        file.write(line + "\n")


def selftest(app, root, screenshot):
    import av
    from . import adb
    from .decoder import Decoder

    problems = []
    try:
        version = adb.run("version", timeout=20).stdout.splitlines()[0]
        report("adb:", adb.ADB, "-", version)
    except Exception as error:
        problems.append(f"adb: {error}")
    try:
        report("scrcpy-server:", paths.find_server())
    except FileNotFoundError as error:
        problems.append(str(error))

    decoder, frames = Decoder(), []
    data = (paths.resource_dir() / "selftest.h264").read_bytes()
    for packet in av.CodecContext.create("h264", "r").parse(data):
        frames += decoder.decode(bytes(packet))
    if not frames:
        problems.append("decoder produced no frames")
    sizes = app.sizes()
    app.streams = {name: None for name in app.screens}
    for name in app.screens:
        app.set_state(name, "live")
    deadline = time.time() + 2
    index = 0
    while time.time() < deadline:
        frame = frames[index % len(frames)] if frames else None
        if frame is not None:
            for name in ("main", "hud", "cluster"):
                if name in app.screens:
                    app.frames[name] = Decoder.to_image(frame, *sizes[name], rotate180=name == "hud")
        index += 1
        root.update()
        time.sleep(1 / 30)
    if screenshot:
        try:  # macOS needs screen-recording permission; a missing picture is not an app failure
            from PIL import ImageGrab
            def capture(path):
                root.update()
                x, y = root.winfo_rootx(), root.winfo_rooty()
                ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(path)
                report("screenshot:", path)

            capture(screenshot)
            app.toggle_apk()
            try:
                path = Path(screenshot)
                capture(path.with_stem(path.stem + "-apk"))
            finally:
                app.toggle_apk()
        except Exception as error:
            report("screenshot skipped:", error)
    report(f"decoded {len(frames)} frames, window {root.winfo_width()}x{root.winfo_height()}")
    for problem in problems:
        report("FAIL:", problem)
    return 1 if problems else 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ex5viewer")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--screenshot")
    parser.add_argument("--linux-safe-rendering", action=argparse.BooleanOptionalAction, default=True,
                        help="Use software rendering and reduce display updates on Linux (default)")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    safe_rendering = args.linux_safe_rendering and sys.platform.startswith("linux")
    if safe_rendering:
        os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
    setup_logging()
    if safe_rendering:
        logging.info("Linux safe rendering enabled: software GL, no animations, video capped at 12 fps")
    from .settings import Settings
    from .ui import App

    from tkinterdnd2 import TkinterDnD

    root = tk.Tk()
    try:
        root.TkdndVersion = TkinterDnD._require(root)
    except RuntimeError as error:
        logging.warning("Native file drop unavailable: %s", error.__cause__ or error)
    settings = Settings(paths.config_dir() / "selftest.json") if args.selftest else Settings()
    app = App(root, settings, selftest=args.selftest, safe_rendering=safe_rendering)
    if args.selftest:
        code = selftest(app, root, args.screenshot)
        app.quit()
        return code
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
