"""Window size picking. Needs a display: run under Xvfb with the screen size in EX5_SCREEN, e.g.
    Xvfb :91 -screen 0 1024x768x24 &  DISPLAY=:91 EX5_SCREEN=1024x768 pytest tests/test_ui_size.py
"""
import os
import tkinter as tk

import pytest

from ex5viewer import ui
from ex5viewer.settings import Settings

SCREEN = os.environ.get("EX5_SCREEN")
pytestmark = pytest.mark.skipif(not SCREEN, reason="set EX5_SCREEN and DISPLAY (see docstring)")


def open_app(tmp_path, **opts):
    settings = Settings(tmp_path / "s.json")
    settings.update(auto_connect=False, **opts)
    root = tk.Tk()
    app = ui.App(root, settings)
    root.update()
    return root, app


@pytest.mark.parametrize("size", ["auto", "large"])
def test_size(tmp_path, size):
    width, height = map(int, SCREEN.split("x"))
    root, app = open_app(tmp_path, size=size)
    try:
        if size == "large":  # an explicit choice is kept even when it overflows
            assert app.size_name == "large"
        elif SCREEN in ("1920x1080", "1600x900", "2560x1440"):
            assert app.size_name == "medium"  # auto never grows past medium
        else:  # 1024x768, 1280x720, 1366x768 (the car panel makes medium 777 px tall)
            assert app.size_name == "small"
            assert root.winfo_width() <= width and root.winfo_height() <= height
        assert app.s["size"] == size  # the saved setting is not overwritten
    finally:
        app.quit()


@pytest.mark.parametrize("language", ["th", "en"])
def test_telemetry_connection_and_vehicle_details(tmp_path, monkeypatch, language):
    monkeypatch.setattr(ui.App, "stats_loop", lambda self: None)
    root, app = open_app(tmp_path, language=language, theme="telemetry")
    try:
        assert not app.vehicle_holder.winfo_ismapped()
        assert app.tbox_panel.winfo_ismapped()
        assert app.ip_entry.winfo_ismapped()
        assert app.screens["hud"].canvas.winfo_y() < app.screens["cluster"].canvas.winfo_y()
        assert app.screens["hud"].viewport[1] > app.screens["cluster"].viewport[1]

        app.link_seg.move(1)
        root.update()
        assert app.s["link"] == "usb"
        assert app.usb_pick.winfo_ismapped()
        assert not app.ip_entry.winfo_ismapped()
        assert app.endpoint_label.cget("text") == app.t("usb_device")
        app.set_model("EX2")
        assert app.model_chip.value == "EX2"
        app.set_link("wifi")
        root.update()
        assert app.ip_entry.winfo_ismapped()

        app.toggle_vehicle()
        root.update()
        assert app.vehicle_holder.winfo_ismapped()
        if SCREEN == "1024x768":
            assert root.winfo_height() <= 768
        app.toggle_vehicle()
        root.update()
        assert not app.vehicle_holder.winfo_ismapped()

        app.conn = "connected"
        app.update_car_data({"tcam": {"network": "4G", "operator": "AIS", "level": 3}})
        texts = [app.tbox_panel.itemcget(item, "text") for item in app.tbox_panel.find_all()
                 if app.tbox_panel.type(item) == "text"]
        assert "4G  AIS" in texts

        app.update_car_data({"tcam": {"network": "4G", "operator": "China Mobile", "level": 3},
                             "tcam_info": {"imsi": "52004"}})
        texts = [app.tbox_panel.itemcget(item, "text") for item in app.tbox_panel.find_all()
                 if app.tbox_panel.type(item) == "text"]
        assert "4G  TrueMove H" in texts
        assert "ⓘ" not in texts
        if ui.sys.platform.startswith("linux"):
            assert app.meters_box["pc"]["RAM"].grid_info()["column"] == 2

        app.show_stats({"cpu": 24, "gpu": None, "ram": (42, 100)},
                       {"cpu": 31, "gpu": 38, "gpu_mhz": 106, "ram": (61, 100)}, 12, [], 0)
        assert app.meters_box["pc"]["RAM"].value.cget("text") == "42%"
        assert app.meters_box["car"]["RAM"].value.cget("text") == "61%"
        assert app.meters_box["car"]["GPU"].value.cget("text") == "38%"
        app.toggle_vehicle()
        assert app.meters_box["pc"]["RAM"].value.cget("text") == "42%"
        assert app.meters_box["car"]["RAM"].value.cget("text") == "61%"
    finally:
        app.quit()


