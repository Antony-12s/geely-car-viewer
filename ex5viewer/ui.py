"""Geely Car Viewer window, "OLED cinema" layout: top bar (brand + status | connection, settings), a centred
Main stage, a lower tray (HUD, Cluster, car data) and a quiet system floor (PC/car resources, app network)."""
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

from . import __version__, adb, paths, widgets
from .cluster import ClusterStream
from .i18n import Translator
from .settings import MAX_SCALE, MIN_SCALE
from .scrcpy import TOUCH_DOWN, TOUCH_MOVE, TOUCH_UP, VideoStream
from .carpanel import CarPanel
from .vehicle import VehicleStats
from .stats import CarStats, History, HostStats, Meter, human_gb, tcp_ping
from .widgets import (GAP, PAGE, RADIUS_BEZEL, Chip, Dot, IconButton, MiniMeter, Segmented, Switch, draw_icon,
                      measure, palette, round_rect)

log = logging.getLogger(__name__)

# ---- "OLED cinema" geometry: everything below scales with k except text, bars and paddings ----
MAIN_BASE = (704, 440)                     # Main picture at k = 1 (2560 × 1600, 16:10)
SIDE_RATIO = 0.28                          # stage side column (title / control | note / stream) per Main width
AUX_RATIO = 0.21                           # HUD / Cluster picture height per Main height (mockup 124 / 540)
ROW_GAP = 10                               # stage -> tray -> floor
ASPECT = {"hud": 800 / 480, "cluster": 1920 / 532}
SCALE = {"small": 0.8, "medium": 1.1, "large": 1.375}  # small fits a 1024 px screen
DISPLAYS = {"main": 0, "hud": 1}           # Android display ids on the EX5
INSET = 2                                  # picture inset inside a screen canvas (room for the control outline)
TOP_H = 52                                 # top bar: brand + status | connection + settings
CTRL_H = 34                                # height of the top bar controls
AUX_PAD, AUX_HEAD, AUX_FOOT = 7, 22, 24    # tray card: inner padding, title row, footer row
FLOOR_H = 74                               # system floor (resources + app network)
TITLE_W = 112                              # left title column of the floor blocks
GEAR = 34                                  # kept for callers that size against the settings button
RADIUS = RADIUS_BEZEL                      # tray screen cards


def even(value):
    return int(value) // 2 * 2


def pick_font(candidates, fallback):
    families = set(tkfont.families())
    return next((name for name in candidates if name in families), fallback)


def open_path(path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - user asked to open their own log file
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)], **adb.NO_WINDOW)


