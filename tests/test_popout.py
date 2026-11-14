"""Pop-out windows: a popped screen renders only in its own window, the docked slot keeps its size with a
placeholder, closing the window re-docks it, and each stream is still decoded once.

Needs a display (Xvfb is fine):  Xvfb :93 -screen 0 1920x1080x24 &  DISPLAY=:93 pytest tests/test_popout.py
adb is stubbed and the streams are fakes: these tests never start an adb process.
"""
import os
import time
import tkinter as tk

import pytest
from PIL import Image

from ex5viewer import adb, ui
from ex5viewer.settings import Settings

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs DISPLAY (run under Xvfb)")

adb.usb_devices = lambda: []  # the App's stats thread lists USB devices every 2 s


@pytest.fixture(autouse=True)
def no_adb(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"adb must not run in UI tests: {args}")

    monkeypatch.setattr(adb, "run", refuse)
    monkeypatch.setattr(adb, "connect", refuse)


class FakeStream:
    """Stands in for VideoStream / ClusterStream and keeps its size callback, like the real decoder thread."""
    made = []

    def __init__(self, *args, **kwargs):
        callables = [a for a in args if callable(a)]
        self.size_fn, self.on_frame, self.on_state = callables[-3], callables[-2], callables[-1]
        self.stopped = False
        FakeStream.made.append(self)

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def is_alive(self):
        return False


@pytest.fixture
def app(tmp_path, monkeypatch):
    FakeStream.made = []
    monkeypatch.setattr(ui, "VideoStream", FakeStream)
    monkeypatch.setattr(ui, "ClusterStream", FakeStream)
    settings = Settings(tmp_path / "s.json")
    settings.update(auto_connect=False, cluster_refresh=True)
    root = tk.Tk()
    app = ui.App(root, settings, selftest=True)
    root.update()
    yield app
    try:
        app.quit()
    except tk.TclError:
        pass


