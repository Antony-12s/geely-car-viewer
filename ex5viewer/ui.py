"""EX5 Viewer window: top bar (connection, network graph, PC/car meters, settings) + one bezel per screen."""
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

from PIL import Image, ImageTk

from . import __version__, adb, paths
from .cluster import ClusterStream
from .i18n import Translator
from .scrcpy import TOUCH_DOWN, TOUCH_MOVE, TOUCH_UP, VideoStream
from .stats import CarStats, History, HostStats, Meter, human_gb, tcp_ping
from .widgets import Dot, MiniMeter, Segmented, Switch, corner_masks, palette, round_rect

log = logging.getLogger(__name__)

BASE = {"main": (704, 440), "hud": (420, 252), "cluster": (420, 116)}
SCALE = {"small": 0.8, "medium": 1.0, "large": 1.25}
DISPLAYS = {"main": 0, "hud": 1}       # Android display ids on the EX5
CHIN, PAD, RADIUS = 48, 12, 22


def pick_font(candidates, fallback):
    families = set(tkfont.families())
    return next((name for name in candidates if name in families), fallback)


def open_path(path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - user asked to open their own log file
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)], **adb.NO_WINDOW)


class Screen:
    """One bezel: picture canvas + chin. Owns its state text and the last frame."""

    def __init__(self, app, parent, name, size):
        self.app, self.name, self.size = app, name, size
        pal, w, h = app.pal, *size
        self.canvas = tk.Canvas(parent, width=w + 2 * PAD, height=h + PAD + CHIN, bg=pal["bg"], highlightthickness=0)
        self.bezel = round_rect(self.canvas, 1, 1, w + 2 * PAD - 1, h + PAD + CHIN - 1, RADIUS,
                                fill=pal["bezel"], outline=pal["bezel_line"], width=1)
        self.photo = ImageTk.PhotoImage(Image.new("RGB", size, pal["bezel"]))
        self.canvas.create_image(PAD, PAD, image=self.photo, anchor="nw", tags="frame")
        corner_masks(self.canvas, PAD, PAD, w, h, 10, pal["bezel"], "mask")
        self.chin = tk.Frame(self.canvas, bg=pal["bezel"], width=w, height=CHIN)
        self.chin.pack_propagate(False)
        self.canvas.create_window(PAD, PAD + h, window=self.chin, anchor="nw", width=w, height=CHIN)
        self.has_frame, self.state, self.fps_count, self.last_frame_at = False, "idle", 0, None
        self.down_bytes = 0

    def chin_label(self, text, fg=None, font=None, side="left", padx=(0, 0)):
        label = tk.Label(self.chin, text=text, bg=self.app.pal["bezel"], fg=fg or self.app.pal["muted"],
                         font=font or self.app.f_small)
        label.pack(side=side, padx=padx)
        return label

    def show(self, image):
        if image.size != self.size:
            image = image.resize(self.size)
        self.photo.paste(image)
        if not self.has_frame:
            self.has_frame = True
            self.draw_message()

    def set_outline(self, colour, width):
        self.canvas.itemconfigure(self.bezel, outline=colour, width=width)

    def draw_message(self):
        canvas, (w, h), pal, t = self.canvas, self.size, self.app.pal, self.app.t
        canvas.delete("message")
        key = {"idle": "msg_idle", "connecting": "msg_connecting", "reconnecting": "msg_reconnecting",
               "error": "msg_error", "paused": "msg_paused"}.get(self.state)
        if not key or (self.state == "paused" and not self.has_frame):
            if self.state == "paused":
                key = "msg_paused"
            else:
                return
        if self.has_frame and self.state != "idle":
            colour = pal["warn"] if self.state in ("reconnecting", "paused") else pal["bad"] if self.state == "error" else pal["line"]
            canvas.create_rectangle(PAD, PAD + h - 32, PAD + w, PAD + h, fill=pal["panel"], outline="", tags="message")
            canvas.create_line(PAD, PAD + h - 32, PAD + w, PAD + h - 32, fill=colour, tags="message")
            canvas.create_text(PAD + 12, PAD + h - 16, text=t(key), fill=pal["text"], font=self.app.f_small,
                               anchor="w", tags="message")
        else:
            if self.state == "idle":
                self.photo.paste(Image.new("RGB", self.size, pal["bezel"]))
                self.has_frame = False
            canvas.create_text(PAD + w // 2, PAD + h // 2, text=t(key), fill=pal["muted"], font=self.app.f_body,
                               tags="message")
        canvas.tag_raise("mask")


