"""OLED Cinema layout (design A): centred Main stage with the car status rail on its right, HUD/Cluster in a
lower tray, system floor.

Needs a display (Xvfb is fine):  Xvfb :93 -screen 0 1920x1080x24 &  DISPLAY=:93 pytest tests/test_ui_layout.py
adb is stubbed: these tests never start an adb process.
"""
import os
import tkinter as tk

import pytest

from ex5viewer import adb, ui, widgets
from ex5viewer.settings import Settings

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs DISPLAY (run under Xvfb)")

# The App's stats thread outlives each test and lists USB devices every 2 s: stub it for the whole process.
adb.usb_devices = lambda: []

CAR = {"soc": 34.0, "range_km": 173.0, "gear": "P", "speed_kmh": 0.0, "temp_c": 27.0, "odometer": 12345.0,
       "plugged": False, "tires": {"fl": 33.0, "fr": 33.2, "rl": 32.1, "rr": 33.2}}


@pytest.fixture(autouse=True)
def no_adb(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"adb must not run in UI tests: {args}")

    monkeypatch.setattr(adb, "run", refuse)
    monkeypatch.setattr(adb, "connect", refuse)


@pytest.fixture
def make_app(tmp_path):
    apps = []

    def make(**opts):
        settings = Settings(tmp_path / f"s{len(apps)}.json")
        settings.update(auto_connect=False, **opts)
        root = tk.Tk()
        app = ui.App(root, settings, selftest=True)
        root.update()
        apps.append(app)
        return app

    yield make
    for app in apps:
        try:
            app.quit()
        except tk.TclError:
            pass


def box(widget):
    widget.update_idletasks()
    x, y = widget.winfo_rootx() - widget.winfo_toplevel().winfo_rootx(), \
        widget.winfo_rooty() - widget.winfo_toplevel().winfo_rooty()
    return x, y, x + widget.winfo_width(), y + widget.winfo_height()


def mapped_descendants(widget):
    for child in widget.winfo_children():
        if child.winfo_ismapped():
            yield child
            yield from mapped_descendants(child)


def test_palette_is_restrained_oled():
    pal = widgets.palette("oled")
    assert pal["bg"] == "#000000"
    assert pal["accent"] == "#b9d4e8"       # pale steel blue, not a saturated neon
    assert widgets.palette("dark")["bg"] != "#000000"
    for key in ("text", "muted", "line", "track", "live", "warn", "bad", "down", "up", "accent_ink"):
        assert key in pal


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_main_is_centred_and_dominant(make_app, size):
    app = make_app(size=size)
    root = app.root
    main, hud, cluster = (app.screens[n].canvas for n in ("main", "hud", "cluster"))
    mx1, my1, mx2, my2 = box(main)
    centre = (mx1 + mx2) / 2
    assert abs(centre - root.winfo_width() / 2) <= 4, "Main is centred in the window"
    # the tray pictures grew (HUD was too small), so Main dominates by area rather than by 2x the width
    area = lambda c: (box(c)[2] - box(c)[0]) * (box(c)[3] - box(c)[1])  # noqa: E731
    assert area(main) >= 3 * area(cluster) and area(main) >= 3 * area(hud), "Main dominates the auxiliary screens"
    assert (mx2 - mx1) > box(cluster)[2] - box(cluster)[0] > box(hud)[2] - box(hud)[0]
    assert box(hud)[1] > my2 and box(cluster)[1] > my2, "HUD and Cluster sit below Main"
    px1, py1, px2, py2 = box(app.car_panel)
    assert px1 >= mx2 and py1 < my2 and py2 > my1, "car status is a rail to the right of Main"
    assert px2 <= root.winfo_width(), "the car rail stays inside the window"
    assert box(app.floor)[1] >= box(cluster)[3], "system floor is the bottom strip"


def test_aux_sizes_keep_screen_aspect(make_app):
    app = make_app(size="medium")
    sizes = app.sizes()
    w, h = sizes["hud"]
    assert abs(w / h - 800 / 480) < 0.04
    w, h = sizes["cluster"]
    assert abs(w / h - 1920 / 532) < 0.06
    w, h = sizes["main"]
    assert abs(w / h - 2560 / 1600) < 0.02


