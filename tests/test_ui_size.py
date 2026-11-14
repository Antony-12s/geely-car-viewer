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
        else:  # 1024x768, 1280x720, 1366x768: medium is too tall for these
            assert app.size_name == "small"
            assert root.winfo_width() <= width and root.winfo_height() <= height
        assert app.s["size"] == size  # the saved setting is not overwritten
    finally:
        app.quit()


def panel_texts(panel):
    return [panel.itemcget(item, "text") for item in panel.find_all() if panel.type(item) == "text"]


@pytest.mark.parametrize("language", ["th", "en"])
def test_connection_and_vehicle_details(tmp_path, monkeypatch, language):
    """The 1.1.2/1.1.3 connection, T-Box and meter behaviour, in the OLED Cinema layout: the car data and the
    T-Box share one always-visible tray section (no Vehicle info button, no separate T-Box card), and HUD and
    Cluster sit side by side under Main."""
    from ex5viewer.stats import human_gb

    monkeypatch.setattr(ui.App, "stats_loop", lambda self: None)
    root, app = open_app(tmp_path, language=language, theme="telemetry")
    try:
        assert app.car_panel.winfo_ismapped()  # vehicle details and T-Box: always visible beside Main
        assert app.ip_entry.winfo_ismapped()
        hud, cluster, main = (app.screens[name].canvas for name in ("hud", "cluster", "main"))
        assert hud.winfo_rooty() == cluster.winfo_rooty() > main.winfo_rooty() + main.winfo_height() - 1
        assert hud.winfo_rootx() < cluster.winfo_rootx()
        assert app.screens["hud"].viewport[1] == app.screens["cluster"].viewport[1]
        assert root.winfo_width() <= int(SCREEN.split("x")[0]) and root.winfo_height() <= int(SCREEN.split("x")[1])

        app.link_seg.move(1)
        root.update()
        assert app.s["link"] == "usb"
        assert app.usb_pick.winfo_ismapped()
        assert not app.ip_entry.winfo_ismapped()
        assert app.endpoint_label.cget("text") == app.t("usb_device")
        app.set_model("EX2")
        assert app.s["model"] == "EX2" and app.model_chip.text.startswith("EX2")
        app.set_model("auto")
        app.set_link("wifi")
        root.update()
        assert app.ip_entry.winfo_ismapped()
        assert app.endpoint_label.cget("text") == "IP"

        app.change_setting("show_vehicle", False)
        root.update()
        assert app.car_panel is None
        app.change_setting("show_vehicle", True)
        root.update()
        assert app.car_panel.winfo_ismapped()
        if SCREEN == "1024x768":
            assert root.winfo_height() <= 768

        app.conn = "connected"
        app.update_car_data({"tcam": {"network": "4G", "operator": "AIS", "level": 3}})
        texts = panel_texts(app.car_panel)
        assert "4G" in texts and "3/4  AIS" in texts

        app.update_car_data({"tcam": {"network": "4G", "operator": "China Mobile", "level": 3},
                             "tcam_info": {"imsi": "52004"}})
        texts = panel_texts(app.car_panel)
        assert "4G" in texts and "3/4  TrueMove H" in texts
        assert "ⓘ" not in texts
        if ui.sys.platform.startswith("linux"):  # host GPU is not polled on Linux: no PC GPU meter
            assert "GPU" not in app.meters_box["pc"]
            assert app.meters_box["pc"]["RAM"].winfo_ismapped()
        assert "GPU" in app.meters_box["car"]

        gb = 2 ** 30
        app.show_stats({"cpu": 24, "gpu": None, "ram": (13 * gb, 31 * gb)},
                       {"cpu": 31, "gpu": 38, "gpu_mhz": 106, "ram": (3 * gb, 8 * gb)}, 12, [], 0)
        ram_pc, ram_car = human_gb(13 * gb, 31 * gb), human_gb(3 * gb, 8 * gb)
        assert ram_pc != ram_car
        assert app.meters_box["pc"]["CPU"].value.cget("text") == "24%"
        assert app.meters_box["pc"]["RAM"].value.cget("text") == ram_pc
        assert app.meters_box["car"]["RAM"].value.cget("text") == ram_car
        assert app.meters_box["car"]["GPU"].value.cget("text").split()[0] == "38%"
        app.build()  # a rebuild (language, theme, size...) keeps the last readings
        assert app.meters_box["pc"]["RAM"].value.cget("text") == ram_pc
        assert app.meters_box["car"]["RAM"].value.cget("text") == ram_car
        assert app.meters_box["car"]["GPU"].value.cget("text").split()[0] == "38%"
    finally:
        app.quit()


def test_touch_coordinates_follow_the_picture(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(ui.App, "stats_loop", lambda self: None)
    root, app = open_app(tmp_path)
    touches = []
    stream = SimpleNamespace(touch=lambda *args: touches.append(args), stop=lambda: None,
                             is_alive=lambda: False)
    try:
        app.streams["main"] = stream
        app.control_var.set(True)
        image_x, image_y, width, height = app.screens["main"].image_bounds
        app.on_touch(SimpleNamespace(type=tk.EventType.ButtonPress, x=ui.PAD + image_x + width / 2,
                                    y=ui.PAD + ui.HEAD + image_y + height / 2))
        assert touches[0][1:] == (0.5, 0.5)
        touches.clear()
        app.press = None
        # this layout has no heading row above the picture: a press on the outline ring is outside it
        app.on_touch(SimpleNamespace(type=tk.EventType.ButtonPress, x=ui.PAD + width / 2, y=ui.PAD - 2))
        assert touches == []
        # letterboxed picture (frame of another ratio): the bars are not the car's screen
        from PIL import Image
        screen = app.screens["main"]
        screen.show(Image.new("RGB", (screen.viewport[0] // 2, screen.viewport[1]), "white"))
        image_x, image_y, width, height = screen.image_bounds
        assert image_x > 0 and width < screen.viewport[0]
        app.on_touch(SimpleNamespace(type=tk.EventType.ButtonPress, x=ui.PAD + image_x - 4, y=ui.PAD + 10))
        assert touches == []
        app.on_touch(SimpleNamespace(type=tk.EventType.ButtonPress, x=ui.PAD + image_x + width / 2,
                                    y=ui.PAD + ui.HEAD + image_y + height / 2))
        assert touches[0][1:] == (0.5, 0.5)
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
        # The corners of the picture area hold the picture itself, pixel for pixel, not the bezel. swscale
        # renders this white test frame as 253 or 255 depending on the output size, so "white" has a tolerance.
        for x, y in ((left, top), (left + width - 1, top + height - 1)):
            pixel = rendered.getpixel((x, y))[:3]
            assert pixel == decoded.getpixel((x - left, y - top))
            assert min(pixel) >= 250
    finally:
        app.quit()
