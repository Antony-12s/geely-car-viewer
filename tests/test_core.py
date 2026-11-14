import io
import socket
import struct
import subprocess
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
            elif command.startswith("command -v"):
                pass  # no ffmpeg: the stream falls back to raw BMP frames
            else:
                for color in ("red", "green", "blue"):
                    channel.sendall(bmp(color, (192, 53)))
            channel.send_exit_status(0)
            channel.close()

        threading.Thread(target=answer, daemon=True).start()
        return True


def fake_cluster_server(server=None):
    """Listening port + a relay command that plays the role of `adb shell ... nc` (stdin/stdout <-> TCP)."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    server = server or FakeCluster()

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
    assert not stream.is_alive()
    assert [img.size for img in frames] == [(96, 26)] * 3
    assert frames[0].getpixel((0, 0)) == (255, 0, 0) and frames[2].getpixel((0, 0)) == (0, 0, 255)
    assert states[:2] == ["connecting", "live"]
    assert "dump surface 4711" in server.commands[2]
    down, up = meter.take()
    assert down > 3 * 192 * 53 * 3 and up > 0  # raw ssh bytes, both directions


# ---------- stats ----------
def test_cpu_and_memory_parsing():
    before = stats.cpu_times("cpu  100 0 100 800 0 0 0 0 0 0")
    after = stats.cpu_times("cpu  150 0 150 900 0 0 0 0 0 0")
    assert stats.cpu_percent(before, after) == pytest.approx(50.0)
    used, total = stats.mem_used("MemTotal: 8000 kB\nMemFree: 1000 kB\nMemAvailable: 2000 kB\n")
    assert (used, total) == (6000 * 1024, 8000 * 1024)
    assert stats.parse_gpu("37 %") == 37.0
    assert stats.parse_gpu("gpu utilisation    : 58") == 58.0  # first line of the EX5 Mali file and stats.parse_gpu("garbage") is None and stats.parse_gpu("999") is None


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
    s.set("language", "th")
    s.set("port", 99999)          # rejected
    s.set("max_fps", 45)          # not a choice
    assert Settings(path)["language"] == "th"
    assert Settings(path)["port"] == DEFAULTS["port"] and Settings(path)["max_fps"] == 30
    path.write_text("{not json")
    assert Settings(path)["language"] == "en"  # broken file -> defaults, no crash
    s.reset()
    assert dict(Settings(path)) == DEFAULTS


def test_every_string_has_both_languages_and_formats():
    for key, (th, en) in STRINGS.items():
        assert th and en, key
        assert th.count("{") == en.count("{"), key
    assert Translator("en")("refresh", s="1") == "Refresh 1s"


def test_transport_close_over_pipe_socket():
    """paramiko's close() reads sock._closed; PipeSocket lacked it and the close blew up mid-way."""
    _server, relay = fake_cluster_server()
    sock = cluster.PipeSocket(relay)
    transport = cluster.open_transport(sock)
    transport.close()
    sock.close()
    assert sock._closed


def test_jpeg_reader_splits_mjpeg_stream():
    from PIL import Image
    jpegs = []
    for color in ("red", "blue"):
        buffer = io.BytesIO()
        Image.new("RGB", (16, 8), color).save(buffer, "JPEG")
        jpegs.append(buffer.getvalue())
    reader = cluster.JpegReader(io.BytesIO(b"".join(jpegs)))
    assert reader.read() == jpegs[0] and reader.read() == jpegs[1] and reader.read() is None


def test_capture_script_sleeps_alongside_the_dump():
    script = cluster.capture_script("4711", 0.5, jpeg=True)
    assert "sleep 0.5 & nice -n 19 LayerManagerControl dump surface 4711" in script
    assert "; wait; done" in script and "ffmpeg" in script and "kill $!" in script


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the script runs on the Linux cluster; needs /proc")
def test_capture_script_removes_only_dead_sessions_files(tmp_path):
    """Run the cleanup part in a real sh: keeps the file of a live pid, drops dead ones and the old name."""
    import os, subprocess
    script = cluster.capture_script("1", 1, jpeg=True)
    stale = script[script.index("for g in"):script.index("done;") + 5].replace("/tmp/", f"{tmp_path}/")
    live, dead, old = (tmp_path / f"ex5c-{os.getpid()}.bmp", tmp_path / "ex5c-999999999.bmp", tmp_path / "ex5c.bmp")
    for path in (live, dead, old):
        path.write_bytes(b"BM")
    subprocess.run(["sh", "-c", stale], check=True)
    assert live.exists() and not dead.exists() and not old.exists()