@pytest.mark.parametrize("language", ["th", "en"])
@pytest.mark.parametrize("size", ["small", "medium"])
def test_nothing_overflows_the_window(make_app, size, language):
    app = make_app(size=size, language=language)
    app.car_panel.update_data(car=CAR, tcam={"network": "4G", "level": 3, "operator": "TrueMove H"},
                              gps={"lat": 0.0, "lon": 0.0, "heading": 0.0, "speed": 0.0})
    app.root.update()
    width, height = app.root.winfo_width(), app.root.winfo_height()
    for widget in mapped_descendants(app.root):
        x1, y1, x2, y2 = box(widget)
        assert x2 <= width + 1 and y2 <= height + 1, f"{widget} {x1, y1, x2, y2} outside {width}x{height}"
    # carpanel text stays inside its own canvas
    panel = app.car_panel
    for item in panel.find_all():
        if panel.type(item) == "text" and panel.itemcget(item, "text"):
            bx1, _by1, bx2, _by2 = panel.bbox(item)
            assert bx1 >= 0 and bx2 <= int(panel["width"]) + 1, panel.itemcget(item, "text")


def test_small_preset_fits_1024_wide_screen(make_app):
    app = make_app(size="small")
    assert app.root.winfo_reqwidth() <= 1024
    assert app.root.winfo_reqheight() <= 768


def test_medium_fits_1600x900(make_app):
    app = make_app(size="medium")
    assert app.root.winfo_reqwidth() <= 1600 - 16
    assert app.root.winfo_reqheight() <= 900 - 90


def test_control_is_off_by_default_and_main_only(make_app):
    app = make_app()
    assert app.s["control"] is False
    assert app.control_var.get() is False
    main = app.screens["main"]
    assert main.canvas.itemcget(main.outline, "outline") != app.pal["accent"]
    app.control_var.set(True)
    app.set_control(True)
    assert app.s["control"] is True
    assert main.canvas.itemcget(main.outline, "outline") == app.pal["accent"]
    # HUD stays view only: no touch bindings on its canvas
    assert not app.screens["hud"].canvas.bind("<ButtonPress-1>")


def test_wifi_and_usb_fields(make_app):
    app = make_app()
    assert app.ip_entry.winfo_ismapped() and not app.usb_pick.winfo_ismapped()
    app.set_link("usb")
    app.root.update()
    assert app.usb_pick.winfo_ismapped() and not app.ip_entry.winfo_ismapped()
    assert app.t("no_usb") in app.usb_pick["text"]
    app.set_link("wifi")
    app.root.update()
    assert app.ip_entry.winfo_ismapped()


def test_bad_ip_shows_error_without_adb(make_app):
    app = make_app()
    app.ip_var.set("not an ip")
    app.connect()
    assert app.conn == "idle"
    assert app.conn_label["text"] == app.t("bad_ip")


def test_cluster_refresh_switch_and_states(make_app):
    app = make_app()
    app.set_cluster_refresh(False)
    assert app.s["cluster_refresh"] is False
    app.set_state("cluster", "paused")
    assert app.screens["cluster"].state_label["text"] == app.t("st_paused")
    app.set_state("main", "live")
    assert app.screens["main"].state_label["text"] == app.t("st_live")


def test_ex2_has_no_hud(make_app):
    app = make_app(model="EX2")
    assert "hud" not in app.screens and "cluster" not in app.screens
    assert "main" in app.screens


def test_settings_panel_toggle_and_rebuild(make_app):
    app = make_app()
    app.toggle_settings()
    app.root.update()
    assert app.settings_panel is not None and app.gear.active
    x1, y1, x2, y2 = box(app.settings_panel)
    assert x2 <= app.root.winfo_width() and y1 >= box(app.gear)[3]
    app.change_setting("language", "en")   # rebuild keeps the panel open
    app.root.update()
    assert app.settings_panel is not None
    assert app.conn_button.text == "Connect"
    app.close_settings()
    assert app.settings_panel is None and not app.gear.active


def test_drag_resize_grows_screens(make_app):
    app = make_app(size="small")
    before = app.sizes()["main"][0]
    app.root.geometry("1500x1000")
    app.root.update()
    app.fit_to_window()
    app.root.update()
    assert app.sizes()["main"][0] > before
    assert app._built_req[0] <= 1500 and app._built_req[1] <= 1000


def test_car_panel_shows_values_when_connected(make_app):
    app = make_app()
    app.conn = "connected"
    app.car_panel.update_data(car=CAR)
    app.root.update()
    texts = {app.car_panel.itemcget(i, "text") for i in app.car_panel.find_all() if app.car_panel.type(i) == "text"}
    assert "34" in texts and "173" in texts and "P" in texts
    assert any("33.0" in t for t in texts)