def test_touch_coordinates_include_screen_heading(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(ui.App, "stats_loop", lambda self: None)
    root, app = open_app(tmp_path)
    touches = []
    stream = SimpleNamespace(touch=lambda *args: touches.append(args), stop=lambda: None)
    try:
        app.streams["main"] = stream
        app.control_var.set(True)
        image_x, image_y, width, height = app.screens["main"].image_bounds
        app.on_touch(SimpleNamespace(type=tk.EventType.ButtonPress, x=ui.PAD + image_x + width / 2,
                                    y=ui.PAD + ui.HEAD + image_y + height / 2))
        assert touches[0][1:] == (0.5, 0.5)
        touches.clear()
        app.press = None
        app.on_touch(SimpleNamespace(type=tk.EventType.ButtonPress, x=ui.PAD + width / 2, y=ui.PAD + 2))
        assert touches == []
    finally:
        app.quit()


def test_apk_tab_targets_connected_vehicle(tmp_path, monkeypatch):
    monkeypatch.setattr(ui.App, "stats_loop", lambda self: None)
    root, app = open_app(tmp_path)
    try:
        app.toggle_apk()
        apk = tmp_path / "demo app.apk"
        apk.write_bytes(b"demo")
        other = tmp_path / "second.apk"
        other.write_bytes(b"demo")
        monkeypatch.setattr(ui.filedialog, "askopenfilenames", lambda **kwargs: (str(apk), str(other)))
        app.choose_apk()
        assert app.apk_files.get(0, "end") == (apk.name, other.name)
        assert app.apk_size == 8
        from types import SimpleNamespace
        drop = SimpleNamespace(data=f"{{{apk}}} {{{other}}}")
        assert app.drop_apk(drop) == "copy"
        assert app.apk_paths == (str(apk), str(other))
        assert app.drop_apk(SimpleNamespace(data="{wrong.txt}")) == "refuse_drop"
        assert app.apk_paths == (str(apk), str(other))
        app.update_apk_panel()
        assert app.apk_install["state"] == "disabled"
        app.conn, app.serial = "connected", "192.0.2.5:5566"
        app.update_apk_panel()
        assert app.apk_install["state"] == "normal"
        calls = []

        def install(serial, filename):
            calls.append((serial, filename))
            if filename == str(apk):
                raise RuntimeError("INSTALL_FAILED")
            return "Success"

        monkeypatch.setattr(ui.adb, "install_apk", install)
        monkeypatch.setattr(app, "ui", lambda callback: callback())
        app._install_apk(app.serial, app.apk_paths)
        assert calls == [(app.serial, str(apk)), (app.serial, str(other))]
        assert app.t("apk_success") in app.apk_result
        assert app.apk_state["text"] == app.t("apk_partial")
        assert "1/2" in app.apk_result
        assert app.apk_done == 2
        assert app.apk_progress.find_withtag("progress")
        assert "INSTALL_FAILED" in app.apk_result
        assert "Success" in app.apk_status.get("1.0", "end")
    finally:
        app.quit()


def test_hud_preserves_aspect_in_matching_frame(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(ui.App, "stats_loop", lambda self: None)
    root, app = open_app(tmp_path, model="EX5")
    try:
        screen = app.screens["hud"]
        screen.state = "live"
        from ex5viewer.decoder import Decoder
        import av
        source = av.VideoFrame.from_image(Image.new("RGB", (1000, 600), "#ffffff"))
        decoded = Decoder.to_image(source, *screen.viewport, preserve_aspect=True)
        assert abs(decoded.width / decoded.height - 5 / 3) < 0.02
        screen.show(decoded)
        assert abs(screen.viewport[0] / screen.viewport[1] - 5 / 3) < 0.02
        left, top, width, height = screen.image_bounds
        assert abs(width / height - 5 / 3) < 0.02
        assert left <= 2 and top <= 2
        assert screen.photo.width() == screen.viewport[0]
        from PIL import ImageTk
        rendered = ImageTk.getimage(screen.photo)
        assert rendered.getpixel((left, top))[:3] == (255, 255, 255)
        assert rendered.getpixel((left + width - 1, top + height - 1))[:3] == (255, 255, 255)
    finally:
        app.quit()
