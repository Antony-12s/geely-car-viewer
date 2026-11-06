"""Settings popover under the gear button. Every change saves at once (App.change_setting)."""
import tkinter as tk

from . import __version__
from .widgets import Segmented, Switch


class SettingsPanel(tk.Frame):
    def __init__(self, app):
        pal, t = app.pal, app.t
        super().__init__(app.root, bg="#0b0c0e", highlightthickness=1, highlightbackground="#23262c", padx=20, pady=16)
        self.app = app
        self.place(relx=1.0, x=-16, y=90, anchor="ne")
        self.lift()
        head = tk.Frame(self, bg=self["bg"])
        head.pack(fill="x")
        tk.Label(head, text=t("settings"), bg=self["bg"], fg=pal["text"], font=app.f_title).pack(side="left")
        tk.Label(head, text=t("saved_auto"), bg=self["bg"], fg=pal["muted"], font=app.f_small).pack(side="left", padx=10)
        close = tk.Label(head, text="✕", bg=self["bg"], fg=pal["muted"], font=app.f_body, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: app.close_settings())

        cols = tk.Frame(self, bg=self["bg"])
        cols.pack(fill="x", pady=(6, 0))
        left, right = tk.Frame(cols, bg=self["bg"]), tk.Frame(cols, bg=self["bg"])
        left.pack(side="left", fill="y", anchor="n")
        tk.Frame(cols, bg=self["bg"], width=28).pack(side="left")
        right.pack(side="left", fill="y", anchor="n")

        s = app.s
        self.group(left, t("g_general"))
        self.pick(left, t("s_language"), "language", [("th", "ไทย"), ("en", "English")])
        self.pick(left, t("s_theme"), "theme", [("oled", t("theme_oled")), ("dark", t("theme_dark"))])
        self.pick(left, t("s_size"), "size", [("auto", t("size_auto")), ("small", t("size_small")), ("medium", t("size_medium")), ("large", t("size_large"))])
        self.switch(left, t("s_topmost"), "topmost", t("s_topmost_sub"))
        self.group(left, t("g_connection"))
        self.port(left, t("s_port"))
        self.switch(left, t("s_auto_connect"), "auto_connect", t("s_auto_connect_sub"))
        self.switch(left, t("s_auto_reconnect"), "auto_reconnect")

        self.group(right, t("g_video"))
        self.pick(right, t("s_fps"), "max_fps", [(15, "15"), (30, "30"), (60, "60")], t("s_fps_sub"))
        self.pick(right, t("s_cluster_interval"), "cluster_interval",
                  [(0.5, "0.5"), (1.0, "1"), (2.0, "2"), (5.0, t("seconds", s=5))])
        if app.layout_model() == "EX5":  # EX2 has no HUD to rotate
            self.switch(right, t("s_rotate"), "rotate_hud", t("s_rotate_sub"))
        self.group(right, t("g_topbar"))
        self.pick(right, t("s_graph"), "graph_seconds", [(30, "30"), (60, "60"), (120, t("seconds", s=120))])
        self.switch(right, t("s_show_host"), "show_host", "CPU / GPU / RAM")
        self.switch(right, t("s_show_car"), "show_car", t("s_show_car_sub"))
        self.switch(right, t("s_show_vehicle"), "show_vehicle", t("s_show_vehicle_sub"))

        tk.Frame(self, bg=pal["line"], height=1).pack(fill="x", pady=(12, 10))
        foot = tk.Frame(self, bg=self["bg"])
        foot.pack(fill="x")
        tk.Label(foot, text=f"EX5 Viewer {__version__}", bg=self["bg"], fg=pal["muted"], font=app.f_small).pack(side="left")
        for text, command in ((t("open_log"), app.open_log), (t("tool_paths"), app.show_paths)):
            self.link(foot, text, command).pack(side="left", padx=(14, 0))
        self.link(foot, t("reset"), app.reset_settings).pack(side="right")
        del s

    def group(self, parent, title):
        tk.Label(parent, text=title, bg=self["bg"], fg=self.app.pal["accent"], font=self.app.f_bold).pack(anchor="w", pady=(10, 2))

    def row(self, parent, label, sub=None):
        pal = self.app.pal
        row = tk.Frame(parent, bg=self["bg"], width=330, height=46 if sub else 34)
        row.pack(fill="x")
        row.pack_propagate(False)
        text = tk.Frame(row, bg=self["bg"])
        text.pack(side="left", fill="y")
        tk.Label(text, text=label, bg=self["bg"], fg=pal["text"], font=self.app.f_body).pack(anchor="w", expand=not sub)
        if sub:
            tk.Label(text, text=sub, bg=self["bg"], fg=pal["muted"], font=self.app.f_tiny).pack(anchor="w")
        tk.Frame(parent, bg="#16181c", height=1).pack(fill="x")
        return row

    def pick(self, parent, label, key, options, sub=None):
        row = self.row(parent, label, sub)
        Segmented(row, options, self.app.s[key], self.app.pal, lambda v: self.app.change_setting(key, v),
                  self.app.f_tiny).pack(side="right")

    def switch(self, parent, label, key, sub=None):
        row = self.row(parent, label, sub)
        var = tk.BooleanVar(value=self.app.s[key])
        Switch(row, var, self.app.pal, lambda v: self.app.change_setting(key, v), bg=self["bg"]).pack(side="right")

    def port(self, parent, label):
        pal = self.app.pal
        row = self.row(parent, label)
        var = tk.StringVar(value=str(self.app.s["port"]))
        entry = tk.Entry(row, textvariable=var, width=7, bg=pal["panel2"], fg=pal["text"], relief="flat",
                         insertbackground=pal["accent"], font=self.app.f_num, justify="center",
                         highlightthickness=1, highlightbackground=pal["line"], highlightcolor=pal["accent"])
        entry.pack(side="right", ipady=3)

        def save(*_):
            text = var.get().strip()
            ok = text.isdigit() and 0 < int(text) < 65536
            entry.configure(highlightbackground=pal["line"] if ok else pal["bad"])
            if ok:
                self.app.s.set("port", int(text))

        var.trace_add("write", save)

    def link(self, parent, text, command):
        label = tk.Label(parent, text=text, bg=self["bg"], fg=self.app.pal["text"], font=self.app.f_small, cursor="hand2")
        label.bind("<Button-1>", lambda _e: command())
        return label
