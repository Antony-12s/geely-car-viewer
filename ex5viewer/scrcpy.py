"""Talk to scrcpy-server directly: one video stream per Android display, optional touch control.

Protocol (scrcpy 5.0.1, doc/develop.md): forward tunnel, first socket gets a dummy byte and
64 bytes of device name, then codec id (u32), then 12-byte headers: session packets (MSB set,
width/height) or media packets (config/key flags + PTS, u32 size, payload).
"""
import logging
import queue
import random
import socket
import struct
import subprocess
import threading
import time
from collections import deque

from . import adb, paths
from .decoder import Decoder

log = logging.getLogger(__name__)

SERVER_VERSION = "5.0.1"  # must equal the bundled scrcpy-server, the server refuses any other
H264 = 0x68323634
TOUCH_DOWN, TOUCH_UP, TOUCH_MOVE = 0, 1, 2
POINTER_FINGER = 0xFFFFFFFFFFFFFFFE  # scrcpy's generic finger id (-2): a touch, not a mouse
TOUCH_QUEUE = 32  # pending touch messages before MOVE events are dropped (DOWN/UP never are)


class StreamError(Exception):
    pass


def recv_exact(sock, size, stop):
    data = bytearray()
    while len(data) < size:
        try:
            chunk = sock.recv(size - len(data))
        except socket.timeout:
            if stop.is_set():
                raise StreamError("stopped")
            continue
        if not chunk:
            raise StreamError("stream closed")
        data += chunk
    return bytes(data)


def parse_header(header):
    """12-byte header -> ('session', width, height) or ('media', is_config, size)."""
    if header[0] & 0x80:
        width, height = struct.unpack(">II", header[4:12])
        return "session", width, height
    flags_pts, size = struct.unpack(">QI", header)
    return "media", bool(flags_pts & (1 << 62)), size


