"""Pop-out windows: one stream screen detached into its own Toplevel.

While a screen is popped out it renders ONLY here: the main window keeps the screen's slot (same size, so the
layout does not move) with an "opened in a window" placeholder, and App.refresh() sends each decoded frame to
App.view(name), which is this window's Screen. The stream decodes once, at App.view_size(name) = this window's
picture size. Closing the window (or the dock button, Escape, a disconnect, quitting) calls App.dock(name).
"""
import tkinter as tk

from .widgets import Chip

SOURCE = {"main": (2560, 1600), "hud": (800, 480), "cluster": (1920, 532)}  # car display sizes (aspect + cap)
PAD = 10          # window padding around the picture
HEAD = 34         # title / status row above the picture
RESIZE_MS = 120   # settle time before a dragged window re-fits its picture


def even(value):
    return max(2, int(value) // 2 * 2)


def fit(source, width, height):
    """Largest even size with the source aspect inside width x height."""
    sw, sh = source
    scale = min(width / sw, height / sh)
    return even(sw * scale), even(sh * scale)


class PopoutWindow:
    def __init__(self, app, name):
        self.app, self.name = app, name
        self.screen, self._job = None, None
        self.top = tk.Toplevel(app.root)
        self.top.protocol("WM_DELETE_WINDOW", lambda: app.dock(name))
        self.top.bind("<Escape>", lambda _e: app.dock(name))
        size = self.initial_size()
        self.build(size)
        from .ui import INSET
        self.top.geometry(f"{size[0] + 2 * INSET + 2 * PAD}x{size[1] + 2 * INSET + 2 * PAD + HEAD}")
        self.top.minsize(240, 160)
        self.top.bind("<Configure>", self.on_configure)

    def initial_size(self):
        """The car's own resolution when it fits in 60% of the screen, else the largest fit (never upscaled)."""
        source = SOURCE[self.name]
        screen_w, screen_h = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
        return fit(source, min(source[0], screen_w * 0.6), min(source[1], screen_h * 0.6))

    def build(self, size):
        from .ui import Screen
        app, pal, t = self.app, self.app.pal, self.app.t
        self.top.configure(bg=pal["bg"])
        self.top.title(f"{t(self.name)} · Geely Car Viewer")
        head = tk.Frame(self.top, bg=pal["bg"], height=HEAD)
        head.pack(side="top", fill="x", padx=PAD, pady=(PAD, 0))
        tk.Label(head, text=t(self.name), bg=pal["bg"], fg=pal["text"], font=app.f_caption).pack(side="left")
        dock = Chip(head, t("dock"), app.f_small, bg=pal["bg"], fill=pal["accent_soft"], fg=pal["accent"], padx=10,
                    height=24)
        dock.pack(side="right")
        dock.bind("<Button-1>", lambda _e: app.dock(self.name))
        self.dock_button = dock
        status = tk.Frame(head, bg=pal["bg"])
        status.pack(side="right", padx=(0, 12))
        self.screen = Screen(app, self.top, self.name, size, pal["bg"])
        app.add_stream_status(self.screen, status, pal["bg"], fps=self.name != "cluster")
        self.screen.canvas.pack(side="top", expand=True, padx=PAD, pady=(0, PAD))
        if self.name == "main":  # Control Main works on the popped picture too (on_touch checks the switch)
            for event in ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>"):
                self.screen.canvas.bind(event, app.on_touch)

    def restyle(self):
        """App rebuilt (theme, language, size): rebuild this window's widgets, keeping the picture and state."""
        old = self.screen
        for child in self.top.winfo_children():
            child.destroy()
        self.build(old.size)
        self.screen.state, self.screen.last_frame_at = old.state, old.last_frame_at
        if old.image is not None and self.app.conn == "connected":
            self.screen.show(old.image)
        self.app.paint_state(self.screen)

    def on_configure(self, event):
        if event.widget is not self.top:
            return
        if self._job:
            self.top.after_cancel(self._job)
        self._job = self.top.after(RESIZE_MS, self.refit)

    def refit(self):
        """Window dragged: the picture follows; the stream decodes at the new size from its next frame on."""
        from .ui import INSET
        self._job = None
        width = self.top.winfo_width() - 2 * PAD - 2 * INSET
        height = self.top.winfo_height() - 2 * PAD - 2 * INSET - HEAD
        if width < 40 or height < 24:
            return
        size = fit(SOURCE[self.name], width, height)
        if abs(size[0] - self.screen.size[0]) > 2 or abs(size[1] - self.screen.size[1]) > 2:
            self.screen.resize(size)

    def destroy(self):
        if self._job:
            try:
                self.top.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        try:
            self.top.destroy()
        except tk.TclError:
            pass