def test_parse_tcam_from_head_unit_log():
    line = ("11-06 11:42:09.524  3105  3371 W ECARX TCAM: [TCAMServiceImpl] onEsimStatusoNotification{"
            ".available__ = Available_Available, .eSIMConnectionStatus__ = ESIMConnectionStatus_FourGnetwork, "
            ".hispeedfun__ = Hispeedfun_NotSupportHighSpeedFun, .signalstrength__ = 24, .signallevl__ = 4, "
            ".ipadr__ = 10.137.11.196, .dataConnectionStatus__ = DataConnectionStatus_BothConnected, "
            ".eSIMTrafficData__ = {.txbytecount__ = 0, .rxbytecount__ = 0}, .operator__ = Operator_Chinamobile}")
    assert stats.parse_tcam(line) == {"network": "4G", "level": 4, "operator": "China Mobile"}
    offline = line.replace("FourGnetwork", "NoNetwork").replace("Operator_Chinamobile", "Operator_Unknown")
    assert stats.parse_tcam(offline) == {"network": None, "level": 4, "operator": None}
    assert stats.parse_tcam("") is None and stats.parse_tcam("garbage") is None


def test_linux_host_stats_skip_gpu_telemetry(monkeypatch):
    def unexpected_probe(*args, **kwargs):
        pytest.fail("Linux host stats must not probe the GPU")

    monkeypatch.setattr(stats.sys, "platform", "linux")
    monkeypatch.setattr(stats.shutil, "which", unexpected_probe)
    monkeypatch.setattr(stats.subprocess, "run", unexpected_probe)
    monkeypatch.setattr(stats, "open", unexpected_probe, raising=False)

    sample = stats.HostStats().sample()

    assert sample["gpu"] is None and sample["gpu_mhz"] is None
    assert 0 <= sample["cpu"] <= 100
    assert 0 <= sample["ram"][0] <= sample["ram"][1]


def test_car_stats_parses_gpu_clock_and_tcam(monkeypatch):
    out = ("cpu  100 0 100 800 0 0 0 0 0 0\n---\nMemTotal: 8000 kB\nMemFree: 1000 kB\nMemAvailable: 2000 kB\n---\n"
           "gpu utilisation    : 58\ncompute utilisation: 7\n\n---\n106250000\n---\n"
           " eth0.11: 14344625   35242    0    0    0     0          0         3 18033053   43524    0 0 0 0 0 0\n---\n"
           "W ECARX TCAM: onEsimStatusoNotification{.eSIMConnectionStatus__ = ESIMConnectionStatus_FourGnetwork, .signallevl__ = 3, "
           ".operator__ = Operator_Chinamobile}\n"
           "I GOS     : \tposnFromSatlt{ posnLat:13.500000, posnLgt:100.250000, posnAlti:12.000000, posnSpd:0.000000,"
           " posnDir:95.000000, uTCForYr:26}\n")
    monkeypatch.setattr(stats.adb, "run", lambda *a, **k: type("R", (), {"stdout": out})())
    sample = stats.CarStats("x").sample()
    assert sample["gpu"] == 58.0 and sample["gpu_mhz"] == 106
    assert sample["tcam"] == {"network": "4G", "level": 3, "operator": "China Mobile"}
    assert sample["tbox_bytes"] == (14344625, 18033053)
    assert (sample["gps"]["lat"], sample["gps"]["lon"], sample["gps"]["heading"]) == (13.5, 100.25, 95.0)
    no_clock = out.replace("106250000", "")
    monkeypatch.setattr(stats.adb, "run", lambda *a, **k: type("R", (), {"stdout": no_clock})())
    assert stats.CarStats("x").sample()["gpu_mhz"] is None


