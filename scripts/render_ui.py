"""Render the real window with mock data and save PNGs (design QA). Never starts adb or touches a car.

    Xvfb :93 -screen 0 1920x1080x24 &
    DISPLAY=:93 PYTHONPATH=. python scripts/render_ui.py OUTDIR [name:key=value,key=value ...]

Each spec: a name, then settings (size, language, model, theme, control, link) and `state=` idle|live|demo.
"live"/"demo" fill the screens with the bundled selftest clip and the car panel with fictional values.
"""
import json
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageGrab

from ex5viewer import adb, paths, ui

adb.usb_devices = lambda: []          # the stats thread lists USB devices: no adb process in renders


def _refuse(*args, **kwargs):
    raise RuntimeError(f"render must not run adb: {args}")


adb.run = adb.connect = _refuse

DEMO_CAR = {"soc": 34.0, "range_km": 173.0, "gear": "P", "speed_kmh": 0.0, "temp_c": 27.0, "odometer": 12345.0,
            "plugged": False, "tires": {"fl": 33.0, "fr": 33.2, "rl": 32.1, "rr": 33.2}}


def frames():
    try:
        import av
        from ex5viewer.decoder import Decoder
        decoder, out = Decoder(), []
        data = (paths.resource_dir() / "selftest.h264").read_bytes()
        for packet in av.CodecContext.create("h264", "r").parse(data):
            out += decoder.decode(bytes(packet))
        return out, Decoder
    except Exception as error:  # noqa: BLE001 - render without video if PyAV is missing
        print("no video:", error)
        return [], None


def parse(spec):
    name, _, rest = spec.partition(":")
    opts = {}
    for pair in filter(None, rest.split(",")):
        key, _, value = pair.partition("=")
        opts[key] = {"true": True, "false": False}.get(value, value)
    return name, opts


def render(out_dir, name, opts, clip):
    from ex5viewer.settings import Settings
    state = opts.pop("state", "idle")
    geometry = opts.pop("geometry", None)
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(Path(tmp) / "s.json")
        settings.update(auto_connect=False, address="192.0.2.25:5566", **opts)
        root = tk.Tk()
        app = ui.App(root, settings, selftest=True)
        root.update()
        if geometry:
            root.geometry(geometry)
            root.update()
            app.fit_to_window()
            root.update()
        if state in ("live", "demo"):
            app.conn, app.model = "connected", app.layout_model()
            app.ping = 18
            app.update_conn_ui()
            app.car_panel and app.car_panel.update_data(
                car=DEMO_CAR, tcam={"network": "4G", "level": 3, "operator": "Demo"},
                gps={"lat": 0.0, "lon": 0.0, "heading": 0.0, "speed": 0.0},
                tbox_rate=(20000.0, 3000.0), tbox_total=5e8)
            import math
            for i in range(45):  # fictional app traffic for the graph
                app.history.samples.append((8.0 + 0.6 * math.sin(i / 3), 0.12 + 0.03 * math.cos(i / 4)))
            frames_, decoder = clip
            app.streams = {n: None for n in app.screens}
            for n in app.screens:
                app.set_state(n, "live")
            sizes = app.sizes()
            for i in range(20):
                if frames_:
                    frame = frames_[i % len(frames_)]
                    for n in app.screens:
                        app.frames[n] = decoder.to_image(frame, *sizes[n], rotate180=n == "hud")
                root.update()
                time.sleep(1 / 30)
            app.draw_rates(app.history.samples[-1])
        if opts.get("settings_open"):
            pass
        root.update()
        time.sleep(0.6)  # let switches / meters finish animating
        root.update()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        path = out_dir / f"{name}.png"
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
        info = {"name": name, "window": [w, h], "req": [root.winfo_reqwidth(), root.winfo_reqheight()],
                "size_name": app.size_name, "k": app.k, "sizes": app.sizes()}
        app.quit()
        return info


def main():
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    clip = frames()
    report = [render(out_dir, *parse(spec), clip) for spec in sys.argv[2:]]
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
