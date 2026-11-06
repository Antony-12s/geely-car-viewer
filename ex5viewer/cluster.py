"""EX5 instrument cluster: a separate Linux (Weston/IVI) box behind the head unit.

Path: adb root shell -> toybox nc to 198.18.44.2:22 -> dropbear ssh (root, empty password)
-> `LayerManagerControl dump surface` in a remote loop -> BMP frames on the channel.
Paramiko runs over the adb pipe through PipeSocket, so no ssh binary is needed on Windows.
"""
import io
import logging
import socket
import subprocess
import threading

import paramiko
from PIL import Image

from . import adb

log = logging.getLogger(__name__)

CLUSTER_IP = "198.18.44.2"
ENV = "export XDG_RUNTIME_DIR=/etc/weston/weston_xdg_runtime_dir WAYLAND_DISPLAY=wayland-1;"


class PipeSocket:
    """Socket-like object over a child's stdin/stdout.

    paramiko.ProxyCommand select()s on pipes, which Windows does not support; a reader thread does.
    """

    def __init__(self, args, meter=None):
        self.meter = meter
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     **adb.NO_WINDOW)
        self.buffer = bytearray()
        self.cond = threading.Condition()
        self.closed = False
        self.timeout = None
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            while chunk := self.proc.stdout.read1(65536):
                if self.meter:
                    self.meter.add(down=len(chunk))
                with self.cond:
                    self.buffer += chunk
                    self.cond.notify_all()
        except (OSError, ValueError):
            pass
        with self.cond:
            self.closed = True
            self.cond.notify_all()

    def recv(self, size):
        with self.cond:
            if not self.cond.wait_for(lambda: self.buffer or self.closed, self.timeout):
                raise socket.timeout()
            data = bytes(self.buffer[:size])
            del self.buffer[:size]
            return data  # b"" once closed and drained = EOF

    def send(self, data):
        if self.closed:
            raise OSError("pipe closed")
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except (OSError, ValueError) as error:
            raise OSError(str(error)) from error
        if self.meter:
            self.meter.add(up=len(data))
        return len(data)

    def sendall(self, data):
        self.send(data)

    @property
    def _closed(self):  # paramiko's Transport.close() reads the private flag of real sockets
        return self.closed

    def settimeout(self, timeout):
        self.timeout = timeout

    def gettimeout(self):
        return self.timeout

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        with self.cond:
            self.closed = True
            self.cond.notify_all()


def open_transport(sock):
    """SSH handshake + root login with no password (what the cluster's dropbear accepts)."""
    transport = paramiko.Transport(sock)
    transport.start_client(timeout=15)  # host key changes with every cluster boot: not checked
    try:
        transport.auth_none("root")
    except paramiko.BadAuthenticationType:
        transport.auth_password("root", "")
    if not transport.is_authenticated():
        transport.close()
        raise paramiko.AuthenticationException("cluster refused root login")
    return transport


def run(transport, command, timeout=20):
    channel = transport.open_session(timeout=timeout)
    channel.settimeout(timeout)
    channel.exec_command(command)
    out = channel.makefile("rb").read()
    channel.close()
    return out.decode(errors="replace")


def read_bmp(stream):
    """One BMP from a byte stream; its size is in header bytes 2..6. None on EOF/garbage."""
    head = stream.read(6)
    if len(head) < 6 or head[:2] != b"BM":
        return None
    size = int.from_bytes(head[2:6], "little")
    if not 54 <= size <= 64 * 1024 * 1024:
        return None
    body = stream.read(size - 6)
    return head + body if len(body) == size - 6 else None


class JpegReader:
    """Split ffmpeg's MJPEG byte stream into JPEG files (ends at FFD9; ffmpeg adds no thumbnails)."""

    def __init__(self, stream):
        self.stream, self.buffer = stream, b""

    def read(self):
        while True:
            end = self.buffer.find(b"\xff\xd9")
            if end >= 0:
                frame, self.buffer = self.buffer[:end + 2], self.buffer[end + 2:]
                return frame if frame[:2] == b"\xff\xd8" else None
            chunk = self.stream.read1(65536) if hasattr(self.stream, "read1") else self.stream.read(65536)
            if not chunk or len(self.buffer) > 8 * 1024 * 1024:
                return None
            self.buffer += chunk


FFMPEG_INPUT = "-f image2pipe -c:v bmp"
JPEG_WIDTH = 960  # 2x the cluster view of the medium window. 22 KB/frame instead of a 4 MB BMP


