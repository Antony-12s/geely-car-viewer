"""Small Tk widgets and drawing helpers: one token set for cards, chips, bezels and the type scale."""
import math
import tkinter as tk
import tkinter.font as tkfont

# ---- layout tokens (every screen block uses these) ----
PAGE = 20           # outer page padding
GAP = 12            # gap between blocks, both directions
RADIUS_CARD = 12    # top-bar and car-panel cards
RADIUS_BEZEL = 18   # screen bezels
RADIUS_CHIP = 8     # buttons, chips, fields, segmented controls

THEMES = {
    "oled": dict(bg="#000000", panel="#070708", panel2="#0c0d0f", line="#1c1e23", bezel="#000000",
                 bezel_line="#16181c", track="#1a1d22"),
    "dark": dict(bg="#0d0f12", panel="#15181d", panel2="#0f1216", line="#262a31", bezel="#050607",
                 bezel_line="#2a2e35", track="#252a32"),
}
COMMON = dict(text="#eef0f3", muted="#8a909b", accent="#4cc2ff", accent_ink="#032233", accent_soft="#10202b",
              accent_line="#1d3a4f", live="#4ade80", warn="#fbbf24", bad="#f87171", down="#4cc2ff",
              up="#c4a1ff", meter="#6b7380", sw_off="#2a2f37", knob_off="#c9ced6", off_dot="#3a3f48",
              seg_on="#1f242b")


def palette(theme):
    return {**COMMON, **THEMES.get(theme, THEMES["oled"])}


def round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    r = radius
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def corner_masks(canvas, x, y, width, height, radius, fill, tag):
    """Cover the square corners of a picture so it looks rounded (drawn once, kept on top)."""
    steps = 6
    for cx, cy, sx, sy in ((x, y, 1, 1), (x + width, y, -1, 1), (x, y + height, 1, -1), (x + width, y + height, -1, -1)):
        points = [cx, cy]
        for i in range(steps + 1):
            angle = math.pi / 2 * i / steps
            points += [cx + sx * radius * (1 - math.cos(angle)), cy + sy * radius * (1 - math.sin(angle))]
        canvas.create_polygon(points, fill=fill, outline="", tags=tag)


def measure(font, text):
    return tkfont.Font(font=font).measure(text)


def baseline_text(canvas, x, baseline, text, font, anchor="w", **kwargs):
    """Draw text so its baseline sits at `baseline`; lets a unit share the value's baseline."""
    top = baseline - tkfont.Font(font=font).metrics("ascent")
    where = {"w": "nw", "e": "ne", "c": "n"}[anchor]
    return canvas.create_text(x, top, text=text, font=font, anchor=where, **kwargs)


