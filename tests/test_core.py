import io
import socket
import struct
import sys
import threading
import time

import paramiko
import pytest

from ex5viewer import adb, cluster, scrcpy, stats
from ex5viewer.i18n import STRINGS, Translator
from ex5viewer.settings import DEFAULTS, Settings


# ---------- adb ----------
@pytest.mark.parametrize("text, expected", [
    ("192.168.1.114", "192.168.1.114:5566"),
    (" 192.168.1.114:5555 ", "192.168.1.114:5555"),
    ("", None), ("abc", None), ("192.168.1", None), ("300.1.1.1", None),
    ("1.2.3.4:0", None), ("1.2.3.4:70000", None), ("1.2.3.4; rm -rf ~", None), ("1.2.3.4:55:66", None),
])
def test_parse_address(text, expected):
    assert adb.parse_address(text, 5566) == expected


def test_parse_devices_keeps_ready_ones_with_model():
    out = ("List of devices attached\n"
           "0123456789abcdef device usb:1-1 product:antora model:Geely_EX5 device:x transport_id:4\n"
           "192.168.1.114:5566 offline\n"
           "emulator-5580 device product:sdk model:sdk_car\n")
    assert adb.parse_devices(out) == [("0123456789abcdef", "Geely_EX5"), ("emulator-5580", "sdk_car")]


@pytest.mark.parametrize("info, model", [
    ({"ro.product.model": "Geely_EX5", "ro.board.platform": "se1000"}, "EX5"),
    ({"ro.product.model": "", "ro.board.platform": "se1000"}, "EX5"),
    ({"ro.hardware": "xecarx", "ro.product.model": "E245"}, "EX2"),
    ({"ro.product.model": "Geely EX2"}, "EX2"),
    ({"ro.product.model": "sdk_car", "ro.board.platform": "ranchu"}, None),
])
def test_detect_model(info, model):
    assert adb.detect_model(info) == model


# ---------- scrcpy protocol ----------
def test_parse_header_session_and_media():
    session = bytes([0x80, 0, 0, 0]) + struct.pack(">II", 2560, 1600)
    assert scrcpy.parse_header(session) == ("session", 2560, 1600)
    config = struct.pack(">QI", (1 << 62) | 5, 31)
    assert scrcpy.parse_header(config) == ("media", True, 31)
    frame = struct.pack(">QI", (1 << 61) | 123456, 9000)
    assert scrcpy.parse_header(frame) == ("media", False, 9000)


def test_touch_message_matches_scrcpy_layout():
    message = scrcpy.touch_message(scrcpy.TOUCH_DOWN, 100, 200, 1080, 1920)
    assert len(message) == 32
    assert message[0] == 2 and message[1] == 0
    assert message[2:10] == b"\xff" * 7 + b"\xfe"            # generic finger pointer id (-2)
    assert message[10:18] == bytes.fromhex("00000064000000c8")  # 100, 200
    assert message[18:22] == bytes.fromhex("04380780")          # 1080x1920
    assert message[22:24] == b"\xff\xff"                       # pressure 1.0
    assert scrcpy.touch_message(scrcpy.TOUCH_UP, 0, 0, 10, 10)[22:24] == b"\x00\x00"


def test_recv_exact_reassembles_and_reports_close():
    a, b = socket.socketpair()
    a.settimeout(1)
    stop = threading.Event()
    b.sendall(b"abc")
    threading.Timer(0.05, lambda: b.sendall(b"def")).start()
    assert scrcpy.recv_exact(a, 6, stop) == b"abcdef"
    b.close()
    with pytest.raises(scrcpy.StreamError):
        scrcpy.recv_exact(a, 1, stop)


# ---------- cluster ----------
def bmp(color, size=(8, 4)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "BMP")
    return buffer.getvalue()


def test_read_bmp_stream_and_garbage():
    stream = io.BytesIO(bmp("red") + bmp("blue"))
    assert cluster.read_bmp(stream)[:2] == b"BM"
    assert cluster.read_bmp(stream) is not None
    assert cluster.read_bmp(stream) is None
    assert cluster.read_bmp(io.BytesIO(b"XXXXXXXXXXXX")) is None
    assert cluster.read_bmp(io.BytesIO(bmp("red")[:20])) is None  # cut short


def test_surface_ids():
    listing = "- Surface 4711 (0x1267)\n  bla\n- Surface 20 (0x14)\n"
    assert cluster.surface_ids(listing) == ["4711", "20"]