def test_vehicle_values_from_car_service_output():
    from ex5viewer import vehicle
    out = """Property:0x2160730e,status: 0,timestamp:1,zone:0x0,floatValues: [19.0],int32Values: [],int64Values: [],bytes: [],string:
Property:0x216072da,status: 0,timestamp:1,zone:0x0,floatValues: [98.0],int32Values: [],int64Values: [],bytes: [],string:
Property:0x11600308,status: 2,timestamp:1,zone:0x0,floatValues: [99.0],int32Values: [],int64Values: [],bytes: [],string:
Property:0x216072cc,status: 0,timestamp:1,zone:0x0,floatValues: [39.0],int32Values: [],int64Values: [],bytes: [],string:
Property:0x11600207,status: 0,timestamp:1,zone:0x0,floatValues: [10.0],int32Values: [],int64Values: [],bytes: [],string:
Property:0x11400400,status: 0,timestamp:1,zone:0x0,floatValues: [],int32Values: [4],int64Values: [],bytes: [],string:
Property:0x11600204,status: 0,timestamp:1,zone:0x0,floatValues: [28149.0],int32Values: [],int64Values: [],bytes: [],string:
Property:0x1120030a,status: 0,timestamp:0,zone:0x0,floatValues: [],int32Values: [1],int64Values: [],bytes: [],string:
Property:0x1160030c,status: 0,timestamp:0,zone:0x0,floatValues: [-7200000.0],int32Values: [],int64Values: [],bytes: [],string:
Property:0x17600309,status: 0,timestamp:1,zone:0x1,floatValues: [35.600002],int32Values: [],int64Values: [],bytes: [],string:
Property:0x17600309,status: 0,timestamp:1,zone:0x2,floatValues: [35.8],int32Values: [],int64Values: [],bytes: [],string:
Property:0x17600309,status: 0,timestamp:1,zone:0x4,floatValues: [34.8],int32Values: [],int64Values: [],bytes: [],string:
Property:0x17600309,status: 0,timestamp:1,zone:0x8,floatValues: [34.2],int32Values: [],int64Values: [],bytes: [],string:
Property 0x21608057 not supported by HAL"""
    car = vehicle.build(vehicle.parse_values(out))
    assert car["soc"] == 19.0 and car["range_km"] == 98.0 and car["temp_c"] == 39.0
    assert car["speed_kmh"] == 36.0 and car["gear"] == "P" and car["odometer"] == 28149.0
    assert car["plugged"] is True and car["charge_kw"] == 7.2
    assert car["tires"] == {"fl": 35.600002, "fr": 35.8, "rl": 34.8, "rr": 34.2}
    empty = vehicle.build({})
    assert all(value is None for value in empty.values())


def test_position_in_milliarcseconds_and_compass():
    from ex5viewer import vehicle
    line = "posnFromSatlt{ posnLat:47146964.0, posnLgt:363425760.0, posnAlti:5.0, posnSpd:0.0, posnDir:370.0"
    position = vehicle.parse_position(line)
    assert round(position["lat"], 3) == 13.096 and round(position["lon"], 3) == 100.952 and position["heading"] == 10
    assert vehicle.parse_position("posnFromSatlt{ posnLat:0.0, posnLgt:0.0, posnAlti:0.0, posnSpd:0.0, posnDir:0.0") is None
    assert [vehicle.compass(d) for d in (0, 44, 46, 180, 350)] == ["N", "NE", "NE", "S", "N"]


def test_vehicle_values_android13_format():
    from ex5viewer import vehicle
    out = ("Property:0x17600309, status: 0, timestamp: 4413847669, zone: 0x1, floatValues: [200.0], int32Values: [], "
           "int64Values: [], bytes: [], string: \n"
           "Property:0x11400400, status: 0, timestamp: 4413883103, zone: 0x0, floatValues: [], int32Values: [8], "
           "int64Values: [], bytes: [], string: \n")
    car = vehicle.build(vehicle.parse_values(out))
    assert car["gear"] == "D" and car["tires"]["fl"] == 200.0


def test_vehicle_fallbacks_aosp_units():
    from ex5viewer import vehicle
    values = {("11600308", 0): 50000.0, ("11600309", 0): 24500.0, ("11600106", 0): 49000.0}
    car = vehicle.build(values)
    assert car["range_km"] == 50.0 and car["soc"] == 50.0


def fake_tcam_parcel(strings):
    """Hex dump in `service call` format for status 0, non-null, then String16s (made-up values)."""
    raw = (0).to_bytes(4, "little") + (1).to_bytes(4, "little")
    for text in strings:
        data = text.encode("utf-16-le") + b"\x00\x00"
        raw += len(text).to_bytes(4, "little") + data + b"\x00" * (-len(data) % 4)
    raw += b"\x00" * 16
    words = [int.from_bytes(raw[i:i + 4], "little") for i in range(0, len(raw), 4)]
    lines = [f"  0x{i * 4:08x}: " + " ".join(f"{w:08x}" for w in words[i:i + 4]) + " '....'" for i in range(0, len(words), 4)]
    return "Result: Parcel(\n" + "\n".join(lines) + ")"