def touch_message(action, x, y, width, height):
    """INJECT_TOUCH_EVENT, 32 bytes (scrcpy app/tests/test_control_msg_serialize.c)."""
    pressure = 0 if action == TOUCH_UP else 0xFFFF
    return struct.pack(">BBQiiHHHII", 2, action, POINTER_FINGER, int(x), int(y), width, height, pressure, 0, 0)


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class VideoStream(threading.Thread):
    """Keeps one display streaming until stop(); reconnects by itself when the stream drops.

    callbacks: on_frame(name, PIL image), on_state(name, state) with state in
    connecting / live / reconnecting / error. meter.add(down=n) counts received bytes.
    """

    def __init__(self, name, serial, display_id, size_fn, on_frame, on_state, meter,
                 control=False, max_fps=30, rotate_fn=lambda: False, reconnect=True):
        super().__init__(daemon=True, name=f"video-{name}")
        self.name_, self.serial, self.display_id = name, serial, display_id
        self.size_fn, self.on_frame, self.on_state, self.meter = size_fn, on_frame, on_state, meter
        self.control, self.max_fps, self.rotate_fn, self.reconnect = control, max_fps, rotate_fn, reconnect
        self.stop_event = threading.Event()
        self.video_size = None          # device frame size, needed for touch coordinates
        self._control_sock = None
        self._touches = queue.Queue()   # touch messages for the sender thread; the Tk thread never sends
        self._procs, self._socks, self._forward = [], [], None
        self._lock = threading.Lock()  # guards _cleanup (run by the stream thread; stop() only kills)
        self._server_log = deque(maxlen=20)

    # ---- public ----
    def stop(self):
        """Called on the Tk thread: never waits and runs no adb. Closing the sockets and killing the server
        wakes the stream thread, whose run() then reaps the processes and removes the forward."""
        self.stop_event.set()
        self._control_sock = None
        for sock in list(self._socks):
            try:
                sock.close()
            except OSError:
                pass
        for proc in list(self._procs):
            if proc.poll() is None:
                proc.kill()

    def touch(self, action, fx, fy):
        """fx, fy in 0..1 of the picture; dropped when control is off or not connected yet.
        Only queues the message: a congested link must not block the caller (the Tk thread)."""
        sock, size = self._control_sock, self.video_size
        if not sock or not size:
            return
        if action == TOUCH_MOVE and self._touches.qsize() >= TOUCH_QUEUE:
            return  # link is behind: drop drag steps, never a press or a release
        x = min(max(fx, 0.0), 1.0) * (size[0] - 1)
        y = min(max(fy, 0.0), 1.0) * (size[1] - 1)
        self._touches.put(touch_message(action, x, y, *size))

    # ---- thread ----
    def run(self):
        delay = 1
        while not self.stop_event.is_set():
            got_frame = False
            try:
                self.on_state(self.name_, "connecting")
                got_frame = self._session()
            except Exception as error:  # any failure ends this session; the loop decides about retrying
                log.info("%s stream ended: %s", self.name_, error)
            finally:
                self._cleanup()
            if self.stop_event.is_set():
                return
            if not self.reconnect:
                self.on_state(self.name_, "error")
                return
            self.on_state(self.name_, "reconnecting")
            delay = 1 if got_frame else min(delay * 2, 8)
            self.stop_event.wait(delay)

    def _session(self):
        scid = random.randrange(1, 0x7FFFFFFF)
        remote_jar = f"/data/local/tmp/ex5viewer-{scid:08x}.jar"  # own file: the server deletes its jar on start
        adb.run("-s", self.serial, "push", paths.find_server(), remote_jar, timeout=60, check=True)
        if self.stop_event.is_set():  # stopped while the push ran: start nothing against the next session
            raise StreamError("stopped")
        port = free_port()
        adb.run("-s", self.serial, "forward", f"tcp:{port}", f"localabstract:scrcpy_{scid:08x}", check=True)
        self._forward = port
        if self.stop_event.is_set():
            raise StreamError("stopped")
        args = [f"scid={scid:08x}", "log_level=warn", "audio=false", f"control={str(self.control).lower()}",
                f"display_id={self.display_id}", f"max_fps={self.max_fps}", "tunnel_forward=true",
                "clipboard_autosync=false", "video_codec=h264"]
        server = adb.popen("-s", self.serial, "shell", f"CLASSPATH={remote_jar}", "app_process", "/",
                           "com.genymobile.scrcpy.Server", SERVER_VERSION, *args,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self._procs.append(server)
        threading.Thread(target=self._collect_log, args=(server,), daemon=True).start()
        video = self._connect_first(port, server)
        if self.control:  # the server sends the device name only after every socket is accepted
            self._control_sock = self._open(port)
            threading.Thread(target=self._drain, args=(self._control_sock,), daemon=True).start()
            self._start_sender(self._control_sock)
        recv_exact(video, 64, self.stop_event)  # device name, unused
        return self._read_video(video)

    def _open(self, port):
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        sock.settimeout(1.0)
        self._socks.append(sock)
        return sock

    def _connect_first(self, port, server):
        """adb accepts the TCP connect even before the server listens; the dummy byte proves it is up."""
        deadline = time.time() + 15
        while time.time() < deadline and not self.stop_event.is_set():
            if server.poll() is not None:
                raise StreamError("server exited: " + " | ".join(self._server_log))
            sock = self._open(port)
            try:
                if sock.recv(1):
                    return sock
            except (socket.timeout, OSError):
                pass
            sock.close()
            self._socks.remove(sock)
            time.sleep(0.15)
        raise StreamError("server did not start")

    def _read_video(self, sock):
        stop = self.stop_event
        codec = struct.unpack(">I", recv_exact(sock, 4, stop))[0]
        if codec != H264:
            raise StreamError(f"unexpected codec {codec:#x}")
        self.meter.add(down=4)
        decoder, config, got_frame = Decoder(), b"", False
        while not stop.is_set():
            header = recv_exact(sock, 12, stop)
            kind, a, b = parse_header(header)
            if kind == "session":
                self.video_size = (a, b)
                self.meter.add(down=12)
                continue
            payload = recv_exact(sock, b, stop)
            self.meter.add(down=12 + b)
            if a:  # SPS/PPS: decoder needs it glued to the next frame
                config = payload
                continue
            if config:
                payload, config = config + payload, b""
            for frame in decoder.decode(payload):
                width, height = self.size_fn()
                self.on_frame(self.name_, Decoder.to_image(frame, width, height, self.rotate_fn(),
                                                          preserve_aspect=self.name_ == "hud"))
                if not got_frame:
                    got_frame = True
                    self.on_state(self.name_, "live")
        return got_frame

    def _collect_log(self, server):
        for line in server.stderr:
            self._server_log.append(line.decode(errors="replace").strip())

    def _start_sender(self, sock):
        while True:  # events queued for an earlier session carry its sizes: drop them
            try:
                self._touches.get_nowait()
            except queue.Empty:
                break
        threading.Thread(target=self._send_touches, args=(sock,), daemon=True, name=f"touch-{self.name_}").start()

    def _send_touches(self, sock):
        """Sender thread: one per control socket, ends when the socket is replaced or the stream stops."""
        while self._control_sock is sock and not self.stop_event.is_set():
            try:
                message = self._touches.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                sock.sendall(message)
                self.meter.add(up=len(message))
            except OSError:
                pass

    @staticmethod
    def _drain(sock):
        try:
            while sock.recv(4096):  # device messages (clipboard etc.) are not used
                pass
        except OSError:
            pass

    def _cleanup(self):
        with self._lock:
            self._cleanup_locked()

    def _cleanup_locked(self):
        self._control_sock = None
        for sock in self._socks:
            try:
                sock.close()
            except OSError:
                pass
        self._socks = []
        for proc in self._procs:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        self._procs = []
        if self._forward:
            port, self._forward = self._forward, None
            try:
                adb.run("-s", self.serial, "forward", "--remove", f"tcp:{port}", timeout=5)
            except Exception:
                pass