def draw_icon(canvas, kind, x, y, size, colour, width=1.5, tags=None):
    """Small line icons drawn with lines and ovals (no emoji, no image files)."""
    s, w, t = size, width, dict(tags=tags) if tags else {}
    if kind == "gauge":
        canvas.create_arc(x, y + s * 0.2, x + s, y + s * 1.8, start=0, extent=180, style="arc", outline=colour,
                          width=w, **t)
        canvas.create_line(x + s * 0.5, y + s * 0.8, x + s * 0.8, y + s * 0.35, fill=colour, width=w, **t)
    elif kind == "tire":
        canvas.create_oval(x, y, x + s, y + s, outline=colour, width=w, **t)
        canvas.create_oval(x + s * 0.34, y + s * 0.34, x + s * 0.66, y + s * 0.66, outline=colour, width=w, **t)
    elif kind == "thermo":
        canvas.create_line(x + s * 0.5, y, x + s * 0.5, y + s * 0.62, fill=colour, width=w, **t)
        canvas.create_oval(x + s * 0.28, y + s * 0.5, x + s * 0.72, y + s, outline=colour, width=w, **t)
    elif kind == "signal":
        for i in range(4):
            top = y + s * (0.7 - 0.2 * i)
            canvas.create_line(x + i * s * 0.28 + 1, y + s, x + i * s * 0.28 + 1, top, fill=colour, width=max(w, 2),
                               **t)
    elif kind == "gps":
        canvas.create_oval(x + s * 0.2, y, x + s * 0.8, y + s * 0.6, outline=colour, width=w, **t)
        canvas.create_line(x + s * 0.5, y + s * 0.6, x + s * 0.5, y + s, fill=colour, width=w, **t)
    elif kind == "info":
        canvas.create_oval(x, y, x + s, y + s, outline=colour, width=w, **t)
        canvas.create_line(x + s * 0.5, y + s * 0.45, x + s * 0.5, y + s * 0.78, fill=colour, width=w, **t)
        canvas.create_oval(x + s * 0.44, y + s * 0.2, x + s * 0.56, y + s * 0.32, fill=colour, outline="", **t)
    elif kind == "gear":
        c, ring, tooth = x + s / 2, s * 0.30, s * 0.47
        canvas.create_oval(c - ring, c - ring, c + ring, c + ring, outline=colour, width=w, **t)
        for angle in range(0, 360, 45):
            a = math.radians(angle)
            canvas.create_line(c + math.cos(a) * ring, c + math.sin(a) * ring,
                               c + math.cos(a) * tooth, c + math.sin(a) * tooth,
                               fill=colour, width=w + 1, capstyle="round", **t)
    elif kind == "battery":
        round_rect(canvas, x, y + s * 0.2, x + s * 0.86, y + s * 0.8, 2, fill="", outline=colour, width=w, **t)
        canvas.create_rectangle(x + s * 0.88, y + s * 0.4, x + s, y + s * 0.6, fill=colour, outline="", **t)
        canvas.create_rectangle(x + s * 0.18, y + s * 0.36, x + s * 0.6, y + s * 0.64, fill=colour, outline="", **t)
    elif kind == "screen":
        round_rect(canvas, x, y, x + s, y + s * 0.7, 3, fill="", outline=colour, width=w, **t)
        canvas.create_line(x + s * 0.5, y + s * 0.7, x + s * 0.5, y + s, fill=colour, width=w, **t)
        canvas.create_line(x + s * 0.3, y + s, x + s * 0.7, y + s, fill=colour, width=w, capstyle="round", **t)
    elif kind == "pause":
        bar = s * 0.22
        canvas.create_rectangle(x + s * 0.2, y, x + s * 0.2 + bar, y + s, fill=colour, outline="", **t)
        canvas.create_rectangle(x + s * 0.6, y, x + s * 0.6 + bar, y + s, fill=colour, outline="", **t)


class Card(tk.Frame):
    """Rounded card on the page background. A canvas paints the rounded fill and 1 px border; content goes in
    `self.body`, inset so its square corners stay inside the curve (radius 12)."""

    def __init__(self, parent, pal, bg, width, height, radius=RADIUS_CARD):
        super().__init__(parent, bg=bg, width=width, height=height)
        self.pal, self.radius = pal, radius
        self.pack_propagate(False)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=pal["panel2"])
        self.body.place(x=14, y=12, relwidth=1, relheight=1, width=-28, height=-24)
        self.canvas.bind("<Configure>", self._paint)

    def _paint(self, _event=None):
        canvas, pal = self.canvas, self.pal
        canvas.delete("all")
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w > 2 and h > 2:
            round_rect(canvas, 0.5, 0.5, w - 0.5, h - 0.5, self.radius, fill=pal["panel2"], outline=pal["line"],
                       width=1)


class Chip(tk.Canvas):
    """Rounded button or chip: text on a filled rounded rectangle, sized to its text. Bind clicks yourself."""

    def __init__(self, parent, text, font, bg, fill, fg, padx=12, height=28, radius=RADIUS_CHIP):
        super().__init__(parent, width=20, height=height, bg=bg, highlightthickness=0, cursor="hand2")
        self.font, self.padx, self.h, self.radius = font, padx, height, radius
        self.set(text, fill, fg)

    def set(self, text=None, fill=None, fg=None):
        if text is not None:
            self.text = text
        if fill is not None:
            self.fill_colour = fill
        if fg is not None:
            self.fg_colour = fg
        width = measure(self.font, self.text) + 2 * self.padx
        self.configure(width=width)
        self.delete("all")
        round_rect(self, 0, 0, width, self.h, self.radius, fill=self.fill_colour, outline="")
        self.create_text(width / 2, self.h / 2, text=self.text, font=self.font, fill=self.fg_colour)


