"""Small Tk widgets drawn to match the mockup: switch, segmented picker, mini meter, status dot."""
import tkinter as tk

THEMES = {
    "oled": dict(bg="#000000", panel="#070708", panel2="#0c0d0f", line="#1c1e23", bezel="#000000",
                 bezel_line="#16181c", track="#1a1d22"),
    "dark": dict(bg="#0d0f12", panel="#15181d", panel2="#0f1216", line="#262a31", bezel="#050607",
                 bezel_line="#2a2e35", track="#252a32"),
}
COMMON = dict(text="#eef0f3", muted="#8a909b", accent="#4cc2ff", accent_ink="#032233", live="#4ade80",
              warn="#fbbf24", bad="#f87171", down="#4cc2ff", up="#c4a1ff", sw_off="#2a2f37",
              knob_off="#c9ced6", off_dot="#3a3f48", seg_on="#1f242b")


def palette(theme):
    return {**COMMON, **THEMES.get(theme, THEMES["oled"])}


def round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    r = radius
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def corner_masks(canvas, x, y, width, height, radius, fill, tag):
    """Cover the square corners of a picture so it looks rounded (drawn once, kept on top)."""
    import math
    steps = 6
    for cx, cy, sx, sy in ((x, y, 1, 1), (x + width, y, -1, 1), (x, y + height, 1, -1), (x + width, y + height, -1, -1)):
        points = [cx, cy]
        for i in range(steps + 1):
            angle = math.pi / 2 * i / steps
            points += [cx + sx * radius * (1 - math.cos(angle)), cy + sy * radius * (1 - math.sin(angle))]
        canvas.create_polygon(points, fill=fill, outline="", tags=tag)


class Switch(tk.Canvas):
    """iOS-style switch bound to a BooleanVar; command(value) runs on user clicks only."""

    def __init__(self, parent, variable, pal, command=None, bg=None):
        super().__init__(parent, width=36, height=21, bg=bg or pal["panel"], highlightthickness=0, cursor="hand2")
        self.variable, self.pal, self.command = variable, pal, command
        self.bind("<Button-1>", self._click)
        variable.trace_add("write", lambda *_: self.draw())
        self.draw()

    def _click(self, _event):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command(self.variable.get())

    def draw(self):
        self.delete("all")
        on = self.variable.get()
        round_rect(self, 0, 0, 36, 21, 10, fill=self.pal["accent"] if on else self.pal["sw_off"], outline="")
        x = 18 if on else 3
        self.create_oval(x, 3, x + 15, 18, fill="#ffffff" if on else self.pal["knob_off"], outline="")


class Segmented(tk.Frame):
    """A row of options, one selected. options: [(value, label)]; command(value) on click."""

    def __init__(self, parent, options, value, pal, command, font):
        super().__init__(parent, bg=pal["panel2"], highlightthickness=1, highlightbackground=pal["line"], padx=2, pady=2)
        self.pal, self.command, self.labels = pal, command, {}
        for option, label in options:
            widget = tk.Label(self, text=label, font=font, padx=9, pady=1, cursor="hand2")
            widget.pack(side="left")
            widget.bind("<Button-1>", lambda _e, o=option: self._pick(o))
            self.labels[option] = widget
        self.select(value)

    def _pick(self, option):
        self.select(option)
        self.command(option)

    def select(self, value):
        for option, widget in self.labels.items():
            on = option == value
            widget.configure(bg=self.pal["seg_on"] if on else self.pal["panel2"],
                             fg=self.pal["text"] if on else self.pal["muted"])


class MiniMeter(tk.Frame):
    """Label + value on one line, thin bar below."""

    def __init__(self, parent, label, pal, font, num_font, width=74):
        super().__init__(parent, bg=pal["panel2"])
        self.pal, self.width = pal, width
        top = tk.Frame(self, bg=pal["panel2"])
        top.pack(fill="x")
        tk.Label(top, text=label, bg=pal["panel2"], fg=pal["muted"], font=font).pack(side="left")
        self.value = tk.Label(top, text="–", bg=pal["panel2"], fg=pal["text"], font=num_font)
        self.value.pack(side="right")
        self.bar = tk.Canvas(self, width=width, height=4, bg=pal["track"], highlightthickness=0)
        self.bar.pack(pady=(3, 0))

    def set(self, text, fraction):
        self.value.configure(text=text)
        self.bar.delete("all")
        if fraction is not None:
            fraction = max(0.0, min(1.0, fraction))
            colour = self.pal["warn"] if fraction > 0.7 else self.pal["accent"]
            self.bar.create_rectangle(0, 0, int(self.width * fraction), 4, fill=colour, outline="")


class Dot(tk.Canvas):
    def __init__(self, parent, pal, bg, size=8):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0)
        self.item = self.create_oval(0, 0, size, size, fill=pal["off_dot"], outline="")

    def set(self, colour):
        self.itemconfigure(self.item, fill=colour)