# ---------- 1.1.2/1.1.3 features inside this layout ----------
def test_default_theme_is_oled(make_app):
    app = make_app()
    assert app.s["theme"] == "oled" and app.pal["bg"] == "#000000"
    app.change_setting("theme", "telemetry")  # the teal palette stays a choice; the layout does not change
    assert app.pal["bg"] == widgets.palette("telemetry")["bg"] != "#000000"
    assert set(app.screens) == {"main", "hud", "cluster"}


@pytest.mark.parametrize("language", ["th", "en"])
def test_apk_tab_opens_over_stage_and_tray(make_app, language):
    """The APK workspace is reachable from the top bar and replaces the stage + tray only: the top bar and the
    system floor stay, and the window does not change size."""
    app = make_app(size="small", language=language)
    root = app.root
    assert app.apk_tab.winfo_ismapped() and app.apk_tab.text == "APK"
    assert not app.apk_panel.winfo_ismapped()
    before = (root.winfo_width(), root.winfo_height())
    app.toggle_apk()
    root.update()
    assert app.apk_open and app.apk_panel.winfo_ismapped()
    assert app.apk_tab.text == app.t("apk_back")
    assert (root.winfo_width(), root.winfo_height()) == before
    panel, body = box(app.apk_panel), box(app.screen_body)
    assert panel == body
    for name in ("main", "hud", "cluster"):  # every screen is under the workspace
        left, top, right, bottom = box(app.screens[name].canvas)
        assert panel[0] <= left and panel[1] <= top and right <= panel[2] and bottom <= panel[3]
    assert box(app.floor)[1] >= panel[3] and app.floor.winfo_ismapped()
    assert app.conn_button.winfo_ismapped() and box(app.conn_button)[3] <= panel[1]
    for widget in (app.apk_choose, app.apk_install, app.apk_drop, app.apk_status, app.apk_override_check):
        assert widget.winfo_ismapped()
        left, top, right, bottom = box(widget)
        assert panel[0] <= left and panel[1] <= top and right <= panel[2] and bottom <= panel[3], widget
    app.change_setting("language", "en" if language == "th" else "th")  # a rebuild keeps the tab open
    root.update()
    assert app.apk_open and app.apk_panel.winfo_ismapped()
    app.toggle_apk()
    root.update()
    assert not app.apk_panel.winfo_ismapped() and app.apk_tab.text == "APK"
    assert app.screens["main"].canvas.winfo_ismapped()


def test_pc_gpu_meter_only_where_it_is_polled(make_app):
    """Linux does not poll the host GPU (1.1.3): the floor has no PC GPU meter there, the car keeps its own."""
    app = make_app()
    assert ("GPU" in app.meters_box["pc"]) == (not ui.sys.platform.startswith("linux"))
    assert "GPU" in app.meters_box["car"]
    app.show_stats({"cpu": 10.0, "gpu": None, "ram": (2 ** 30, 2 ** 31)}, None, None, [], 0)  # must not raise
    assert app.meters_box["pc"]["CPU"].value.cget("text") == "10%"


@pytest.mark.parametrize("language", ["th", "en"])
@pytest.mark.parametrize("connected", [False, True])
def test_apk_workspace_text_is_not_cut_off(make_app, language, connected):
    """At the small size the target card is narrow: its sentences wrap inside the card instead of being clipped."""
    app = make_app(size="small", language=language)
    if connected:
        app.conn, app.serial, app.model = "connected", "192.0.2.25:5566", "EX5"
    app.toggle_apk()
    app.root.update()
    panel = box(app.apk_panel)
    labels = [w for w in mapped_descendants(app.apk_panel) if isinstance(w, tk.Label)]
    assert len(labels) >= 8
    for label in labels:
        assert label.winfo_reqwidth() <= label.winfo_width() + 1, label.cget("text")
        left, top, right, bottom = box(label)
        parent = box(label.master)
        assert parent[0] <= left and right <= parent[2] and parent[1] <= top and bottom <= parent[3], \
            label.cget("text")
        assert bottom <= panel[3]
    assert app.apk_serial_entry.winfo_ismapped() == connected
    assert app.apk_hint.winfo_ismapped() == (not connected)
    if connected:
        assert app.apk_serial.get() == "192.0.2.25:5566"
