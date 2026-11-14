"""UI stability (audit F3, F4, F5). Needs a display (Xvfb is fine):
    Xvfb :93 -screen 0 1920x1080x24 &  DISPLAY=:93 pytest tests/test_stability.py
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
    """Stands in for VideoStream / ClusterStream: keeps the callbacks so a test can play the worker thread."""
    made = []

    def __init__(self, *args, **kwargs):
        callables = [a for a in args if callable(a)]
        self.on_frame, self.on_state = callables[-2], callables[-1]
        self.started = self.stopped = False
        FakeStream.made.append(self)

    def start(self):
        self.started = True

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


def scheduled(app):
    """Names of the Python callbacks waiting in Tk's after queue."""
    names = []
    for job in app.root.tk.splitlist(app.root.tk.call("after", "info")):
        script = app.root.tk.splitlist(app.root.tk.call("after", "info", job))[0]
        names.append(str(script))
    return " ".join(names)


def fake_connected(app, address="192.168.1.114:5566"):
    app.serial, app.address, app.model, app.conn = address, address, "EX5", "connected"
    app.start_streams()
    for name, stream in app.streams.items():
        stream.on_state(name, "live")
    pump(app)


def test_refresh_survives_a_failing_task(app):
    """F3: a non-Tcl exception in a worker task must not stop the UI pump."""
    ran = []

    def boom():
        raise ValueError("probe")

    app.ui(boom)
    app.ui(lambda: ran.append(True))
    pump(app)
    assert ran == [True]
    assert "refresh" in scheduled(app)
    app.ui(lambda: ran.append(True))  # and it keeps pumping afterwards
    pump(app)
    assert ran == [True, True]


def test_tick_survives_an_exception(app, monkeypatch):
    """F3: tick reschedules itself even when its body raises."""
    def broken(*_args):
        raise KeyError("probe")

    monkeypatch.setattr(app.history, "tick", broken)
    app.tick()  # must not raise
    assert "tick" in scheduled(app)


def test_bad_ip_while_connected_keeps_the_session(app):
    """F4: a typo in the address must not stop the streams and leave the screens saying Live."""
    fake_connected(app)
    streams = dict(app.streams)
    assert set(streams) == {"main", "hud", "cluster"}
    app.ip_var.set("300.1.1.1")
    app.connect()
    pump(app)
    assert app.conn == "connected" and app.streams == streams
    assert not any(stream.stopped for stream in streams.values())
    assert {name: screen.state for name, screen in app.screens.items()} == dict.fromkeys(streams, "live")


def test_empty_usb_serial_while_connected_keeps_the_session(app):
    """F4: the USB path validates first too."""
    fake_connected(app)
    streams = dict(app.streams)
    app.s.set("usb_serial", "")
    app.s.set("link", "usb")
    app.connect()
    assert app.conn == "connected" and app.streams == streams
    assert not any(stream.stopped for stream in streams.values())


def test_late_callbacks_from_a_stopped_stream_do_not_repaint(app):
    """F5: after a restart the old stream's late state/frame must not reach the new session's screens."""
    fake_connected(app)
    old = app.streams["main"]
    app.stop_streams()
    app.start_streams()
    new = app.streams["main"]
    assert new is not old and old.stopped
    new.on_state("main", "connecting")
    pump(app)
    screen = app.screens["main"]
    screen.has_frame = False
    old.on_state("main", "live")
    old.on_frame("main", Image.new("RGB", (8, 8), "red"))
    pump(app)
    assert screen.state == "connecting" and not screen.has_frame
    new.on_frame("main", Image.new("RGB", (8, 8), "blue"))
    new.on_state("main", "live")
    pump(app)
    assert screen.state == "live" and screen.has_frame


def test_late_cluster_state_after_cluster_toggle(app):
    """F5: a cluster stream switched off must not flip the card back from paused."""
    fake_connected(app)
    old = app.streams["cluster"]
    app.set_cluster_refresh(False)
    assert app.screens["cluster"].state == "paused"
    old.on_state("cluster", "live")
    pump(app)
    assert app.screens["cluster"].state == "paused"


# ---------- Linux safe rendering (1.1.3) keeps working with the guarded callbacks ----------
class RecordingStream(FakeStream):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.kwargs = kwargs


def test_safe_rendering_caps_fps_and_disables_animations(tmp_path, monkeypatch):
    from ex5viewer import widgets
    FakeStream.made = []
    monkeypatch.setattr(ui, "VideoStream", RecordingStream)
    monkeypatch.setattr(ui, "ClusterStream", RecordingStream)
    settings = Settings(tmp_path / "s.json")
    settings.update(auto_connect=True, address="192.0.2.25:5566", max_fps=30, animations=True)
    root = tk.Tk()
    app = ui.App(root, settings, safe_rendering=True)
    try:
        root.update()
        assert widgets.ANIMATE is False
        assert "connect" not in scheduled(app)  # no auto-connect in safe mode
        assert app.conn == "idle"
        fake_connected(app)
        # GPU-freeze mitigation: 8 fps (was 12) and an ~125 ms UI pump
        assert app.streams["main"].kwargs["max_fps"] == ui.SAFE_FPS == 8
        assert app.streams["hud"].kwargs["max_fps"] == 8
        assert app.refresh_ms == ui.SAFE_REFRESH_MS == 125
        app.frames["main"] = (Image.new("RGB", app.sizes()["main"], "blue"), app.streams["main"])
        pump(app, 0.3)  # the slower pump still shows frames
        assert app.screens["main"].has_frame
    finally:
        app.quit()
    settings.update(auto_connect=False)
    root = tk.Tk()
    app = ui.App(root, settings, selftest=True)
    try:
        root.update()
        assert widgets.ANIMATE is True
        fake_connected(app)
        assert app.streams["main"].kwargs["max_fps"] == 30
    finally:
        app.quit()