def test_tcam_info_parcel_and_carrier():
    values = ["1111111111/A", "2222222222/A", "2222222222/A", "3333333333/A", "4444444444/A", "5555555555/B",
              "6666666666/A", "520049999999999", "8966049999999999999F", "0000000000000000000\x04",
              "359999999999999", "GO4G8966049999999999999F"]
    info = stats.parse_tcam_info(fake_tcam_parcel(values))
    assert info["iccid"] == "8966049999999999999" and info["imsi"] == "520049999999999"
    assert info["hw"] == "2222222222/A" and info["swlx"] == "5555555555/B" and info["msisdn"] is None
    assert info["tcam_id"].startswith("GO4G")
    assert stats.carrier(info["imsi"]) == "TrueMove H"
    assert stats.carrier("460001234567890") == "China Mobile" and stats.carrier("999991234") == "MCC 999 / 99"
    assert stats.parse_tcam_info("Result: Parcel(00000000 ffffffb4 'error')") is None
    assert stats.parse_tcam_info("") is None


def test_scale_setting_bounds(tmp_path):
    s = Settings(tmp_path / "s.json")
    for bad in (0.5, 3.5, 1, "1.2"):
        s.set("scale", bad)
        assert s["scale"] == 0.0
    s.set("scale", 1.6)
    assert Settings(tmp_path / "s.json")["scale"] == 1.6


def test_motion_helpers():
    from ex5viewer import carpanel, widgets
    assert widgets.ease_out(0) == 0 and widgets.ease_out(1) == 1 and widgets.ease_out(0.5) > 0.5
    assert widgets.blend("#000000", "#ffffff", 0.5) == "#808080"
    start = {"soc": 20.0, "speed_kmh": None, "gear": "P", "tires": {"fl": 30.0, "fr": None}}
    end = {"soc": 40.0, "speed_kmh": 50.0, "gear": "D", "tires": {"fl": 34.0, "fr": 35.0}}
    mid = carpanel.interpolate(start, end, 0.5)
    assert mid["soc"] == 30.0 and mid["speed_kmh"] == 50.0 and mid["gear"] == "D"
    assert mid["tires"] == {"fl": 32.0, "fr": 35.0}
    assert carpanel.interpolate(start, end, 1.0)["soc"] == 40.0


@pytest.mark.parametrize("output, succeeds", [("Success\n", True), ("Failure [INSTALL_FAILED_INVALID_APK]", False)])
def test_install_apk_uses_selected_device(monkeypatch, output, succeeds):
    from types import SimpleNamespace

    def run(*args, timeout):
        assert args == ("-s", "vehicle", "install", "-r", "/tmp/demo app.apk")
        assert timeout == 180
        return SimpleNamespace(stdout=output, stderr="", returncode=0)

    monkeypatch.setattr(adb, "run", run)
    if succeeds:
        assert adb.install_apk("vehicle", "/tmp/demo app.apk") == "Success"
    else:
        with pytest.raises(RuntimeError, match="INSTALL_FAILED_INVALID_APK"):
            adb.install_apk("vehicle", "/tmp/demo app.apk")


@pytest.mark.parametrize("original", ["0", "1", "null"])
def test_temporary_adb_verifier_restores_after_install_failure(monkeypatch, original):
    from types import SimpleNamespace
    from ex5viewer import adb

    value = original
    changes = []

    def run(*args, **kwargs):
        nonlocal value
        assert args[:4] == ("-s", "head-unit", "shell", "settings")
        operation, namespace, key, *values = args[4:]
        assert (namespace, key) == ("global", "verifier_verify_adb_installs")
        if operation != "get":
            value = values[0] if operation == "put" else "null"
            changes.append(value)
        return SimpleNamespace(stdout=value + "\n")

    monkeypatch.setattr(adb, "run", run)
    with pytest.raises(RuntimeError, match="install failed"):
        with adb.temporary_adb_verifier_override("head-unit"):
            assert value == "0"
            raise RuntimeError("install failed")
    assert value == original
    assert changes == ([] if original == "0" else ["0", original])