class Screen:
    """One picture canvas. Owns its state text and the last frame. The labels around it (title, state, fps,
    bandwidth) live in the stage side columns (Main) or the tray card (HUD, Cluster)."""

    def __init__(self, app, parent, name, size, bg):
        self.app, self.name, self.size, self.inset = app, name, size, INSET
        pal, w, h = app.pal, *size
        self.bg = bg
        self.canvas = tk.Canvas(parent, width=w + 2 * INSET, height=h + 2 * INSET, bg=bg, highlightthickness=0)
        self.photo = ImageTk.PhotoImage(Image.new("RGB", size, pal["bezel"]))
        self.canvas.create_image(INSET, INSET, image=self.photo, anchor="nw", tags="frame")
        self.outline = self.canvas.create_rectangle(1, 1, w + 2 * INSET - 1, h + 2 * INSET - 1, outline=bg, width=2,
                                                    tags="outline")
        self.has_frame, self.state, self.fps_count, self.last_frame_at = False, "idle", 0, None
        self.down_bytes = 0

    def show(self, image):
        if image.size != self.size:
            image = image.resize(self.size)
        self.photo.paste(image)
        if not self.has_frame:
            self.has_frame = True
            self.draw_message()

    def set_outline(self, colour, width):
        self.canvas.itemconfigure(self.outline, outline=colour, width=width)

    def draw_message(self):
        canvas, (w, h), pal, app, t = self.canvas, self.size, self.app.pal, self.app, self.app.t
        canvas.delete("message")
        key = {"idle": "msg_idle", "connecting": "msg_connecting", "reconnecting": "msg_reconnecting",
               "error": "msg_error", "paused": "msg_paused"}.get(self.state)
        if not key:
            return
        x0 = y0 = INSET
        if self.has_frame and self.state != "idle":
            colour = pal["warn"] if self.state in ("reconnecting", "paused") else pal["bad"] if self.state == "error" else pal["line"]
            bar = 24 if h < 200 else 32
            canvas.create_rectangle(x0, y0 + h - bar, x0 + w, y0 + h, fill=pal["panel"], outline="", tags="message")
            canvas.create_line(x0, y0 + h - bar, x0 + w, y0 + h - bar, fill=colour, tags="message")
            canvas.create_text(x0 + 10, y0 + h - bar / 2, text=t(key), fill=pal["text"], font=app.f_small,
                               anchor="w", width=w - 20, tags="message")
        else:
            if self.state == "idle":
                self.photo.paste(Image.new("RGB", self.size, pal["bezel"]))
                self.has_frame = False
            hint = {"idle": "hint_idle", "connecting": "hint_connecting", "reconnecting": "hint_connecting",
                    "error": "hint_error", "paused": "hint_paused"}[self.state]
            cx, cy = x0 + w // 2, y0 + h // 2
            if h >= 200:  # Main: glyph, one line, one muted hint
                glyph = "pause" if self.state == "paused" else "screen"
                draw_icon(canvas, glyph, cx - 11, cy - 34, 22, pal["muted"], width=1.6, tags="message")
                canvas.create_text(cx, cy + 2, text=t(key), fill=pal["text"], font=app.f_body, tags="message")
                canvas.create_text(cx, cy + 24, text=t(hint), fill=pal["muted"], font=app.f_small, width=w - 24,
                                   justify="center", tags="message")
            else:  # tray pictures are ~100 px tall: one centred line, wrapped inside the picture
                canvas.create_text(cx, cy, text=t(key), fill=pal["muted"], font=app.f_small, width=w - 16,
                                   justify="center", tags="message")
        canvas.tag_raise("outline")


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
        self.tcam = None
        self.car_data, self.vehicle_stats, self._tbox_last = {}, None, None
        self.host_stats, self.car_stats = HostStats(), None
        self.press = None
        self.screens = {}
        self.settings_panel = None
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.bind("<Escape>", lambda _e: self.close_settings())
        self._building, self._resize_job = False, None
        self.root.bind("<Configure>", self.on_configure)
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
        self._building = True
        if self.s["scale"]:  # size picked by dragging the window corner
            self.k = self.s["scale"]
            self.size_name = "small" if self.k < 0.95 else "medium"  # compact layout tweaks below medium
            self._build_widgets()
        else:
            chosen = self.s["size"]
            for self.size_name in ("medium", "small") if chosen == "auto" else (chosen,):
                self.k = SCALE[self.size_name]
                self._build_widgets()
                if self.size_name == "small" or self.fits_screen():
                    break
        self.root.update_idletasks()
        self._built_req = (self.root.winfo_reqwidth(), self.root.winfo_reqheight(), self.k)
        req_w, req_h, k = self._built_req  # smallest drag size = this layout at MIN_SCALE
        per_w, per_h = self.scale_terms()
        self.root.minsize(int(req_w - (k - MIN_SCALE) * per_w), int(req_h - (k - MIN_SCALE) * per_h))
        self._building = False
        if reopen:
            self.toggle_settings()

    @staticmethod
    def scale_terms():
        """Window pixels added per unit of k: width = Main + two side columns, height = Main + tray pictures."""
        return MAIN_BASE[0] * (1 + 2 * SIDE_RATIO), MAIN_BASE[1] * (1 + AUX_RATIO)

    # ---------- drag-to-resize ----------
    def on_configure(self, event):
        """Window dragged/maximised: rescale the screens to fill it (after the drag settles)."""
        if event.widget is not self.root or self._building:
            return
        req_w, req_h, _k = self._built_req
        if abs(event.width - req_w) <= 6 and abs(event.height - req_h) <= 6:
            return  # our own layout, not the user
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(250, self.fit_to_window)

    def fit_to_window(self):
        """Pick the scale whose layout fits the window. Pictures grow linearly with the scale; bars, text and
        padding do not, so solve for k from the last layout and correct once if needed."""
        self._resize_job = None
        width, height = self.root.winfo_width(), self.root.winfo_height()
        per_w, per_h = self.scale_terms()
        for _ in range(3):
            req_w, req_h, k = self._built_req
            fixed_w, fixed_h = req_w - k * per_w, req_h - k * per_h
            new_k = min((width - fixed_w) / per_w, (height - fixed_h) / per_h)
            new_k = round(max(MIN_SCALE, min(MAX_SCALE, new_k)), 3)
            if abs(new_k - k) < 0.01 and req_w <= width and req_h <= height:
                return
            self.s.set("scale", new_k)
            self.build()
            if self._built_req[0] <= width and self._built_req[1] <= height:
                return

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
        widgets.ANIMATE = bool(self.s["animations"])
        thai = pick_font(["Noto Sans Thai", "Leelawadee UI", "Sukhumvit Set", "Thonburi", "Tahoma"], "TkDefaultFont")
        mono = pick_font(["Noto Sans Mono", "DejaVu Sans Mono", "Consolas", "Menlo", "Courier New"], "TkFixedFont")
        self.f_body, self.f_bold = (thai, 10), (thai, 10, "bold")   # secondary text, buttons
        self.f_small = (thai, 9)                                       # units, captions, stream meta
        self.f_tiny = (thai, 8)                                        # notes under blocks
        self.f_caption = (thai, 9, "bold")                             # block titles
        self.f_title = (thai, 11, "bold")                              # app name, settings title
        self.f_stage = (thai, 15, "bold")                              # "จอกลาง" beside the stage
        self.f_value = (mono, 19)                                      # primary car values
        self.f_num, self.f_num_bold = (mono, 9), (mono, 10)            # numbers: IP, rates, fps, meters
        self.root.configure(bg=pal["bg"])
        self.root.option_add("*Font", self.f_body)
        self.root.title("Geely Car Viewer")
        icon = paths.resource_dir() / "icon.png"
        if icon.is_file():
            self._icon = tk.PhotoImage(file=str(icon))
            self.root.iconphoto(True, self._icon)
        self.root.resizable(True, True)
        self.root.attributes("-topmost", bool(self.s["topmost"]))
        self.build_topbar()
        self.build_screens()
        self.build_floor()
        self.update_conn_ui()

    def layout_model(self):
        if self.s["model"] != "auto":
            return self.s["model"]
        return self.detected_model or "EX5"

    def sizes(self):
        """Picture sizes (even numbers, true aspect) for the current scale; the streams scale to these."""
        k = self.k
        main = (even(MAIN_BASE[0] * k), even(MAIN_BASE[1] * k))
        aux_h = even(main[1] * AUX_RATIO)
        return {"main": main,
                "hud": (even(aux_h * ASPECT["hud"]), aux_h),
                "cluster": (even(aux_h * ASPECT["cluster"]), aux_h)}

    def page_width(self):
        """Width of every row: the stage (side column | Main | side column)."""
        return self.sizes()["main"][0] + 2 * INSET + 2 * self.side_width()

    def side_width(self):
        return int(self.sizes()["main"][0] * SIDE_RATIO)

    # ---------- top bar ----------
    def build_topbar(self):
        """Brand + connection status on the left; link, address, connect and settings on the right."""
        pal, t = self.pal, self.t
        bar = tk.Frame(self.root, bg=pal["bg"], width=self.page_width(), height=TOP_H)
        bar.pack(padx=PAGE, pady=(4, 4))
        bar.pack_propagate(False)

        # right side first: pack keeps their room and the status text gets clipped instead
        self.gear = IconButton(bar, pal, pal["bg"], "sliders", self.toggle_settings, CTRL_H, text=t("settings"),
                               font=self.f_small)
        self.gear.pack(side="right", padx=(12, 0))
        self.conn_button = Chip(bar, "", self.f_bold, bg=pal["bg"], fill=pal["accent"], fg=pal["accent_ink"],
                                padx=18, height=CTRL_H)
        self.conn_button.bind("<Button-1>", lambda _e: self.on_conn_button())
        self.conn_button.pack(side="right", padx=(8, 0))
        self.address_box = tk.Frame(bar, bg=pal["field"], highlightthickness=1, highlightbackground=pal["line"],
                                    highlightcolor=pal["accent"], height=CTRL_H)
        self.address_box.pack(side="right", padx=(8, 0), fill="y", pady=(TOP_H - CTRL_H) // 2)
        self.ip_caption = tk.Label(self.address_box, text="IP", bg=pal["field"], fg=pal["muted"], font=self.f_tiny)
        self.ip_var = tk.StringVar(value=self.s["address"])
        entry_chars = 17 if self.size_name != "small" else 15
        self.ip_entry = tk.Entry(self.address_box, textvariable=self.ip_var, width=entry_chars, bg=pal["field"],
                                 fg=pal["text"], relief="flat", insertbackground=pal["accent"], font=self.f_num,
                                 disabledbackground=pal["field"], disabledforeground=pal["muted"],
                                 highlightthickness=0, selectbackground=pal["accent_line"])
        self.ip_entry.bind("<Return>", lambda _e: self.on_conn_button())
        self.ip_var.trace_add("write", lambda *_: self.update_conn_ui())
        self.usb_pick = tk.Label(self.address_box, bg=pal["field"], fg=pal["text"], font=self.f_small,
                                 width=entry_chars + 3, anchor="w", padx=8, cursor="hand2")
        self.usb_pick.bind("<Button-1>", self.usb_menu)
        self.link_seg = Segmented(bar, [("wifi", "Wi‑Fi"), ("usb", "USB")], self.s["link"], pal, self.set_link,
                                  self.f_small, bg=pal["bg"], fill=pal["field"], height=CTRL_H)
        self.link_seg.pack(side="right")

        brand = tk.Frame(bar, bg=pal["bg"])
        brand.pack(side="left", fill="y")
        mark = tk.Canvas(brand, width=30, height=30, bg=pal["bg"], highlightthickness=0)
        mark.pack(side="left", padx=(0, 12))
        round_rect(mark, 0.5, 0.5, 29.5, 29.5, 6, fill=pal["bg"], outline=pal["line"])
        mark.create_text(12, 15, text="G", fill=pal["text"], font=self.f_title)
        mark.create_text(20, 15, text="V", fill=pal["accent"], font=self.f_title)
        words = tk.Frame(brand, bg=pal["bg"])
        words.pack(side="left", pady=(4, 0))
        tk.Label(words, text="Geely Car Viewer", bg=pal["bg"], fg=pal["text"], font=self.f_title,
                 anchor="w").pack(anchor="w")
        status = tk.Frame(words, bg=pal["bg"])
        status.pack(anchor="w")
        self.conn_dot = Dot(status, pal, pal["bg"], 6)
        self.conn_dot.pack(side="left", padx=(1, 7))
        self.conn_label = tk.Label(status, bg=pal["bg"], fg=pal["muted"], font=self.f_small, anchor="w")
        self.conn_label.pack(side="left")
        self.model_chip = Chip(status, "", self.f_tiny, bg=pal["bg"], fill=pal["accent_soft"], fg=pal["accent"],
                               padx=7, height=17)
        self.model_chip.pack(side="left", padx=(10, 0))
        self.model_chip.bind("<Button-1>", self.model_menu)

    # ---------- stage + tray ----------
    def build_screens(self):
        pal, t, sizes = self.pal, self.t, self.sizes()
        page_w, side = self.page_width(), self.side_width()
        model = self.layout_model()
        old = self.screens
        self.screens = {}

        stage = tk.Frame(self.root, bg=pal["bg"])
        stage.pack(padx=PAGE)
        tk.Frame(stage, bg=pal["line"], width=page_w, height=1).pack()
        row = tk.Frame(stage, bg=pal["bg"])
        row.pack()
        tk.Frame(stage, bg=pal["line"], width=page_w, height=1).pack()
        main_h = sizes["main"][1] + 2 * INSET
        left = tk.Frame(row, bg=pal["bg"], width=side, height=main_h)
        left.grid(row=0, column=0)
        left.pack_propagate(False)
        main = self.add_screen(row, "main", sizes["main"], pal["bg"])
        main.canvas.grid(row=0, column=1)
        right = tk.Frame(row, bg=pal["bg"], width=side, height=main_h)
        right.grid(row=0, column=2)
        right.pack_propagate(False)

        # left: what this is, and the one control that can touch the car
        head = tk.Frame(left, bg=pal["bg"])
        head.pack(side="top", anchor="w", padx=(6, 0), pady=(24, 0))
        tk.Label(head, text=t("main"), bg=pal["bg"], fg=pal["text"], font=self.f_stage).pack(anchor="w")
        tk.Label(head, text=t("main_sub"), bg=pal["bg"], fg=pal["muted"], font=self.f_small).pack(anchor="w")
        tk.Label(head, text="2560 × 1600", bg=pal["bg"], fg=pal["muted"], font=self.f_tiny).pack(anchor="w",
                                                                                                 pady=(10, 0))
        control = tk.Frame(left, bg=pal["bg"])
        control.pack(side="bottom", anchor="w", padx=(6, 0), pady=(0, 18))
        tk.Label(control, text=t("control_main"), bg=pal["bg"], fg=pal["text"], font=self.f_small,
                 wraplength=side - 12, justify="left").pack(anchor="w", pady=(0, 8))
        self.control_var = tk.BooleanVar(value=self.s["control"])
        Switch(control, self.control_var, pal, self.set_control, bg=pal["bg"]).pack(anchor="w")
        for event in ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>"):
            main.canvas.bind(event, self.on_touch)

        # right: model + mode note on top, live stream numbers at the bottom
        note = tk.Frame(right, bg=pal["bg"])
        note.pack(side="top", anchor="e", padx=(0, 6), pady=(24, 0))
        self.stage_mode = tk.Label(note, bg=pal["bg"], fg=pal["text"], font=self.f_small, anchor="e",
                                   justify="right", wraplength=side - 12)
        self.stage_mode.pack(anchor="e")
        self.stage_hint = tk.Label(note, bg=pal["bg"], fg=pal["muted"], font=self.f_small, anchor="e",
                                   justify="right", wraplength=side - 12)
        self.stage_hint.pack(anchor="e", pady=(4, 0))
        tk.Label(note, text=t("main_only"), bg=pal["bg"], fg=pal["muted"], font=self.f_small, anchor="e",
                 justify="right", wraplength=side - 12).pack(anchor="e", pady=(4, 0))
        meta = tk.Frame(right, bg=pal["bg"])
        meta.pack(side="bottom", anchor="e", padx=(0, 6), pady=(0, 18))
        self.add_stream_status(main, meta, pal["bg"], stacked=True)
        self.apply_control_look()

        # tray: HUD card, Cluster card, car data
        tray = tk.Frame(self.root, bg=pal["bg"], width=page_w)
        tray.pack(padx=PAGE, pady=(ROW_GAP, 0))
        card_h = AUX_PAD + AUX_HEAD + sizes["hud"][1] + 2 * INSET + AUX_FOOT
        used = 0
        if model == "EX5":
            hud, foot = self.aux_card(tray, "hud", sizes["hud"], t("hud"), "HUD", "800 × 480", card_h)
            hud.card.grid(row=0, column=0, sticky="n", padx=(0, GAP))
            rotated = f" · {t('rotated')}" if self.s["rotate_hud"] and self.size_name != "small" else ""
            tk.Label(foot, text=t("view_only") + rotated,
                     bg=pal["bezel"], fg=pal["muted"], font=self.f_tiny).pack(side="left")
            self.add_stream_status(hud, foot, pal["bezel"])
            cluster, foot = self.aux_card(tray, "cluster", sizes["cluster"], t("cluster"), "Cluster", "1920 × 532",
                                          card_h)
            cluster.card.grid(row=0, column=1, sticky="n", padx=(0, GAP))
            interval = self.s["cluster_interval"]
            tk.Label(foot, text=t("refresh", s=f"{interval:g}"), bg=pal["bezel"], fg=pal["text"],
                     font=self.f_tiny).pack(side="left")
            self.refresh_var = tk.BooleanVar(value=self.s["cluster_refresh"])
            Switch(foot, self.refresh_var, pal, self.set_cluster_refresh, bg=pal["bezel"]).pack(side="left",
                                                                                               padx=(8, 0))
            self.add_stream_status(cluster, foot, pal["bezel"], fps=False)
            cluster.ago = tk.Label(foot, bg=pal["bezel"], fg=pal["muted"], font=self.f_tiny)
            cluster.ago.pack(side="right", padx=(0, 8))
            used = int(hud.card["width"]) + int(cluster.card["width"]) + 2 * GAP
        else:  # EX2: no HUD; cluster path unknown
            width = sizes["hud"][0] + sizes["cluster"][0] + 4 * INSET + 4 * AUX_PAD + GAP
            box = tk.Canvas(tray, width=width, height=card_h, bg=pal["bg"], highlightthickness=0)
            box.grid(row=0, column=0, columnspan=2, sticky="n", padx=(0, GAP))
            round_rect(box, 0.5, 0.5, width - 0.5, card_h - 0.5, RADIUS, fill=pal["bezel"], outline=pal["line"])
            box.create_text(AUX_PAD + 2, AUX_PAD + AUX_HEAD / 2, text=f"{t('cluster')} · {t('st_unsupported')}",
                            fill=pal["text"], font=self.f_caption, anchor="w")
            box.create_text(width / 2, card_h / 2, text=t("ex2_cluster_title"), fill=pal["text"], font=self.f_small)
            box.create_text(width / 2, card_h / 2 + 30, text=t("ex2_cluster_body") + "\n" + t("ex2_note"),
                            fill=pal["muted"], font=self.f_tiny, justify="center", width=width - 24)
            used = width + GAP
        self.car_panel = None
        vehicle_w = page_w - used
        if self.s["show_vehicle"] and vehicle_w > 200:
            self.car_panel = CarPanel(self, tray, vehicle_w, card_h)
            self.car_panel.grid(row=0, column=2, sticky="n")
            self.car_panel.update_data(**self.car_data)
        else:
            tk.Frame(tray, bg=pal["bg"], width=max(1, vehicle_w), height=card_h).grid(row=0, column=2)
        # keep states across rebuilds (language/theme/size changes while streaming)
        for name, screen in self.screens.items():
            if name in old:
                screen.state = old[name].state
            self.paint_state(screen)

    def aux_card(self, parent, name, size, title, sub, res, card_h):
        """Rounded card: title row, picture, footer. Returns (screen, footer frame)."""
        pal = self.pal
        width = size[0] + 2 * INSET + 2 * AUX_PAD
        card = tk.Canvas(parent, width=width, height=card_h, bg=pal["bg"], highlightthickness=0)
        round_rect(card, 0.5, 0.5, width - 0.5, card_h - 0.5, RADIUS, fill=pal["bezel"], outline=pal["line"])
        head_y = AUX_PAD + AUX_HEAD / 2
        title_item = card.create_text(AUX_PAD + 2, head_y, text=title, fill=pal["text"], font=self.f_caption,
                                      anchor="w")
        if sub != title:
            card.create_text(card.bbox(title_item)[2] + 6, head_y, text=sub, fill=pal["muted"], font=self.f_tiny,
                             anchor="w")
        card.create_text(width - AUX_PAD - 2, head_y, text=res, fill=pal["muted"], font=self.f_tiny, anchor="e")
        screen = self.add_screen(card, name, size, pal["bezel"])
        card.create_window(AUX_PAD, AUX_PAD + AUX_HEAD, window=screen.canvas, anchor="nw")
        foot = tk.Frame(card, bg=pal["bezel"], width=size[0], height=AUX_FOOT - 4)
        foot.pack_propagate(False)
        card.create_window(AUX_PAD + INSET, AUX_PAD + AUX_HEAD + size[1] + 2 * INSET + 1, window=foot, anchor="nw",
                           width=size[0], height=AUX_FOOT - 4)
        screen.card = card
        return screen, foot

    def add_screen(self, parent, name, size, bg):
        screen = Screen(self, parent, name, size, bg)
        self.screens[name] = screen
        return screen

    def add_stream_status(self, screen, parent, bg, fps=True, stacked=False):
        """Dot + state, fps, bandwidth. stacked: Main's side column (state on its own line, numbers below)."""
        pal = self.pal
        font = self.f_small if stacked else self.f_tiny
        top = tk.Frame(parent, bg=bg)
        top.pack(side="top" if stacked else "right", anchor="e")
        if stacked:
            nums = tk.Frame(parent, bg=bg)
            nums.pack(side="top", anchor="e", pady=(4, 0))
        else:
            nums = top
        screen.bw_label = tk.Label(nums, bg=bg, fg=pal["down"], font=self.f_num if stacked else self.f_tiny,
                                   anchor="e")
        screen.bw_label.pack(side="right")
        screen.fps_label = tk.Label(nums, bg=bg, fg=pal["muted"], font=self.f_num if stacked else self.f_tiny,
                                    anchor="e")
        if fps:  # the cluster sends one picture every few seconds: fps would only mislead
            screen.fps_label.pack(side="right", padx=(0, 8))
        screen.state_label = tk.Label(top, bg=bg, fg=pal["text"], font=font)
        if stacked:
            screen.state_label.pack(side="right")
            screen.state_dot = Dot(top, pal, bg, 6)
            screen.state_dot.pack(side="right", padx=(0, 7))
        else:
            screen.state_label.pack(side="right", padx=(0, 8))
            screen.state_dot = Dot(top, pal, bg, 6)
            screen.state_dot.pack(side="right", padx=(0, 6))

    # ---------- system floor ----------
    def build_floor(self):
        """Resources (this PC and the head unit) | this app's network traffic, as one quiet bottom strip."""
        pal, t = self.pal, self.t
        page_w = self.page_width()
        floor = self.floor = tk.Frame(self.root, bg=pal["bg"], width=page_w, height=FLOOR_H + 1)
        floor.pack(padx=PAGE, pady=(ROW_GAP, 6))
        floor.pack_propagate(False)
        floor.grid_propagate(False)
        tk.Frame(floor, bg=pal["line"], height=1).place(x=0, y=0, relwidth=1)
        show_meters = self.s["show_host"] or self.s["show_car"]
        res_w = int(page_w * 0.47) if show_meters else 0
        net_x = res_w + 32 if show_meters else 0
        self.meters_box = None
        if show_meters:
            res = tk.Frame(floor, bg=pal["bg"], width=res_w, height=FLOOR_H - 8)
            res.place(x=0, y=10)
            res.grid_propagate(False)
            res.grid_columnconfigure(0, minsize=TITLE_W)
            tk.Label(res, text=t("resources"), bg=pal["bg"], fg=pal["text"], font=self.f_caption,
                     anchor="w").grid(row=0, column=0, rowspan=1, sticky="nw")
            tk.Label(res, text=t("gpu_note"), bg=pal["bg"], fg=pal["muted"], font=self.f_tiny, anchor="w",
                     wraplength=TITLE_W - 8, justify="left").grid(row=1, column=0, rowspan=2, sticky="nw")
            label_w = 44
            res.grid_columnconfigure(1, minsize=label_w)
            cell_w = (res_w - TITLE_W - label_w - 3 * 14) // 3
            chars = max(7, min(11, cell_w // max(1, measure(self.f_num, "0"))))  # "21.5/31G", "44% 300M"
            for col, metric in enumerate(("CPU", "GPU", "RAM")):
                tk.Label(res, text=metric, bg=pal["bg"], fg=pal["muted"], font=self.f_tiny, anchor="w", pady=0, bd=0).grid(
                    row=0, column=col + 2, sticky="w", padx=(14, 0))
            self.meters_box = {}
            row = 1
            for key, show in (("pc", self.s["show_host"]), ("car", self.s["show_car"])):
                if not show:
                    continue
                tk.Label(res, text=t(key), bg=pal["bg"], fg=pal["muted"], font=self.f_small, anchor="w", pady=0, bd=0).grid(
                    row=row, column=1, sticky="w")
                cells = {}
                for col, metric in enumerate(("CPU", "GPU", "RAM")):
                    cells[metric] = MiniMeter(res, None, pal, self.f_small, self.f_num, width=cell_w,
                                              value_chars=chars, bg=pal["bg"])
                    cells[metric].grid(row=row, column=col + 2, padx=(14, 0), pady=(1, 1), sticky="w")
                self.meters_box[key] = cells
                row += 1

        net_w = page_w - net_x
        net = tk.Frame(floor, bg=pal["bg"], width=net_w, height=FLOOR_H - 8)
        net.place(x=net_x, y=10)
        net.pack_propagate(False)
        titles = tk.Frame(net, bg=pal["bg"], width=TITLE_W)
        titles.pack(side="left", fill="y")
        titles.pack_propagate(False)
        tk.Label(titles, text=t("app_network"), bg=pal["bg"], fg=pal["text"], font=self.f_caption,
                 anchor="w").pack(anchor="w")
        tk.Label(titles, text=t("history", s=self.s["graph_seconds"]), bg=pal["bg"], fg=pal["muted"],
                 font=self.f_tiny, anchor="w").pack(anchor="w")
        tk.Label(titles, text=t("net_note"), bg=pal["bg"], fg=pal["muted"], font=self.f_tiny, anchor="w",
                 wraplength=TITLE_W - 8, justify="left").pack(anchor="w", side="bottom")
        now = tk.Frame(net, bg=pal["bg"])
        now.pack(side="left", fill="y", padx=(0, 16))
        rate_chars = 12 if self.size_name != "small" else 11  # "↓ 999.9 Mb/s" fits
        self.down_label = tk.Label(now, bg=pal["bg"], fg=pal["down"], font=self.f_num_bold, anchor="w",
                                   width=rate_chars)
        self.down_label.pack(anchor="w")
        self.up_label = tk.Label(now, bg=pal["bg"], fg=pal["up"], font=self.f_num, anchor="w", width=rate_chars)
        self.up_label.pack(anchor="w")
        self.ping_label = tk.Label(now, bg=pal["bg"], fg=pal["muted"], font=self.f_tiny, anchor="w")
        self.ping_label.pack(anchor="w")
        plot = tk.Frame(net, bg=pal["bg"])
        plot.pack(side="left", fill="both", expand=True)
        self.peak_label = tk.Label(plot, bg=pal["bg"], fg=pal["muted"], font=self.f_tiny, anchor="e")
        self.peak_label.pack(fill="x")
        self.graph = tk.Canvas(plot, height=36, bg=pal["bg"], highlightthickness=0)
        self.graph.pack(fill="both", expand=True, pady=(0, 6))
        self.draw_rates((0.0, 0.0))

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
        showing = self.usb_pick if usb else self.ip_entry
        if not showing.winfo_manager():  # swap the field only when the link changes (this runs every second)
            for widget in (self.ip_caption, self.ip_entry, self.usb_pick):
                widget.pack_forget()
            if not usb:
                self.ip_caption.pack(side="left", padx=(10, 6))
            showing.pack(side="left", fill="y", padx=(0, 10))
        self.ip_entry.configure(state="disabled" if self.conn == "connecting" else "normal")
        if usb:
            label = next((f"{m or 'USB'}  {s}" for s, m in self.usb_list if s == self.s["usb_serial"]), None)
            self.usb_pick.configure(text=(label or t("no_usb")) + "  ▾", fg=pal["text"] if label else pal["muted"])
        edited = self.conn == "connected" and not usb and \
            adb.parse_address(self.ip_var.get(), self.s["port"]) != self.address
        if self.conn == "connecting":
            look = ("btn_cancel", "#1a1508", pal["warn"])
        elif self.conn == "connected" and not edited:
            look = ("btn_disconnect", pal["seg_on"], pal["text"])
        else:
            disabled = usb and not self.usb_list
            look = ("btn_connect", pal["line"] if disabled else pal["accent"], pal["muted"] if disabled else pal["accent_ink"])
        self.conn_button.set(text=t(look[0]), fill=look[1], fg=look[2])
        status = {"idle": "conn_idle", "connecting": "conn_connecting", "connected": "conn_connected"}[self.conn]
        if self.conn == "connected" and not self.car_ok:
            status = "conn_lost"
        if not getattr(self, "conn_error", None) or self.conn != "idle":
            self.conn_label.configure(text=t(status), fg=pal["text"] if self.conn == "connected" else pal["muted"])
        colour = {"idle": pal["off_dot"], "connecting": pal["warn"],
                  "connected": pal["live"] if self.car_ok else pal["warn"]}[self.conn]
        self.conn_dot.set(colour)
        model = self.model if self.conn == "connected" else (self.s["model"] if self.s["model"] != "auto" else t("model_auto"))
        self.model_chip.set(text=f"{model} ▾")
        if self.conn == "connected" and not usb:
            self.ping_label.configure(text=f"ping {self.ping:.0f} ms" if self.ping is not None else "ping –")
        else:
            self.ping_label.configure(text="")
        self.update_stage_note()

    def update_stage_note(self):
        """Right of Main: which car and whether clicks reach it."""
        if not hasattr(self, "stage_mode"):
            return
        t = self.t
        model = self.model if self.conn == "connected" else self.layout_model()
        on = self.control_var.get()
        self.stage_mode.configure(text=f"{model} · {t('mode_control') if on else t('mode_view')}",
                                  fg=self.pal["accent"] if on else self.pal["text"])
        self.stage_hint.configure(text=t("hint_control_on") if on else t("hint_control_off"))

    def update_car_data(self, car):
        data = {"tcam": car.get("tcam"), "gps": car.get("gps")}
        if car.get("tcam_info"):
            data["tcam_info"] = car["tcam_info"]
        now, counters = time.monotonic(), car.get("tbox_bytes")
        if counters:
            last, self._tbox_last = self._tbox_last, (now, counters)
            data["tbox_total"] = sum(counters)
            if last and now > last[0] and all(c >= p for c, p in zip(counters, last[1])):
                data["tbox_rate"] = tuple((c - p) / (now - last[0]) for c, p in zip(counters, last[1]))
        self.car_data.update(data)
        if self.car_panel:
            self.car_panel.update_data(**self.car_data)

    def tcam_text(self):
        """T-Box line: `T-Box 4G ▮▮▮▯ China Mobile`, or no signal."""
        tcam = self.tcam
        if not tcam:
            return ""
        if not tcam["network"]:
            return f"T-Box · {self.t('tcam_offline')}"
        level = tcam["level"]
        bars = "" if level is None else " " + "▮" * level + "▯" * (4 - level)
        if self.size_name == "small":  # the network graph needs the width
            return f"T-Box {tcam['network']}{bars}"
        return f"T-Box {tcam['network']}{bars}" + (f" · {tcam['operator']}" if tcam["operator"] else "")

    def apply_control_look(self):
        main = self.screens.get("main")
        if main:
            on = self.control_var.get()
            main.set_outline(self.pal["accent"] if on else main.bg, 2)
            main.canvas.configure(cursor="hand2" if on else "")
        self.update_stage_note()

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
        self.vehicle_stats = VehicleStats(serial)
        self.car_data, self._tbox_last = {}, None
        threading.Thread(target=self.vehicle_loop, args=(self.generation, self.vehicle_stats), daemon=True).start()
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
        self.vehicle_stats = None
        if self.car_panel:
            self.car_panel.draw()
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
        fx, fy = (event.x - main.inset) / w, (event.y - main.inset) / h
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
                       activebackground=self.pal["accent_soft"], activeforeground=self.pal["accent"], font=self.f_small)
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
        self.gear.set_active(True)

    def close_settings(self):
        if self.settings_panel:
            self.settings_panel.destroy()
            self.settings_panel = None
            self.gear.set_active(False)

    def change_setting(self, key, value):
        """Called by the settings panel. Rebuilds or restarts only what the setting affects."""
        old = self.s.get(key)
        self.s.set(key, value)
        if key == "size":  # a preset replaces the dragged size and lets the window shrink back to fit
            changed = old != value or self.s["scale"]
            self.s.set("scale", 0.0)
            self.root.geometry("")
            if changed:
                self.build()
            return
        if old == value:
            return
        if key in ("language", "theme", "animations", "show_host", "show_car", "show_vehicle", "rotate_hud", "graph_seconds", "cluster_interval"):
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
        messagebox.showinfo("Geely Car Viewer", f"adb:\n{adb.ADB}\n\nscrcpy-server:\n{server}\n\nlog / settings:\n{paths.config_dir()}",
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
        self.down_label.configure(text=f"↓ {now[0]:.1f} Mb/s", fg=pal["down"])
        self.up_label.configure(text=f"↑ {now[1]:.1f} Mb/s", fg=pal["up"])
        self.peak_label.configure(text=f"{self.t('peak')} {self.history.peak():.1f} Mb/s")
        graph = self.graph
        graph.delete("all")
        width, height = max(graph.winfo_width(), 50), max(graph.winfo_height(), 24)
        graph.create_line(0, height - 1, width, height - 1, fill=pal["line"])
        graph.create_line(0, 1, width, 1, fill=pal["line"])
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

    def vehicle_loop(self, generation, stats):
        """Car panel values in their own thread: car_service hangs while the car powers down,
        and that must not freeze the CPU/ping meters. Ends when the connection changes."""
        while generation == self.generation:
            delay = 4
            if self.s["show_vehicle"]:
                try:
                    values = stats.sample()
                except Exception as error:  # timeout while the car sleeps: back off
                    log.info("vehicle: %s", error)
                    values, delay = None, 20
                if values and generation == self.generation:
                    self.ui(lambda v=values: self.set_vehicle(v))
            time.sleep(delay)

    def set_vehicle(self, values):
        self.car_data["car"] = values
        if self.car_panel:
            self.car_panel.update_data(**self.car_data)

    def show_stats(self, host, car, ping, usb, failures):
        if usb is not None and usb != self.usb_list:
            self.usb_list = usb
            if usb and self.s["usb_serial"] not in [s for s, _ in usb]:
                self.s.set("usb_serial", usb[0][0])  # one device plugged in: pick it
            self.update_conn_ui()
        if self.conn == "connected":
            self.ping = ping if ping is not None else self.ping
            if car:
                self.tcam = car.get("tcam")
                self.update_car_data(car)
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
                text = f"{value:.0f}%" if value is not None else "–"
                if metric == "gpu" and values.get("gpu_mhz") and self.size_name != "small":
                    # % is busy time at the current clock; the clock says how hard the GPU is pushed
                    text += f" {values['gpu_mhz']}M"
                cells[metric.upper()].set(text, value / 100 if value is not None else None)
            used, total = values["ram"]
            cells["RAM"].set(human_gb(used, total), used / total if total else None)

    def quit(self):
        self.stop_streams()
        self.root.destroy()