def pump(app, seconds=0.15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.root.update()
        time.sleep(0.01)


def connect(app):
    app.serial, app.address, app.model, app.conn = "192.0.2.25:5566", "192.0.2.25:5566", "EX5", "connected"
    app.start_streams()
    for name, stream in app.streams.items():
        stream.on_state(name, "live")
    pump(app)


def deliver(app, name, colour):
    """Play the stream thread: one decode at the stream's size callback, one on_frame."""
    stream = app.streams[name]
    image = Image.new("RGB", stream.size_fn(), colour)
    stream.on_frame(name, image)
    pump(app)
    return image


def test_every_stream_screen_has_a_popout_button(app):
    assert set(app.popout_buttons) == {"main", "hud", "cluster"}
    for name, button in app.popout_buttons.items():
        assert button.winfo_ismapped(), name
    assert app.t("popout") and app.t("popped_title") and app.t("dock")


@pytest.mark.parametrize("name", ["main", "hud", "cluster"])
def test_popped_screen_renders_only_in_its_window(app, name):
    connect(app)
    docked = app.screens[name]
    slot = (docked.canvas.winfo_width(), docked.canvas.winfo_height())
    window = app.popout(name)
    pump(app)
    assert isinstance(window.top, tk.Toplevel) and window.top.winfo_exists()
    assert app.view(name) is window.screen and app.view(name) is not docked
    assert docked.popped and docked.canvas.find_withtag("message"), "placeholder in the main window"
    assert app.popout_buttons[name].active

    shown = []
    docked_show = docked.show
    docked.show = lambda image: (shown.append("docked"), docked_show(image))
    deliver(app, name, "red")
    assert shown == [], "a popped screen must not render in the main window too"
    assert window.screen.has_frame and window.screen.image.getpixel((0, 0)) == (255, 0, 0)
    assert not docked.has_frame
    assert (docked.canvas.winfo_width(), docked.canvas.winfo_height()) == slot, "the docked slot keeps its size"


def test_popout_decodes_once_at_the_window_size(app):
    connect(app)
    streams_before = list(FakeStream.made)
    window = app.popout("hud")
    pump(app)
    assert FakeStream.made == streams_before, "popping out starts no second stream (no second decode)"
    assert app.streams["hud"].size_fn() == window.screen.viewport != app.sizes()["hud"]
    image = deliver(app, "hud", "green")
    assert image.size == window.screen.viewport
    assert window.screen.image is image, "the one decoded picture goes to the window as is"
    app.dock("hud")
    assert app.streams["hud"].size_fn() == app.sizes()["hud"], "back to the docked size after re-docking"


def test_closing_the_window_docks_the_screen_back(app):
    connect(app)
    window = app.popout("main")
    pump(app)
    deliver(app, "main", "blue")
    top = window.top
    top.tk.call(top.protocol("WM_DELETE_WINDOW"))  # what the window manager's close button runs
    pump(app)
    assert "main" not in app.popouts and not top.winfo_exists()
    docked = app.screens["main"]
    assert not docked.popped and not docked.canvas.find_withtag("dock")
    assert not app.popout_buttons["main"].active
    deliver(app, "main", "yellow")
    assert docked.has_frame and docked.image.getpixel((0, 0)) == (255, 255, 0)


def test_popout_button_toggles(app):
    app.toggle_popout("cluster")
    pump(app)
    assert "cluster" in app.popouts
    app.toggle_popout("cluster")
    pump(app)
    assert "cluster" not in app.popouts and not app.screens["cluster"].popped


def test_disconnect_closes_popouts(app, monkeypatch):
    monkeypatch.setattr(adb, "disconnect", lambda *a, **k: None)
    connect(app)
    tops = [app.popout(name).top for name in ("main", "hud", "cluster")]
    pump(app)
    app.disconnect(quiet=True)
    pump(app)
    assert app.popouts == {}
    assert not any(top.winfo_exists() for top in tops)
    assert not any(screen.popped for screen in app.screens.values())


def test_quit_closes_popouts(tmp_path, monkeypatch):
    FakeStream.made = []
    monkeypatch.setattr(ui, "VideoStream", FakeStream)
    monkeypatch.setattr(ui, "ClusterStream", FakeStream)
    settings = Settings(tmp_path / "s.json")
    settings.update(auto_connect=False)
    root = tk.Tk()
    app = ui.App(root, settings, selftest=True)
    root.update()
    connect(app)
    window = app.popout("hud")
    pump(app)
    app.quit()
    assert app.popouts == {}
    assert all(stream.stopped for stream in FakeStream.made)
    with pytest.raises(tk.TclError):
        window.top.winfo_exists()  # the window is gone with the app


def test_popout_survives_a_rebuild(app):
    connect(app)
    app.popout("hud")
    pump(app)
    deliver(app, "hud", "red")
    app.change_setting("language", "en")  # rebuilds the main window
    pump(app)
    window = app.popouts["hud"]
    assert window.top.winfo_exists() and window.screen.has_frame
    assert app.screens["hud"].popped and app.screens["hud"].canvas.find_withtag("message")
    assert sum(isinstance(w, tk.Toplevel) for w in app.root.winfo_children()) == 1


def test_late_state_reaches_the_popout(app):
    connect(app)
    window = app.popout("main")
    pump(app)
    app.streams["main"].on_state("main", "reconnecting")
    pump(app)
    assert window.screen.state == "reconnecting" == app.screens["main"].state


def test_popout_resize_refits_the_picture(app):
    connect(app)
    window = app.popout("main")
    pump(app)
    before = window.screen.viewport
    window.top.geometry("700x500")
    pump(app, 0.5)
    window.refit()
    after = window.screen.viewport
    assert after != before and after[0] <= 700 and after[1] <= 500
    assert abs(after[0] / after[1] - 2560 / 1600) < 0.02
    assert app.streams["main"].size_fn() == after


def test_screen_reuses_its_frame_buffers(app):
    """GPU-freeze mitigation: steady-state frames allocate no PhotoImage and no letterbox buffer."""
    screen = app.screens["hud"]
    screen.state = "live"
    photo = screen.photo
    w, h = screen.viewport
    odd = (w - 20, h)  # a picture of another size goes through the letterbox buffer
    screen.show(Image.new("RGB", odd, "red"))
    buffer = screen._letterbox
    assert buffer is not None and buffer.size == screen.viewport
    for colour in ("green", "blue", "white"):
        screen.show(Image.new("RGB", odd, colour))
        assert screen._letterbox is buffer, "letterbox buffer reused"
        assert screen.photo is photo, "PhotoImage reused"
    screen.show(Image.new("RGB", screen.viewport, "red"))  # exact size: pasted straight in
    assert screen.photo is photo
    screen.show(Image.new("RGBA", screen.viewport, "red"))  # converted to the PhotoImage's mode first
    assert screen.photo is photo