# ---------- stability (audit F1, F2, F5, F6) ----------
def jpeg(color, size=(16, 8)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return buffer.getvalue()


class FakeJpegCluster(FakeCluster):
    """Cluster with ffmpeg: small JPEGs 0.3 s apart, and the channel stays open like a live capture loop."""

    def check_channel_exec_request(self, channel, command):
        command = command.decode()
        self.commands.append(command)

        def answer():
            time.sleep(0.2)
            if "get surfaces" in command:
                channel.sendall(b"- Surface 4711 (0x1267)\n")
            elif command.startswith("command -v"):
                channel.sendall(b"/usr/bin/ffmpeg\n")
            else:
                for color in ("red", "green", "blue"):
                    channel.sendall(jpeg(color))
                    time.sleep(0.3)
                time.sleep(30)  # still capturing: no EOF to flush a short read
            channel.send_exit_status(0)
            channel.close()

        threading.Thread(target=answer, daemon=True).start()
        return True


def test_cluster_jpeg_frames_arrive_without_waiting_for_64k():
    """F1: the JPEG reader must not block until 64 KiB arrive (3 frames of ~700 B never fill it)."""
    server, relay = fake_cluster_server(FakeJpegCluster())
    arrived, done = [], threading.Event()

    def on_frame(name, image):
        arrived.append((time.monotonic(), image))
        if len(arrived) == 3:
            done.set()

    stream = cluster.ClusterStream("serial", 1.0, lambda: (16, 8), on_frame, lambda n, s: None, stats.Meter(),
                                   reconnect=False, proxy_args=relay)
    stream.start()
    try:
        assert done.wait(15), f"frames={len(arrived)} commands={server.commands}"
        assert arrived[2][0] - arrived[0][0] < 2.0
        assert arrived[0][1].getpixel((0, 0))[0] > 200 and arrived[2][1].getpixel((0, 0))[2] > 200
    finally:
        stream.stop()
        stream.join(10)
    assert not stream.is_alive()


def test_video_stream_stop_does_not_block_and_thread_cleans_up(tmp_path, monkeypatch):
    """F2: stop() runs on the Tk thread: no wait, no adb. The stream thread kills/reaps and removes the forward."""
    # Stub adb.run (no shell script, no real adb): runs on Windows, macOS and Linux alike.
    callers = []

    def run(*args, **kwargs):
        callers.append((threading.current_thread().name, args))
        if "--remove" in args:
            time.sleep(1)  # a slow adb server: must only ever delay the stream thread
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(adb, "run", run)
    stream = scrcpy.VideoStream("main", "serial", 0, lambda: (8, 8), lambda *a: None, lambda *a: None,
                                stats.Meter(), reconnect=False)
    ready = threading.Event()
    server = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])

    def session():
        stream._forward = 4321
        stream._procs.append(server)
        a, b = socket.socketpair()
        a.settimeout(1)
        stream._socks.append(a)
        ready.set()
        scrcpy.recv_exact(a, 1, stream.stop_event)

    stream._session = session
    stream.start()
    assert ready.wait(5)
    started = time.monotonic()
    stream.stop()
    assert time.monotonic() - started < 0.2
    assert callers == []  # no adb from the caller's thread
    stream.join(10)
    assert not stream.is_alive()
    assert server.poll() is not None  # killed and reaped
    assert [(name, args[2:]) for name, args in callers] == [("video-main", ("forward", "--remove", "tcp:4321"))]


def test_pipe_socket_close_does_not_wait(monkeypatch):
    """F2: ClusterStream.stop() closes the PipeSocket on the Tk thread; the wait belongs to reap()."""
    sock = cluster.PipeSocket([sys.executable, "-c", "import time; time.sleep(30)"])
    real_wait = sock.proc.wait
    monkeypatch.setattr(sock.proc, "wait", lambda timeout=None: (time.sleep(2), real_wait(timeout))[1])
    started = time.monotonic()
    sock.close()
    assert time.monotonic() - started < 0.2 and sock._closed
    sock.reap()
    assert sock.proc.poll() is not None