class App:
    def __init__(self, root, settings, selftest=False):
        self.root, self.s, self.selftest = root, settings, selftest
        self.ui_tasks = queue.Queue()
        self.frames = {}                     # name -> newest PIL image (stream threads write)
        self.streams, self.meters = {}, {}
        self.history = History(settings["graph_seconds"])
        self.conn = "idle"                   # idle / connecting / connected
        self.generation = 0                  # bumps on every connect/cancel; stale workers check it
        self.serial = self.address = self.model = None
        self.detected_model = None
        self.usb_list, self.ping, self.car_ok = [], None, True
        self.host_stats, self.car_stats = HostStats(), None
        self.press = None
        self.screens = {}
        self.settings_panel = None
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.bind("<Escape>", lambda _e: self.close_settings())
        self.build()
        self.refresh()
        self.tick()
        threading.Thread(target=self.stats_loop, daemon=True).start()
        if settings["auto_connect"] and not selftest and self.can_auto_connect():
            self.root.after(300, self.connect)

    # ---------- build ----------
    def build(self):
        """Build the window. "auto" size: medium, or small when medium does not fit the screen."""
        reopen = self.settings_panel is not None
        chosen = self.s["size"]
        for self.size_name in ("medium", "small") if chosen == "auto" else (chosen,):
            self._build_widgets()
            if self.size_name == "small" or self.fits_screen():
                break
        if reopen:
            self.toggle_settings()

    def fits_screen(self):
        self.root.update_idletasks()
        # room for the title bar and a taskbar/dock
        return (self.root.winfo_reqwidth() <= self.root.winfo_screenwidth() - 16
                and self.root.winfo_reqheight() <= self.root.winfo_screenheight() - 90)

    def _build_widgets(self):
        for child in self.root.winfo_children():
            child.destroy()
        self.settings_panel = None
        self.t = Translator(self.s["language"])
        self.pal = pal = palette(self.s["theme"])
        thai = pick_font(["Noto Sans Thai", "Leelawadee UI", "Sukhumvit Set", "Thonburi", "Tahoma"], "TkDefaultFont")
        mono = pick_font(["Noto Sans Mono", "DejaVu Sans Mono", "Consolas", "Menlo", "Courier New"], "TkFixedFont")
        self.f_body, self.f_bold = (thai, 10), (thai, 10, "bold")
        self.f_small, self.f_tiny = (thai, 9), (thai, 8)
        self.f_title = (thai, 11, "bold")
        self.f_num, self.f_num_small = (mono, 9), (mono, 8)
        self.root.configure(bg=pal["bg"])
        self.root.option_add("*Font", self.f_body)
        self.root.title("EX5 Viewer")
        icon = paths.resource_dir() / "icon.png"
        if icon.is_file():
            self._icon = tk.PhotoImage(file=str(icon))
            self.root.iconphoto(True, self._icon)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", bool(self.s["topmost"]))
        self.build_topbar()
        self.build_screens()
        self.update_conn_ui()

    def layout_model(self):
        if self.s["model"] != "auto":
            return self.s["model"]
        return self.detected_model or "EX5"

    def sizes(self):
        k = SCALE[self.size_name]
        return {name: (int(w * k) // 2 * 2, int(h * k) // 2 * 2) for name, (w, h) in BASE.items()}

    def build_topbar(self):
        pal, t = self.pal, self.t
        bar = tk.Frame(self.root, bg=pal["panel"], height=96, padx=20)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Frame(self.root, bg=pal["line"], height=1).pack(fill="x")
        inner = tk.Frame(bar, bg=pal["panel"])
        inner.pack(fill="both", expand=True, pady=12)

        # connection block
        conn = tk.Frame(inner, bg=pal["panel"])
        conn.pack(side="left", fill="y")
        top = tk.Frame(conn, bg=pal["panel"])
        top.pack(fill="x")
        self.conn_dot = Dot(top, pal, pal["panel"])
        self.conn_dot.pack(side="left", padx=(0, 8))
        self.conn_label = tk.Label(top, bg=pal["panel"], fg=pal["text"], font=self.f_title)
        self.conn_label.pack(side="left")
        self.model_chip = tk.Label(top, bg="#10202b", fg=pal["accent"], font=self.f_tiny, padx=7, cursor="hand2",
                                   highlightthickness=1, highlightbackground="#1d3a4f")
        self.model_chip.pack(side="left", padx=(8, 0))
        self.model_chip.bind("<Button-1>", self.model_menu)
        self.link_seg = Segmented(top, [("wifi", "Wi‑Fi"), ("usb", "USB")], self.s["link"], pal, self.set_link, self.f_tiny)
        self.link_seg.pack(side="left", padx=(6, 0))
        self.ping_label = tk.Label(top, bg=pal["panel"], fg=pal["muted"], font=self.f_small)
        self.ping_label.pack(side="left", padx=(10, 0))

        group = tk.Frame(conn, bg=pal["line"], padx=1, pady=1)
        group.pack(anchor="w", pady=(8, 0))
        self.ip_var = tk.StringVar(value=self.s["address"])
        self.ip_entry = tk.Entry(group, textvariable=self.ip_var, width=19, bg=pal["panel2"], fg=pal["text"],
                                 relief="flat", insertbackground=pal["accent"], font=self.f_num,
                                 disabledbackground=pal["panel2"], disabledforeground=pal["muted"],
                                 highlightthickness=0, selectbackground="#1d3a4f")
        self.ip_entry.bind("<Return>", lambda _e: self.on_conn_button())
        self.ip_var.trace_add("write", lambda *_: self.update_conn_ui())
        self.usb_pick = tk.Label(group, bg=pal["panel2"], fg=pal["text"], font=self.f_small, width=24, anchor="w",
                                 padx=6, cursor="hand2")
        self.usb_pick.bind("<Button-1>", self.usb_menu)
        self.conn_button = tk.Label(group, font=self.f_bold, padx=14, cursor="hand2")
        self.conn_button.bind("<Button-1>", lambda _e: self.on_conn_button())

        tk.Frame(inner, bg=pal["line"], width=1).pack(side="left", fill="y", padx=18)

        # gear (rightmost), machine meters, then the graph fills what is left
        gear = tk.Label(inner, text="⚙", bg=pal["panel2"], fg=pal["muted"], font=(self.f_title[0], 14),
                        width=2, cursor="hand2", highlightthickness=1, highlightbackground=pal["line"])
        gear.pack(side="right", padx=(12, 0))
        gear.bind("<Button-1>", lambda _e: self.toggle_settings())
        self.gear = gear

        self.meters_box = None
        if self.s["show_host"] or self.s["show_car"]:
            box = tk.Frame(inner, bg=pal["panel2"], highlightthickness=1, highlightbackground=pal["line"], padx=12, pady=6)
            box.pack(side="right", fill="y")
            self.meters_box = {}
            for row, (key, show) in enumerate((("pc", self.s["show_host"]), ("car", self.s["show_car"]))):
                if not show:
                    continue
                tk.Label(box, text=t(key), bg=pal["panel2"], fg=pal["muted"], font=self.f_small, width=5,
                         anchor="w").grid(row=row, column=0, sticky="w")
                cells = {}
                for col, metric in enumerate(("CPU", "GPU", "RAM")):
                    cells[metric] = MiniMeter(box, metric, pal, self.f_tiny, self.f_num_small)
                    cells[metric].grid(row=row, column=col + 1, padx=(8, 0), pady=2)
                self.meters_box[key] = cells

        graph_box = tk.Frame(inner, bg=pal["panel2"], highlightthickness=1, highlightbackground=pal["line"], padx=10, pady=5)
        graph_box.pack(side="left", fill="both", expand=True, padx=(0, 12))
        now = tk.Frame(graph_box, bg=pal["panel2"])
        now.pack(side="left", fill="y", padx=(0, 12))
        self.down_label = tk.Label(now, bg=pal["panel2"], fg=pal["text"], font=self.f_num, anchor="w", width=13)
        self.down_label.pack(anchor="w", expand=True)
        self.up_label = tk.Label(now, bg=pal["panel2"], fg=pal["text"], font=self.f_num, anchor="w", width=13)
        self.up_label.pack(anchor="w", expand=True)
        right = tk.Frame(graph_box, bg=pal["panel2"])
        right.pack(side="left", fill="both", expand=True)
        head = tk.Frame(right, bg=pal["panel2"])
        head.pack(fill="x")
        self.peak_label = tk.Label(head, bg=pal["panel2"], fg=pal["muted"], font=self.f_tiny)
        self.peak_label.pack(side="right")  # packed first: keeps its room when the box is narrow
        if self.size_name != "small":  # no room for the caption next to the peak in the small window
            tk.Label(head, text=t("history", s=self.s["graph_seconds"]), bg=pal["panel2"], fg=pal["muted"],
                     font=self.f_tiny).pack(side="left")
        self.graph = tk.Canvas(right, height=40, bg=pal["panel2"], highlightthickness=0)
        self.graph.pack(fill="both", expand=True, pady=(2, 0))
        self.draw_rates((0.0, 0.0))

    def build_screens(self):
        pal, t, sizes = self.pal, self.t, self.sizes()
        body = tk.Frame(self.root, bg=pal["bg"], padx=20, pady=18)
        body.pack()
        model = self.layout_model()
        old = self.screens
        self.screens = {}
        main = self.add_screen(body, "main", sizes["main"])
        main.canvas.grid(row=0, column=0, sticky="n", padx=(0, 18))
        right = tk.Frame(body, bg=pal["bg"])
        right.grid(row=0, column=1, sticky="n")

        main.chin_label(t("main"), fg=pal["text"], font=self.f_bold, padx=(6, 8))
        main.chin_label(f"{2560}×{1600}")
        self.control_var = tk.BooleanVar(value=self.s["control"])
        Switch(main.chin, self.control_var, pal, self.set_control, bg=pal["bezel"]).pack(side="right", padx=(6, 6))
        tk.Label(main.chin, text=t("control"), bg=pal["bezel"], fg=pal["text"], font=self.f_small).pack(side="right")
        self.add_chin_status(main)
        for event in ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>"):
            main.canvas.bind(event, self.on_touch)
        self.apply_control_look()

        if model == "EX5":
            hud = self.add_screen(right, "hud", sizes["hud"])
            hud.canvas.pack()
            hud.chin_label(t("hud"), fg=pal["text"], font=self.f_bold, padx=(6, 8))
            hud.chin_label(t("rotated") if self.s["rotate_hud"] else "")
            hud.chin_label(t("view_only"), side="right", padx=(0, 8))
            self.add_chin_status(hud)
            cluster = self.add_screen(right, "cluster", sizes["cluster"])
            cluster.canvas.pack(pady=(14, 0))
            cluster.chin_label(t("cluster"), fg=pal["text"], font=self.f_bold, padx=(6, 8))
            cluster.ago = cluster.chin_label("")
            self.refresh_var = tk.BooleanVar(value=self.s["cluster_refresh"])
            Switch(cluster.chin, self.refresh_var, pal, self.set_cluster_refresh, bg=pal["bezel"]).pack(side="right", padx=(6, 6))
            interval = self.s["cluster_interval"]
            tk.Label(cluster.chin, text=t("refresh", s=f"{interval:g}"), bg=pal["bezel"], fg=pal["text"],
                     font=self.f_small).pack(side="right")
            self.add_chin_status(cluster, fps=False)
        else:  # EX2: no HUD; cluster path unknown
            w, h = sizes["hud"][0], sizes["hud"][1] + sizes["cluster"][1] + 30
            box = tk.Canvas(right, width=w + 2 * PAD, height=h + PAD + CHIN, bg=pal["bg"], highlightthickness=0)
            box.pack()
            round_rect(box, 1, 1, w + 2 * PAD - 1, h + PAD + CHIN - 1, RADIUS, fill=pal["bezel"], outline=pal["bezel_line"])
            box.create_rectangle(PAD, PAD, PAD + w, PAD + h, outline=pal["line"], dash=(3, 3))
            box.create_text(PAD + w // 2, PAD + h // 2 - 22, text=t("ex2_cluster_title"), fill=pal["text"], font=self.f_bold)
            box.create_text(PAD + w // 2, PAD + h // 2 + 14, text=t("ex2_cluster_body"), fill=pal["muted"],
                            font=self.f_small, justify="center")
            box.create_text(PAD + 8, PAD + h + CHIN // 2, text=f"{t('cluster')} · {t('st_unsupported')}",
                            fill=pal["muted"], font=self.f_small, anchor="w")
            tk.Label(right, text=t("ex2_note"), bg=pal["bg"], fg=pal["muted"], font=self.f_tiny,
                     wraplength=w + 2 * PAD, justify="left").pack(anchor="w", pady=(10, 0))
        # keep states across rebuilds (language/theme/size changes while streaming)
        for name, screen in self.screens.items():
            if name in old:
                screen.state = old[name].state
            self.paint_state(screen)

    def add_screen(self, parent, name, size):
        screen = Screen(self, parent, name, size)
        self.screens[name] = screen
        return screen

    def add_chin_status(self, screen, fps=True):
        pal = self.pal
        tk.Frame(screen.chin, bg=pal["line"], width=1, height=22).pack(side="right", padx=10)
        screen.bw_label = tk.Label(screen.chin, bg=pal["bezel"], fg=pal["down"], font=self.f_num_small, width=7, anchor="e")
        screen.bw_label.pack(side="right")
        screen.fps_label = tk.Label(screen.chin, bg=pal["bezel"], fg=pal["muted"], font=self.f_num_small,
                                    width=7 if fps else 0, anchor="e")
        if fps:  # the cluster sends one picture every few seconds: fps would only mislead
            screen.fps_label.pack(side="right")
        screen.state_label = tk.Label(screen.chin, bg=pal["bezel"], fg=pal["text"], font=self.f_small)
        screen.state_label.pack(side="right", padx=(0, 4))
        screen.state_dot = Dot(screen.chin, pal, pal["bezel"], 7)
        screen.state_dot.pack(side="right", padx=(0, 6))

    # ---------- state painting ----------
    def paint_state(self, screen):
        pal = self.pal
        colour = {"live": pal["live"], "connecting": pal["warn"], "reconnecting": pal["warn"], "error": pal["bad"],
                  "paused": pal["muted"]}.get(screen.state, pal["off_dot"])
        screen.state_dot.set(colour)
        screen.state_label.configure(text=self.t(f"st_{screen.state}"),
                                     fg=pal["text"] if screen.state == "live" else pal["warn"]
                                     if screen.state in ("connecting", "reconnecting") else pal["muted"])
        if screen.state != "live":
            screen.fps_label.configure(text="")
        screen.draw_message()

    def set_state(self, name, state):
        screen = self.screens.get(name)
        if not screen or screen.state == state:
            return
        if state == "reconnecting" and screen.state == "live":
            self.history.mark_drop()
        screen.state = state
        self.paint_state(screen)

    def update_conn_ui(self):
        pal, t = self.pal, self.t
        if not hasattr(self, "conn_button"):
            return
        usb = self.s["link"] == "usb"
        self.ip_entry.pack_forget()
        self.usb_pick.pack_forget()
        self.conn_button.pack_forget()
        (self.usb_pick if usb else self.ip_entry).pack(side="left", fill="y", ipady=5)
        self.conn_button.pack(side="left", fill="y")
        self.ip_entry.configure(state="disabled" if self.conn == "connecting" else "normal")
        if usb:
            label = next((f"{m or 'USB'}  {s}" for s, m in self.usb_list if s == self.s["usb_serial"]), None)
            self.usb_pick.configure(text=(label or t("no_usb")) + "  ▾", fg=pal["text"] if label else pal["muted"])
        edited = self.conn == "connected" and not usb and \
            adb.parse_address(self.ip_var.get(), self.s["port"]) != self.address
        if self.conn == "connecting":
            look = ("btn_cancel", "#1a1508", pal["warn"])
        elif self.conn == "connected" and not edited:
            look = ("btn_disconnect", pal["panel2"], pal["text"])
        else:
            disabled = usb and not self.usb_list
            look = ("btn_connect", pal["line"] if disabled else pal["accent"], pal["muted"] if disabled else pal["accent_ink"])
        self.conn_button.configure(text=t(look[0]), bg=look[1], fg=look[2])
        status = {"idle": "conn_idle", "connecting": "conn_connecting", "connected": "conn_connected"}[self.conn]
        if self.conn == "connected" and not self.car_ok:
            status = "conn_lost"
        if not getattr(self, "conn_error", None) or self.conn != "idle":
            self.conn_label.configure(text=t(status), fg=pal["text"])
        colour = {"idle": pal["off_dot"], "connecting": pal["warn"],
                  "connected": pal["live"] if self.car_ok else pal["warn"]}[self.conn]
        self.conn_dot.set(colour)
        model = self.model if self.conn == "connected" else (self.s["model"] if self.s["model"] != "auto" else t("model_auto"))
        self.model_chip.configure(text=f"{model} ▾")
        if self.conn == "connected" and not usb:
            self.ping_label.configure(text=f"ping {self.ping:.0f} ms" if self.ping is not None else "ping –")
        else:
            self.ping_label.configure(text="")

    def apply_control_look(self):
        main = self.screens.get("main")
        if main:
            on = self.control_var.get()
            main.set_outline(self.pal["accent"] if on else self.pal["bezel_line"], 2 if on else 1)
            main.canvas.configure(cursor="hand2" if on else "")

    # ---------- connection ----------
    def can_auto_connect(self):
        return bool(self.s["usb_serial"]) if self.s["link"] == "usb" else bool(adb.parse_address(self.s["address"], self.s["port"]))

    def on_conn_button(self):
        if self.conn == "connecting":
            self.disconnect()
        elif self.conn == "connected" and (self.s["link"] == "usb" or
                                           adb.parse_address(self.ip_var.get(), self.s["port"]) == self.address):
            self.disconnect()
        else:
            self.connect()

    def set_link(self, link):
        if self.conn != "idle":
            self.disconnect()
        self.s.set("link", link)
        self.update_conn_ui()

    def connect(self):
        self.disconnect(quiet=True)
        self.conn_error = None
        if self.s["link"] == "usb":
            serial = self.s["usb_serial"]
            if not serial:
                return
            address = None
        else:
            address = adb.parse_address(self.ip_var.get(), self.s["port"])
            if not address:
                self.conn_label.configure(text=self.t("bad_ip"), fg=self.pal["bad"])
                self.conn_error = "bad_ip"
                return
            self.s.set("address", self.ip_var.get().strip())
            serial = address
        self.generation += 1
        self.conn = "connecting"
        self.update_conn_ui()
        threading.Thread(target=self._connect_worker, args=(self.generation, serial, address), daemon=True).start()

    def _connect_worker(self, generation, serial, address):
        try:
            if address:
                ok, message = adb.connect(address)
                if not ok:
                    raise RuntimeError(message)
            state = adb.run("-s", serial, "get-state", timeout=8).stdout.strip()
            if state != "device":
                raise RuntimeError(state or "device not ready")
            info = adb.props(serial, "ro.product.model", "ro.board.platform", "ro.hardware", "ro.product.name")
            detected = adb.detect_model(info)
        except Exception as error:  # adb missing, timeout, refused...
            text = self.t("timeout") if "imed out" in str(error) or isinstance(error, subprocess.TimeoutExpired) else str(error)
            self.ui(lambda: self._connect_failed(generation, text))
            return
        self.ui(lambda: self._connected(generation, serial, address, detected))

    def _connect_failed(self, generation, text):
        if generation != self.generation:
            return
        self.conn = "idle"
        self.conn_error = text
        self.update_conn_ui()
        self.conn_label.configure(text=self.t("conn_failed", e=text[:60]), fg=self.pal["bad"])
        for screen in self.screens.values():
            screen.state = "error"
            self.paint_state(screen)

    def _connected(self, generation, serial, address, detected):
        if generation != self.generation:
            return
        self.serial, self.address, self.detected_model = serial, address, detected
        self.model = self.layout_model()
        self.conn, self.car_ok, self.ping = "connected", True, None
        self.car_stats = CarStats(serial)
        self.history = History(self.s["graph_seconds"])
        self.build()
        self.start_streams()

    def start_streams(self):
        reconnect = self.s["auto_reconnect"]
        frames_cb = self.frame_from_worker
        state_cb = lambda name, state: self.ui(lambda: self.set_state(name, state))
        self.meters = {name: Meter() for name in ("main", "hud", "cluster")}
        self.streams["main"] = VideoStream("main", self.serial, DISPLAYS["main"], lambda: self.sizes()["main"],
                                           frames_cb, state_cb, self.meters["main"], control=True,
                                           max_fps=self.s["max_fps"], reconnect=reconnect)
        if self.model == "EX5":
            self.streams["hud"] = VideoStream("hud", self.serial, DISPLAYS["hud"], lambda: self.sizes()["hud"],
                                              frames_cb, state_cb, self.meters["hud"], max_fps=self.s["max_fps"],
                                              rotate_fn=lambda: self.s["rotate_hud"], reconnect=reconnect)
            if self.s["cluster_refresh"]:
                self.start_cluster()
            else:
                self.set_state("cluster", "paused")
        for name in ("main", "hud"):
            if name in self.streams:
                self.streams[name].start()

    def start_cluster(self):
        stream = ClusterStream(self.serial, self.s["cluster_interval"], lambda: self.sizes()["cluster"],
                               self.frame_from_worker, lambda n, st: self.ui(lambda: self.set_state(n, st)),
                               self.meters["cluster"], reconnect=self.s["auto_reconnect"])
        self.streams["cluster"] = stream
        stream.start()

    def stop_streams(self):
        streams, self.streams = list(self.streams.values()), {}
        for stream in streams:
            if stream:
                stream.stop()
        self.frames.clear()

    def disconnect(self, quiet=False):
        self.generation += 1
        self.stop_streams()
        was = self.conn
        self.conn, self.serial, self.address, self.car_stats = "idle", None, None, None
        if was != "idle" and not quiet:
            for screen in self.screens.values():
                screen.has_frame = False
                screen.state = "idle"
                self.paint_state(screen)
        self.update_conn_ui()

    # ---------- user controls ----------
    def set_control(self, value):
        self.s.set("control", value)
        self.apply_control_look()

    def set_cluster_refresh(self, value):
        self.s.set("cluster_refresh", value)
        if self.conn != "connected" or self.model != "EX5":
            return
        if value:
            self.start_cluster()
        else:
            stream = self.streams.pop("cluster", None)
            if stream:
                stream.stop()
            self.set_state("cluster", "paused")

    def on_touch(self, event):
        main, stream = self.screens.get("main"), self.streams.get("main")
        if not (main and stream and self.control_var.get()):
            return
        w, h = main.size
        fx, fy = (event.x - PAD) / w, (event.y - PAD) / h
        if event.type == tk.EventType.ButtonPress:
            if not (0 <= fx <= 1 and 0 <= fy <= 1):
                return
            self.press = time.monotonic()
            stream.touch(TOUCH_DOWN, fx, fy)
        elif self.press is None:
            return
        elif event.type == tk.EventType.Motion:
            now = time.monotonic()
            if now - self.press >= 1 / 60:  # cap move events at 60/s
                self.press = now
                stream.touch(TOUCH_MOVE, fx, fy)
        else:
            stream.touch(TOUCH_UP, fx, fy)
            self.press = None

    def model_menu(self, event):
        t = self.t
        menu = tk.Menu(self.root, tearoff=0, bg=self.pal["panel2"], fg=self.pal["text"],
                       activebackground="#10202b", activeforeground=self.pal["accent"], font=self.f_small)
        found = t("model_found", m=self.detected_model) if self.detected_model else ""
        options = [("auto", f"{t('model_auto')}  {found}".strip()), ("EX5", f"EX5  ·  {t('model_ex5')}"),
                   ("EX2", f"EX2  ·  {t('model_ex2')}")]
        for value, label in options:
            prefix = "● " if self.s["model"] == value else "   "
            menu.add_command(label=prefix + label, command=lambda v=value: self.set_model(v))
            if value == "auto":
                menu.add_separator()
        menu.tk_popup(event.x_root, event.y_root + 10)

    def set_model(self, value):
        self.s.set("model", value)
        if self.conn == "connected":
            self.stop_streams()
            self.model = self.layout_model()
            self.build()
            self.start_streams()
        else:
            self.update_conn_ui()

    def usb_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0, bg=self.pal["panel2"], fg=self.pal["text"], font=self.f_small)
        if not self.usb_list:
            menu.add_command(label=self.t("usb_hint"), state="disabled")
        for serial, model in self.usb_list:
            menu.add_command(label=f"{model or 'USB'}  {serial}", command=lambda s=serial: self.pick_usb(s))
        menu.tk_popup(event.x_root, event.y_root + 10)

    def pick_usb(self, serial):
        self.s.set("usb_serial", serial)
        self.update_conn_ui()

    # ---------- settings panel ----------
    def toggle_settings(self):
        if self.settings_panel:
            self.close_settings()
            return
        from .settings_panel import SettingsPanel
        self.settings_panel = SettingsPanel(self)
        self.gear.configure(bg=self.pal["accent"], fg=self.pal["accent_ink"])

    def close_settings(self):
        if self.settings_panel:
            self.settings_panel.destroy()
            self.settings_panel = None
            self.gear.configure(bg=self.pal["panel2"], fg=self.pal["muted"])

    def change_setting(self, key, value):
        """Called by the settings panel. Rebuilds or restarts only what the setting affects."""
        old = self.s.get(key)
        self.s.set(key, value)
        if old == value:
            return
        if key in ("language", "theme", "size", "show_host", "show_car", "rotate_hud", "graph_seconds", "cluster_interval"):
            if key == "graph_seconds":
                self.history.resize(value)
            self.build()
        if key == "topmost":
            self.root.attributes("-topmost", bool(value))
        if key in ("max_fps", "auto_reconnect", "cluster_interval") and self.conn == "connected":
            self.stop_streams()
            self.start_streams()

    def reset_settings(self):
        self.s.reset()
        self.ip_var.set("")
        self.build()

    def show_paths(self):
        try:
            server = paths.find_server()
        except FileNotFoundError as error:
            server = str(error)
        messagebox.showinfo("EX5 Viewer", f"adb:\n{adb.ADB}\n\nscrcpy-server:\n{server}\n\nlog / settings:\n{paths.config_dir()}",
                            parent=self.root)

    def open_log(self):
        open_path(paths.config_dir() / "ex5-viewer.log")

    # ---------- loops ----------
    def ui(self, task):
        """Run task on the Tk thread; workers must never touch Tk directly."""
        self.ui_tasks.put(task)

    def frame_from_worker(self, name, image):
        self.frames[name] = image

    def refresh(self):
        while True:
            try:
                task = self.ui_tasks.get_nowait()
            except queue.Empty:
                break
            try:
                task()
            except tk.TclError:  # widget gone after a rebuild
                pass
        for name in list(self.frames):
            image = self.frames.pop(name, None)
            screen = self.screens.get(name)
            if image is not None and screen and name in self.streams:
                screen.show(image)
                screen.fps_count += 1
                screen.last_frame_at = time.monotonic()
        self.root.after(15, self.refresh)

    def tick(self):
        down = up = 0
        for name, meter in self.meters.items():
            d, u = meter.take()
            down, up = down + d, up + u
            screen = self.screens.get(name)
            if screen and hasattr(screen, "bw_label"):
                screen.down_bytes = d
                live = screen.state == "live"
                screen.bw_label.configure(text=f"↓ {d * 8 / 1e6:.1f}" if live else "")
                if live and name != "cluster":
                    screen.fps_label.configure(text=f"{screen.fps_count} fps")
            if screen:
                screen.fps_count = 0
        self.draw_rates(self.history.tick(down, up))
        cluster = self.screens.get("cluster")
        if cluster and hasattr(cluster, "ago"):
            age = time.monotonic() - cluster.last_frame_at if cluster.last_frame_at else None
            cluster.ago.configure(text=self.t("ago", s=f"{age:.0f}") if age is not None else "")
        if self.conn == "connected" and self.s["link"] == "wifi":
            self.update_conn_ui()
        self.root.after(1000, self.tick)

    def draw_rates(self, now):
        pal = self.pal
        self.down_label.configure(text=f"↓ {now[0]:5.1f} Mb/s", fg=pal["down"])
        self.up_label.configure(text=f"↑ {now[1]:5.1f} Mb/s", fg=pal["up"])
        self.peak_label.configure(text=f"{self.t('peak')} {self.history.peak():.1f} Mb/s")
        graph = self.graph
        graph.delete("all")
        width, height = max(graph.winfo_width(), 50), max(graph.winfo_height(), 30)
        graph.create_line(0, height - 1, width, height - 1, fill=pal["line"])
        graph.create_line(0, height // 2, width, height // 2, fill=pal["line"], dash=(2, 4))
        samples, slots = list(self.history.samples), self.history.samples.maxlen
        if len(samples) < 2:
            return
        top = max(self.history.peak(), 1.0)
        step = width / (slots - 1)
        offset = slots - len(samples)
        for index, colour in ((0, pal["down"]), (1, pal["up"])):
            points = []
            for i, sample in enumerate(samples):
                points += [(offset + i) * step, height - 2 - (height - 4) * sample[index] / top]
            graph.create_line(points, fill=colour, width=2 if index == 0 else 1.5, smooth=False)
        for age in self.history.drops:
            x = (slots - 1 - age) * step
            graph.create_line(x, 0, x, height, fill=pal["warn"], dash=(3, 3))

    def stats_loop(self):
        """Every 2 s: PC + car meters, ping, USB device list, and adb reconnect when the car vanished."""
        failures = 0
        while True:
            started = time.monotonic()
            host = self.host_stats.sample()
            car = ping = None
            usb = None
            serial, address, conn = self.serial, self.address, self.conn
            try:
                if self.s["link"] == "usb" or conn == "idle":
                    usb = adb.usb_devices()
                if conn == "connected" and serial and self.car_stats:
                    car = self.car_stats.sample()
                    ping = tcp_ping(address) if address else None
                    failures = 0 if car else failures + 1
                    if failures >= 2 and address and self.s["auto_reconnect"]:
                        adb.connect(address)  # Wi-Fi blip: adb drops the device and does not come back alone
            except Exception as error:
                log.debug("stats: %s", error)
                failures += 1
            self.ui(lambda h=host, c=car, p=ping, u=usb, f=failures: self.show_stats(h, c, p, u, f))
            time.sleep(max(0.5, 2 - (time.monotonic() - started)))

    def show_stats(self, host, car, ping, usb, failures):
        if usb is not None and usb != self.usb_list:
            self.usb_list = usb
            if usb and self.s["usb_serial"] not in [s for s, _ in usb]:
                self.s.set("usb_serial", usb[0][0])  # one device plugged in: pick it
            self.update_conn_ui()
        if self.conn == "connected":
            self.ping = ping if ping is not None else self.ping
            ok = failures < 2
            if ok != self.car_ok:
                self.car_ok = ok
            self.update_conn_ui()
        if not self.meters_box:
            return
        for key, values in (("pc", host), ("car", car if self.conn == "connected" else None)):
            cells = self.meters_box.get(key)
            if not cells:
                continue
            if not values:
                for cell in cells.values():
                    cell.set("–", None)
                continue
            for metric in ("cpu", "gpu"):
                value = values[metric]
                cells[metric.upper()].set(f"{value:.0f}%" if value is not None else "–",
                                          value / 100 if value is not None else None)
            used, total = values["ram"]
            cells["RAM"].set(human_gb(used, total), used / total if total else None)

    def quit(self):
        self.stop_streams()
        self.root.destroy()