class FakeCluster(paramiko.ServerInterface):
    """dropbear stand-in: root, no password, answers the two commands ClusterStream sends."""

    def __init__(self):
        self.commands = []

    def get_allowed_auths(self, username):
        return "none,password"

    def check_auth_none(self, username):
        return paramiko.AUTH_SUCCESSFUL if username == "root" else paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_exec_request(self, channel, command):
        command = command.decode()
        self.commands.append(command)

        def answer():
            time.sleep(0.2)  # let the exec reply go out before data/close
            if "get surfaces" in command:
                channel.sendall(b"- Surface 4711 (0x1267)\n")
            else:
                for color in ("red", "green", "blue"):
                    channel.sendall(bmp(color, (192, 53)))
            channel.send_exit_status(0)
            channel.close()

        threading.Thread(target=answer, daemon=True).start()
        return True


def fake_cluster_server():
    """Listening port + a relay command that plays the role of `adb shell ... nc` (stdin/stdout <-> TCP)."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    server = FakeCluster()

    def serve():
        conn, _ = listener.accept()
        transport = paramiko.Transport(conn)
        transport.add_server_key(paramiko.RSAKey.generate(1024))
        transport.start_server(server=server)
        transport.join()

    threading.Thread(target=serve, daemon=True).start()
    relay = ("import socket,sys,threading;s=socket.create_connection(('127.0.0.1',%d));"
             "threading.Thread(target=lambda:[(sys.stdout.buffer.write(d),sys.stdout.buffer.flush()) "
             "for d in iter(lambda:s.recv(65536),b'')],daemon=True).start();"
             "[s.sendall(d) for d in iter(lambda:sys.stdin.buffer.read1(65536),b'')]") % listener.getsockname()[1]
    return server, [sys.executable, "-c", relay]


def test_cluster_stream_over_pipe_socket():
    server, relay = fake_cluster_server()
    frames, states, meter = [], [], stats.Meter()
    done = threading.Event()

    def on_frame(name, image):
        frames.append(image)
        if len(frames) == 3:
            done.set()

    stream = cluster.ClusterStream("serial", 1.0, lambda: (96, 26), on_frame, lambda n, s: states.append(s), meter,
                                   reconnect=False, proxy_args=relay)
    stream.start()
    assert done.wait(20), f"frames={len(frames)} states={states}"
    stream.stop()
    stream.join(10)
    assert [img.size for img in frames] == [(96, 26)] * 3
    assert frames[0].getpixel((0, 0)) == (255, 0, 0) and frames[2].getpixel((0, 0)) == (0, 0, 255)
    assert states[:2] == ["connecting", "live"]
    assert "dump surface 4711" in server.commands[1]
    down, up = meter.take()
    assert down > 3 * 192 * 53 * 3 and up > 0  # raw ssh bytes, both directions


# ---------- stats ----------
def test_cpu_and_memory_parsing():
    before = stats.cpu_times("cpu  100 0 100 800 0 0 0 0 0 0")
    after = stats.cpu_times("cpu  150 0 150 900 0 0 0 0 0 0")
    assert stats.cpu_percent(before, after) == pytest.approx(50.0)
    used, total = stats.mem_used("MemTotal: 8000 kB\nMemFree: 1000 kB\nMemAvailable: 2000 kB\n")
    assert (used, total) == (6000 * 1024, 8000 * 1024)
    assert stats.parse_gpu("37 %") == 37.0 and stats.parse_gpu("garbage") is None and stats.parse_gpu("999") is None


def test_history_rates_and_drops():
    history = stats.History(seconds=3)
    history._last -= 1.0
    down, up = history.tick(1_000_000, 125_000)
    assert down == pytest.approx(8.0, rel=0.05) and up == pytest.approx(1.0, rel=0.05)
    history.mark_drop()
    history.tick(0, 0)
    assert list(history.drops) == [1]
    history.tick(0, 0)
    history.tick(0, 0)
    assert list(history.drops) == []  # scrolled off the 3-sample graph
    assert len(history.samples) == 3


# ---------- settings / i18n ----------
def test_settings_roundtrip_and_bad_values(tmp_path):
    path = tmp_path / "s.json"
    s = Settings(path)
    s.set("language", "en")
    s.set("port", 99999)          # rejected
    s.set("max_fps", 45)          # not a choice
    assert Settings(path)["language"] == "en"
    assert Settings(path)["port"] == DEFAULTS["port"] and Settings(path)["max_fps"] == 30
    path.write_text("{not json")
    assert Settings(path)["language"] == "th"  # broken file -> defaults, no crash
    s.reset()
    assert dict(Settings(path)) == DEFAULTS


def test_every_string_has_both_languages_and_formats():
    for key, (th, en) in STRINGS.items():
        assert th and en, key
        assert th.count("{") == en.count("{"), key
    assert Translator("en")("refresh", s="1") == "Refresh 1s"