@pytest.mark.parametrize("stop_during", ["push", "forward"])
def test_video_stream_stopped_during_setup_starts_no_server(monkeypatch, stop_during):
    """F5: a stop that lands while push/forward runs must not go on to start a server for a dead session."""
    calls = []
    stream = scrcpy.VideoStream("main", "serial", 0, lambda: (8, 8), lambda *a: None, lambda *a: None,
                                stats.Meter(), reconnect=False)

    def run(*args, **kwargs):
        calls.append(args)
        if stop_during in args and "--remove" not in args:
            stream.stop()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    started = []

    def popen(*args, **kwargs):  # run() swallows exceptions: record, then fail the session
        started.append(args)
        raise OSError("no server in tests")

    monkeypatch.setattr(adb, "run", run)
    monkeypatch.setattr(adb, "popen", popen)
    monkeypatch.setattr(scrcpy.paths, "find_server", lambda: "scrcpy-server")
    stream.start()
    stream.join(5)
    assert not stream.is_alive()
    assert started == []
    verbs = [args[2] for args in calls]
    if stop_during == "push":
        assert verbs == ["push"]
    else:  # the forward it made is removed again
        assert verbs == ["push", "forward", "forward"] and "--remove" in calls[-1]


def test_touch_never_blocks_and_keeps_down_up(monkeypatch):
    """F6: touch() only queues; a sender thread does the sendall. Full queue drops MOVE, never DOWN/UP."""
    a, b = socket.socketpair()
    a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    a.setblocking(False)
    for _ in range(4096):  # b never reads: fill the send buffer so the sender is stuck from the start
        try:
            a.send(b"\0" * 4096)
        except BlockingIOError:
            break
    a.settimeout(1.0)  # what VideoStream._open sets
    stream = scrcpy.VideoStream("main", "serial", 0, lambda: (8, 8), lambda *a: None, lambda *a: None,
                                stats.Meter(), control=True)
    stream._control_sock, stream.video_size = a, (1080, 1920)
    stream._start_sender(a)
    started = time.monotonic()
    stream.touch(scrcpy.TOUCH_DOWN, 0.5, 0.5)
    for i in range(98):
        stream.touch(scrcpy.TOUCH_MOVE, i / 100, 0.5)
    stream.touch(scrcpy.TOUCH_UP, 0.9, 0.5)
    assert time.monotonic() - started < 0.05
    pending = [message[1] for message in list(stream._touches.queue)]
    assert pending[-1] == scrcpy.TOUCH_UP
    assert pending.count(scrcpy.TOUCH_MOVE) <= scrcpy.TOUCH_QUEUE
    stream.stop()
    a.close(), b.close()

    # healthy link: everything goes out, in order
    a, b = socket.socketpair()
    b.settimeout(2)
    stream = scrcpy.VideoStream("main", "serial", 0, lambda: (8, 8), lambda *a: None, lambda *a: None,
                                stats.Meter(), control=True)
    stream._control_sock, stream.video_size = a, (1080, 1920)
    stream._start_sender(a)
    for action in (scrcpy.TOUCH_DOWN, scrcpy.TOUCH_MOVE, scrcpy.TOUCH_UP):
        stream.touch(action, 0.5, 0.5)
    got = scrcpy.recv_exact(b, 96, threading.Event())
    assert [got[i * 32 + 1] for i in range(3)] == [scrcpy.TOUCH_DOWN, scrcpy.TOUCH_MOVE, scrcpy.TOUCH_UP]
    stream.stop()
    a.close(), b.close()


# ---------- Cluster relay: firmware 1.3 (no su) first, the su relay as the fallback ----------
def test_cluster_relay_is_unprivileged_first_with_su_fallback():
    stream = cluster.ClusterStream("serial", 1.0, lambda: (96, 26), None, None, stats.Meter())
    assert "su" not in stream.proxy_args and stream.proxy_args[-2:] == [cluster.CLUSTER_IP, "22"]
    assert stream.proxy_args[1:5] == ["-s", "serial", "shell", "-T"]
    at = stream.legacy_proxy_args.index("su")
    assert stream.legacy_proxy_args[at:at + 2] == ["su", "0"]
    assert [arg for arg in stream.legacy_proxy_args if arg not in ("su", "0")] == stream.proxy_args
    custom = cluster.ClusterStream("serial", 1.0, lambda: (96, 26), None, None, stats.Meter(), proxy_args=["relay"])
    assert custom.proxy_args == ["relay"] and custom.legacy_proxy_args is None  # an explicit relay has no fallback