class IconButton(tk.Canvas):
    """Square rounded icon button (the settings gear). Active = accent fill."""

    def __init__(self, parent, pal, bg, kind, command, size=36):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, cursor="hand2")
        self.pal, self.kind, self.command, self.size, self.active = pal, kind, command, size, False
        self.bind("<Button-1>", lambda _e: self.command())
        self.draw()

    def set_active(self, on):
        self.active = on
        self.draw()

    def draw(self):
        pal, s = self.pal, self.size
        self.delete("all")
        on = self.active
        round_rect(self, 0.5, 0.5, s - 0.5, s - 0.5, RADIUS_CHIP, fill=pal["accent"] if on else pal["panel2"],
                   outline="" if on else pal["line"], width=1)
        draw_icon(self, self.kind, s * 0.27, s * 0.27, s * 0.46, pal["accent_ink"] if on else pal["muted"], width=1.6)


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


class Segmented(tk.Canvas):
    """A row of options, one selected, on a recessed rounded track. options: [(value, label)]; command(value)."""

    def __init__(self, parent, options, value, pal, command, font, bg=None, fill=None, height=24):
        self.pal, self.command, self.options, self.font, self.value = pal, command, options, font, value
        self.track, self.h, pad = fill or pal["bg"], height, 10
        self.spans, x = [], 2
        for option, label in options:
            width = measure(font, label) + 2 * pad
            self.spans.append((option, label, x, x + width))
            x += width
        self.total = int(x + 2)
        super().__init__(parent, width=self.total, height=height, bg=bg or pal["panel2"], highlightthickness=0,
                         cursor="hand2")
        self.bind("<Button-1>", self._click)
        self.draw()

    def _click(self, event):
        for option, _label, x1, x2 in self.spans:
            if x1 <= event.x < x2:
                self.select(option)
                self.command(option)
                return

    def select(self, value):
        self.value = value
        self.draw()

    def draw(self):
        pal = self.pal
        self.delete("all")
        round_rect(self, 0, 0, self.total, self.h, RADIUS_CHIP, fill=self.track, outline="")
        for option, label, x1, x2 in self.spans:
            on = option == self.value
            if on:
                round_rect(self, x1, 2, x2, self.h - 2, RADIUS_CHIP - 2, fill=pal["seg_on"], outline="")
            self.create_text((x1 + x2) / 2, self.h / 2, text=label, font=self.font,
                             fill=pal["text"] if on else pal["muted"])


class MiniMeter(tk.Frame):
    """Label and right-aligned value on one line, thin bar below. `width` is the fixed cell width,
    so the bars of the PC row and the car row line up."""

    def __init__(self, parent, label, pal, font, num_font, width=110, value_chars=9):
        super().__init__(parent, bg=pal["panel2"])
        self.pal, self.width = pal, width
        top = tk.Frame(self, bg=pal["panel2"])
        top.pack(fill="x")
        tk.Label(top, text=label, bg=pal["panel2"], fg=pal["muted"], font=font).pack(side="left")
        self.value = tk.Label(top, text="–", bg=pal["panel2"], fg=pal["text"], font=num_font, anchor="e",
                              width=value_chars)  # fixed column: the PC and car bars line up
        self.value.pack(side="right")
        self.bar = tk.Canvas(self, width=width, height=3, bg=pal["track"], highlightthickness=0)
        self.bar.pack(pady=(3, 0), anchor="w")

    def set(self, text, fraction):
        self.value.configure(text=text)
        self.bar.delete("all")
        if fraction is not None:
            fraction = max(0.0, min(1.0, fraction))
            colour = self.pal["warn"] if fraction > 0.7 else self.pal["meter"]
            self.bar.create_rectangle(0, 0, int(self.width * fraction), 3, fill=colour, outline="")


class Dot(tk.Canvas):
    def __init__(self, parent, pal, bg, size=8):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0)
        self.item = self.create_oval(0, 0, size, size, fill=pal["off_dot"], outline="")

    def set(self, colour):
        self.itemconfigure(self.item, fill=colour)