def capture_script(surface, interval, jpeg):
    """Shell loop run on the cluster. Everything is niced: the driver's gauges come first.

    Raw mode: `cat` into the closed channel fails and ends the loop. JPEG mode: ffmpeg sits in
    between, so a watcher waits for stdin EOF (channel closed) and kills ffmpeg; the loop then
    dies on its next write. Without it the loop kept running on the cluster after we left.
    """
    dump = f"nice -n 19 LayerManagerControl dump surface {surface} to $f >/dev/null 2>&1"
    # the sleep runs alongside the dump: one frame every `interval` s, or as fast as the dump goes
    loop = f"while :; do sleep {interval} & {dump} && cat $f || {{ rm -f $f; exit; }}; wait; done"
    # own file per session (two viewers must not delete each other's); first drop files whose
    # session is gone: an in-flight dump can rewrite the file after the old session's rm (4 MB each)
    stale = 'for g in /tmp/ex5c*.bmp; do p=${g#/tmp/ex5c-}; [ -d "/proc/${p%.bmp}" ] || rm -f "$g"; done;'
    setup = f"{ENV} {stale} f=/tmp/ex5c-$$.bmp;"
    if not jpeg:
        return f"{setup} {loop}"
    ffmpeg = (f"nice -n 19 ffmpeg -v error -threads 1 {FFMPEG_INPUT} -i - -vf scale={JPEG_WIDTH}:-2"
              " -q:v 4 -flush_packets 1 -f image2pipe -c:v mjpeg -")
    return f"{setup} ( {loop} ) | {ffmpeg} & cat >/dev/null; kill $! 2>/dev/null; sleep 2; rm -f $f"


def surface_ids(listing):
    return [line.split()[2] for line in listing.splitlines() if line.startswith("- Surface ")]


class ClusterStream(threading.Thread):
    """Grab the cluster picture every `interval` seconds until stop(); retries when the relay drops."""

    def __init__(self, serial, interval, size_fn, on_frame, on_state, meter, reconnect=True,
                 proxy_args=None):
        super().__init__(daemon=True, name="cluster")
        self.serial, self.interval, self.size_fn = serial, interval, size_fn
        self.on_frame, self.on_state, self.meter, self.reconnect = on_frame, on_state, meter, reconnect
        self.proxy_args = proxy_args or [adb.ADB, "-s", serial, "shell", "-T", "su", "0", "toybox", "nc", "-w", "3",
                                         "-q", "1", CLUSTER_IP, "22"]  # -q: killing adb leaves nc running otherwise
        self.stop_event = threading.Event()
        self._sock = self._transport = None

    def stop(self):
        self.stop_event.set()
        if self._transport:  # say goodbye first: dropbear then ends the session and its shell loop
            self._transport.close()
        if self._sock:
            self._sock.close()

    def run(self):
        delay = 2
        while not self.stop_event.is_set():
            got_frame = False
            try:
                self.on_state("cluster", "connecting")
                got_frame = self._session()
            except Exception as error:
                log.info("cluster ended: %s", error)
            finally:
                if self._sock:
                    self._sock.close()
            if self.stop_event.is_set():
                return
            if not self.reconnect:
                self.on_state("cluster", "error")
                return
            self.on_state("cluster", "reconnecting" if got_frame else "error")
            delay = 2 if got_frame else min(delay * 2, 16)
            self.stop_event.wait(delay)

    def _session(self):
        self._sock = PipeSocket(self.proxy_args, self.meter)
        transport = self._transport = open_transport(self._sock)
        ids = surface_ids(run(transport, ENV + " LayerManagerControl get surfaces"))
        if not ids:
            raise RuntimeError("no IVI surface on the cluster")
        jpeg = "/ffmpeg" in run(transport, "command -v ffmpeg")
        channel = transport.open_session(timeout=15)
        channel.settimeout(self.interval + 20)  # a stalled relay surfaces as a timeout, then a reconnect
        channel.exec_command(capture_script(ids[0], self.interval, jpeg))
        stream = channel.makefile("rb")
        next_frame = JpegReader(stream).read if jpeg else lambda: read_bmp(stream)
        got_frame = False
        while not self.stop_event.is_set():
            data = next_frame()
            if data is None:
                break
            image = Image.open(io.BytesIO(data)).convert("RGB").resize(self.size_fn(), Image.Resampling.BILINEAR)
            self.on_frame("cluster", image)
            if not got_frame:
                got_frame = True
                self.on_state("cluster", "live")
        transport.close()
        return got_frame