def test_cluster_falls_back_to_the_legacy_relay_and_still_stops_fast():
    """The first relay dies during the SSH handshake (what a head unit without that path does): the stream
    retries once through the legacy relay, shows frames, and stop() still returns at once (F2)."""
    server, relay = fake_cluster_server()
    frames, states = [], []
    done = threading.Event()

    def on_frame(name, image):
        frames.append(image)
        if len(frames) == 3:
            done.set()

    stream = cluster.ClusterStream("serial", 1.0, lambda: (96, 26), on_frame, lambda n, s: states.append(s),
                                   stats.Meter(), reconnect=False)
    stream.proxy_args = [sys.executable, "-c", "pass"]  # exits at once: no SSH banner
    stream.legacy_proxy_args = relay
    stream.start()
    assert done.wait(30), f"frames={len(frames)} states={states}"
    started = time.monotonic()
    stream.stop()
    assert time.monotonic() - started < 1.0
    stream.join(10)
    assert not stream.is_alive()
    assert states[:2] == ["connecting", "live"] and "dump surface 4711" in server.commands[2]


# ---------- GPU-freeze mitigations: reconnect backoff, software decode ----------
def test_retry_delay_backs_off_and_caps():
    assert [adb.retry_delay(n) for n in range(1, 7)] == [4, 8, 16, 30, 30, 30]
    assert adb.retry_delay(0) == 4


def test_backoff_spaces_out_attempts():
    now = [100.0]
    backoff = adb.Backoff(clock=lambda: now[0])
    assert backoff.due()
    backoff.failed()
    assert not backoff.due()
    now[0] += 4
    assert backoff.due()
    backoff.failed()
    now[0] += 7.9
    assert not backoff.due()
    now[0] += 0.2
    assert backoff.due()
    backoff.reset()
    assert backoff.due() and backoff.failures == 0


def _record_waits(stream, monkeypatch, sessions):
    """Run a stream thread's loop in this thread with failing sessions; return the waits between them."""
    waits = []
    results = iter(sessions)

    def session():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    def wait(seconds):
        waits.append(seconds)
        if len(waits) >= len(sessions):
            stream.stop_event.set()
        return stream.stop_event.is_set()

    monkeypatch.setattr(stream, "_session", session)
    monkeypatch.setattr(stream.stop_event, "wait", wait)
    stream.run()
    return waits


def test_video_stream_backs_off_on_repeated_failures(monkeypatch):
    stream = scrcpy.VideoStream("main", "serial", 0, lambda: (64, 40), lambda *a: None, lambda *a: None,
                                stats.Meter())
    monkeypatch.setattr(stream, "_cleanup", lambda: None)
    fail = OSError("device not found")
    waits = _record_waits(stream, monkeypatch, [fail, fail, fail, fail, fail, True, fail])
    assert waits == [4, 8, 16, 30, 30, 1, 4]  # a live session resets the backoff


def test_cluster_stream_backs_off_on_repeated_failures(monkeypatch):
    stream = cluster.ClusterStream("serial", 3, lambda: (64, 18), lambda *a: None, lambda *a: None, None)
    fail = OSError("Error reading SSH protocol banner")
    waits = _record_waits(stream, monkeypatch, [fail, fail, fail, fail, True, fail])
    assert waits == [4, 8, 16, 30, 2, 4]


def test_stats_reconnect_is_backed_off(monkeypatch):
    from ex5viewer import ui
    calls = []
    monkeypatch.setattr(adb, "connect", lambda address: calls.append(address) or (False, "refused"))
    now = [0.0]
    backoff = adb.Backoff(clock=lambda: now[0])
    fake = type("FakeApp", (), {"s": {"auto_reconnect": True}})()
    for _tick in range(30):  # 60 s of 2 s stats ticks with the car gone
        ui.App.reconnect_car(fake, 5, "192.0.2.25:5566", backoff)
        now[0] += 2
    # attempts at 0, 4, 12, 28, 58 s: five, not thirty
    assert len(calls) == 5
    ui.App.reconnect_car(fake, 1, "192.0.2.25:5566", adb.Backoff())  # one missed sample: no reconnect yet
    assert len(calls) == 5


def test_decoder_is_software_only():
    from ex5viewer import decoder
    assert decoder.HWACCEL is None
    dec = decoder.Decoder()
    assert not getattr(dec.ctx, "is_hwaccel", False)
    assert dec.ctx.codec.name == "h264"
