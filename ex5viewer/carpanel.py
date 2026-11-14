"""Car status rail to the right of Main (design A "OLED cinema"): battery, range, gear/speed, tires, T-Box/GPS.
Plus the T-Box info dialog (SIM numbers masked until asked)."""
import tkinter as tk
import webbrowser

from .vehicle import compass
from .stats import carrier
from .widgets import NUMBER_MS, PANEL_MS, RADIUS_CHIP, animate, baseline_text, draw_icon, lerp, measure, round_rect

TIRE_LOW, TIRE_HIGH, TIRE_SPREAD = 30.0, 42.0, 3.0  # psi: warn outside the band or when one tire is off
PAD = 14  # inner padding of a card


def fmt(value, pattern, missing="–"):
    return pattern.format(value) if value is not None else missing


def human_bytes(count):
    for unit, size in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if count >= size:
            return f"{count / size:.1f} {unit}"
    return f"{count:.0f} B"


ANIMATED = ("soc", "range_km", "speed_kmh", "temp_c", "charge_kw", "odometer")


def interpolate(start, end, t):
    """Car values between two samples; anything not numeric on both sides jumps to the new value."""
    out = dict(end)
    for key in ANIMATED:
        a, b = start.get(key), end.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out[key] = lerp(a, b, t)
    if start.get("tires") and end.get("tires"):
        out["tires"] = {wheel: lerp(start["tires"][wheel], value, t)
                        if isinstance(start["tires"].get(wheel), (int, float)) and isinstance(value, (int, float))
                        else value for wheel, value in end["tires"].items()}
    return out


class CarPanel(tk.Canvas):
    """Car data in a vertical rail beside the Main stage: one open column with a hairline on its left.
    Top to bottom: header | battery | range | gear + speed | tires | T-Box + GPS. Spare height is shared out
    between the sections, so the rail fills Main's height at every window size."""

    def __init__(self, app, parent, width, height):
        super().__init__(parent, width=width, height=height, bg=app.pal["bg"], highlightthickness=0)
        self.app, self.w, self.h = app, width, height
        self.data, self.shown = {}, None  # shown: interpolated car values while numbers animate
        self.tag_bind("map", "<Button-1>", lambda _e: self.open_map())
        self.tag_bind("info", "<Button-1>", lambda _e: TboxInfo(self.app, self.data.get("tcam_info")))
        for tag in ("map", "info"):
            self.tag_bind(tag, "<Enter>", lambda _e: self.configure(cursor="hand2"))
            self.tag_bind(tag, "<Leave>", lambda _e: self.configure(cursor=""))
        self.draw()

    def update_data(self, **data):
        """New values glide from what is on screen to the new numbers (battery fill, speed, range, tires...)."""
        before = self.shown or self.data.get("car")
        self.data.update(data)
        after = self.data.get("car")
        if not (before and after) or before is after or "car" not in data:
            self.draw()
            return

        def step(e):
            self.shown = interpolate(before, after, e)
            self.draw()

        def done():
            self.shown = None
            self.draw()

        animate(self, "numbers", NUMBER_MS, step, done)

    def open_map(self):
        gps = self.data.get("gps")
        if gps:
            webbrowser.open(f"https://www.google.com/maps?q={gps['lat']:.6f},{gps['lon']:.6f}")

    # ---------- drawing ----------
    # natural heights of the rail sections (header, battery, range, gear, tires, T-Box); spare height goes
    # into the gaps between them. COMPACT drops the sub-lines (odometer, outside temperature) on a short rail.
    SECTIONS = (26, 58, 64, 66, 60, 76)
    COMPACT = (24, 56, 46, 48, 58, 76)

    def compact(self):
        return sum(self.SECTIONS) + 2 * PAD > self.h

    def rows(self):
        """Top y of each section, spread over the rail height."""
        sections = self.COMPACT if self.compact() else self.SECTIONS
        gaps = len(sections) - 1
        spare = max(0, self.h - 2 * PAD - sum(sections))
        gap = min(spare / gaps, 40)
        y, tops = PAD, []
        for height in sections:
            tops.append(round(y))
            y += height + gap
        return dict(zip(("head", "battery", "range", "gear", "tires", "tbox"), tops)), gap

    def value(self, x, baseline, number, unit, colour):
        app, pal = self.app, self.app.pal
        item = baseline_text(self, x, baseline, number, app.f_value, fill=colour)
        if unit:
            baseline_text(self, self.bbox(item)[2] + 4, baseline, unit, app.f_small, fill=pal["muted"])
        return item

    def rule(self, y):
        self.create_line(PAD, y, self.w - PAD, y, fill=self.app.pal["line"])

    def draw(self):
        self.delete("all")
        app, pal, t = self.app, self.app.pal, self.app.t
        small = app.size_name == "small"
        connected = app.conn == "connected"
        car = (self.shown or self.data.get("car") or {}) if connected else {}
        r, gap = self.rows()
        compact = self.compact()
        w, x0 = self.w, PAD
        inner = w - 2 * PAD
        self.create_line(0.5, 0, 0.5, self.h, fill=pal["line"])
        head = self.create_text(x0, r["head"] + 8, text=t("c_status"), anchor="w", fill=pal["text"],
                                font=app.f_caption)
        self.create_text(self.bbox(head)[2] + 8, r["head"] + 8, text=app.layout_model(), anchor="w",
                         fill=pal["muted"], font=app.f_tiny)

        # battery: label, big value, fill bar across the rail
        y = r["battery"]
        self.create_text(x0, y + 6, text=t("c_battery"), anchor="w", fill=pal["muted"], font=app.f_tiny)
        soc = car.get("soc")
        colour = pal["muted"] if soc is None else pal["bad"] if soc < 20 else pal["warn"] if soc < 40 else pal["live"]
        self.value(x0, y + 38, fmt(soc, "{:.0f}"), "%" if soc is not None else "", colour)
        self.create_rectangle(x0, y + 47, x0 + inner, y + 51, fill=pal["track"], outline="")
        if soc is not None:
            self.create_rectangle(x0, y + 47, x0 + inner * max(0, min(100, soc)) / 100, y + 51, fill=colour,
                                  outline="")

        # range + odometer / charging
        y = r["range"]
        self.create_text(x0, y + 6, text=t("c_range_title"), anchor="w", fill=pal["muted"], font=app.f_tiny)
        rng = car.get("range_km")
        self.value(x0, y + 38, fmt(rng, "{:.0f}"), "km" if rng is not None else "", pal["text"])
        charging = car.get("plugged")
        odo = car.get("odometer")
        sub = (t("c_charging", kw=f"{car.get('charge_kw') or 0:.1f}") if charging
               else t("c_odo", km=f"{odo:,.0f}") if odo is not None else "–")
        if not compact:
            self.create_text(x0, y + 54, text=sub, anchor="w", fill=pal["live"] if charging else pal["muted"],
                             font=app.f_tiny, width=inner)
        elif charging:  # short rail: charging still shows, on the title row
            self.create_text(x0 + inner, y + 6, text=f"⚡ {car.get('charge_kw') or 0:.1f} kW", anchor="e",
                             fill=pal["live"], font=app.f_tiny)

        # gear box + speed, outside temperature
        y = r["gear"]
        self.create_text(x0, y + 6, text=t("c_gear_speed"), anchor="w", fill=pal["muted"], font=app.f_tiny)
        gear = car.get("gear")
        driving = gear is not None and gear != "P"
        box = 26 if small else 30
        gy = y + 42 - box
        round_rect(self, x0 + 0.5, gy + 0.5, x0 + box - 0.5, gy + box - 0.5, 4, fill=pal["bg"], outline=pal["line"])
        self.create_text(x0 + box / 2, gy + box / 2, text=gear or "–", fill=pal["accent"] if driving else pal["text"],
                         font=app.f_value)
        self.value(x0 + box + 10, y + 38, fmt(car.get("speed_kmh"), "{:.0f}"), "km/h", pal["text"])
        temp = car.get("temp_c")
        if not compact:
            self.create_text(x0, y + 56, text=t("c_outside", t=f"{temp:.0f}") if temp is not None else "–",
                             anchor="w", fill=pal["muted"], font=app.f_tiny, width=inner)

        # tires: front pair, rear pair
        y = r["tires"]
        self.rule(round(y - min(gap, 12) / 2) - 2)
        title = self.create_text(x0, y + 8, text=t("c_tires"), anchor="w", fill=pal["text"], font=app.f_caption)
        self.create_text(self.bbox(title)[2] + 8, y + 8, text="psi", anchor="w", fill=pal["muted"], font=app.f_tiny)
        tires = car.get("tires") or {}
        known = [v for v in tires.values() if v is not None]
        average = sum(known) / len(known) if known else None
        axles = ((t("c_front"), ("fl", "fr")), (t("c_rear"), ("rl", "rr")))
        label_w = max(measure(app.f_tiny, label) for label, _pair in axles) + 8
        for index, (label, pair) in enumerate(axles):
            ly = y + 28 + index * 18
            self.create_text(x0, ly, text=label, anchor="w", fill=pal["muted"], font=app.f_tiny)
            x = x0 + label_w
            for key in pair:
                value = tires.get(key)
                bad = value is not None and (value < TIRE_LOW or value > TIRE_HIGH or abs(value - average) > TIRE_SPREAD)
                item = self.create_text(x, ly, text=fmt(value, "{:.1f}"), anchor="w",
                                        fill=pal["warn"] if bad else pal["text"], font=app.f_num)
                x = self.bbox(item)[2] + 10
        y = r["tbox"]
        self.rule(round(y - min(gap, 12) / 2) - 2)
        self._tbox(x0, inner, y, connected, small)

    def _tbox(self, x, width, y, connected, small):
        """T-Box: network + signal | GPS + map link | data through the T-Box. The info link sits on the title row."""
        app, pal, t = self.app, self.app.pal, self.app.t
        tcam = self.data.get("tcam") if connected else None
        title = self.create_text(x, y + 8, text="T-Box", anchor="w", fill=pal["text"], font=app.f_caption)
        if tcam and tcam.get("network"):
            self.create_text(self.bbox(title)[2] + 8, y + 8, text=tcam["network"], anchor="w", fill=pal["live"],
                             font=app.f_tiny)
        info = self.data.get("tcam_info")
        if connected and info:
            link = self.create_text(x + width, y + 8, text=t("c_tbox_info"), anchor="e", fill=pal["accent"],
                                    font=app.f_tiny, tags="info")
            draw_icon(self, "info", self.bbox(link)[0] - 15, y + 2, 11, pal["accent"], width=1.2, tags="info")
        line2, line3, line4 = y + 28, y + 46, y + 64
        level = (tcam or {}).get("level") or 0
        for i in range(4):  # signal bars, growing left to right
            on = tcam and tcam.get("network") and i < level
            height = 4 + 2 * i
            self.create_rectangle(x + i * 4, line2 + 5 - height, x + i * 4 + 2, line2 + 5,
                                  fill=pal["live"] if on else pal["track"], outline="")
        if not tcam:
            net = "–"
        elif not tcam.get("network"):
            net = t("tcam_offline")
        else:
            # the eSIM's IMSI names the real carrier; the status log says China Mobile on Thai cars
            operator = carrier((self.data.get("tcam_info") or {}).get("imsi")) or tcam.get("operator")
            net = f"{level}/4" + (f"  {operator}" if operator else "")
        self.create_text(x + 22, line2, text=net, anchor="w", fill=pal["text"], font=app.f_small, width=width - 22)
        rate, total = (self.data.get("tbox_rate"), self.data.get("tbox_total")) if connected else (None, None)
        gps = self.data.get("gps") if connected else None
        if gps:
            angle = gps["heading"]
            car = self.data.get("car") or {}
            moving = gps.get("speed", 0) > 0.5 or (car.get("speed_kmh") or 0) > 2
            # heading is 0 while parked: say "parked" instead of a meaningless "0° N"
            where = f"{angle:.0f}° {compass(angle)}" if moving else t("c_parked")
            item = self.create_text(x, line3, text=f"GPS · {where}", anchor="w", fill=pal["muted"], font=app.f_tiny)
            label = self.create_text(self.bbox(item)[2] + 14, line3, text=t("c_map") + " ↗", anchor="w",
                                     fill=pal["accent"], font=app.f_tiny, tags="map")
            x1, y1, x2, y2 = self.bbox(label)
            if x2 + 6 > x + width:  # narrow rail: the map link goes under the GPS line
                self.coords(label, x + 6, line4)
                x1, y1, x2, y2 = self.bbox(label)
                line4 += 18
            round_rect(self, x1 - 6, y1 - 2, x2 + 6, y2 + 2, RADIUS_CHIP - 2, fill=pal["accent_soft"], outline="",
                       tags="map")
            self.tag_raise(label)
        else:
            self.create_text(x, line3, text="GPS –", anchor="w", fill=pal["muted"], font=app.f_tiny)
        if total is not None:  # data through the T-Box: the longest form that fits the rail
            forms = [t("c_since_boot", n=human_bytes(total)), human_bytes(total)]
            if rate and not small:
                speeds = f"↓ {human_bytes(rate[0])}/s  ↑ {human_bytes(rate[1])}/s"
                forms = [f"{speeds} · {human_bytes(total)}", speeds] + forms
            text = next((form for form in forms if measure(app.f_tiny, form) <= width), None)
            if text and line4 + 8 <= self.h:
                self.create_text(x, line4, anchor="w", fill=pal["muted"], font=app.f_tiny, text=text)


SECRET = ("iccid", "imsi", "imei", "tcam_id")  # identify the SIM/car: hidden until the user asks


def mask(value):
    return value[:6] + "•" * max(0, len(value) - 10) + value[-4:] if value and len(value) > 10 else value


class TboxInfo(tk.Toplevel):
    """T-Box identity and part numbers. SIM numbers are masked until "show" is clicked; click a value to copy."""

    ROWS = [("iccid", "ICCID (eSIM)"), ("imsi", "IMSI"), ("imei", "IMEI"), ("tcam_id", "TCAM ID"),
            ("carrier", None), ("hw", "HW"), ("swbl", "SW BL"), ("swlm", "SW LM"), ("swlx", "SW Lx"),
            ("sxbl", "SX BL"), ("sxdi", "SX DI"), ("du", "DU")]

    def __init__(self, app, info):
        if not info:
            return
        from .stats import carrier
        from .widgets import Chip
        pal, t = app.pal, app.t
        super().__init__(app.root, bg=pal["panel"], padx=22, pady=18)
        self.title("T-Box")
        self.resizable(False, False)
        self.transient(app.root)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.app, self.info, self.revealed = app, {**info, "carrier": carrier(info.get("imsi"))}, False
        tk.Label(self, text=t("c_tbox_info"), bg=pal["panel"], fg=pal["text"], font=app.f_title).grid(
            row=0, column=0, columnspan=2, sticky="w")
        tk.Label(self, text=t("c_tbox_note"), bg=pal["panel"], fg=pal["muted"], font=app.f_small).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 12))
        self.values = {}
        for row, (key, label) in enumerate(self.ROWS, start=2):
            if key == "hw":
                tk.Frame(self, bg=pal["line"], height=1).grid(row=row * 2 - 1, column=0, columnspan=2, sticky="ew",
                                                              pady=8)
            tk.Label(self, text=label or t("c_carrier"), bg=pal["panel"], fg=pal["muted"], font=app.f_small,
                     anchor="w", width=14).grid(row=row * 2, column=0, sticky="w", pady=1)
            value = tk.Label(self, bg=pal["panel"], fg=pal["text"], font=app.f_num, anchor="w", cursor="hand2")
            value.grid(row=row * 2, column=1, sticky="w", pady=1)
            value.bind("<Button-1>", lambda _e, k=key: self.copy(k))
            self.values[key] = value
        foot = tk.Frame(self, bg=pal["panel"])
        foot.grid(row=99, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        self.toggle = Chip(foot, "", app.f_small, bg=pal["panel"], fill=pal["panel2"], fg=pal["text"])
        self.toggle.pack(side="left")
        self.toggle.bind("<Button-1>", lambda _e: self.reveal(not self.revealed))
        self.status = tk.Label(foot, bg=pal["panel"], fg=pal["live"], font=app.f_small)
        self.status.pack(side="left", padx=12)
        self.reveal(False)
        fade_in(self)

    def reveal(self, on):
        self.revealed = on
        for key, label in self.values.items():
            value = self.info.get(key) or "–"
            label.configure(text=value if on or key not in SECRET else mask(value))
        self.toggle.set(self.app.t("c_hide" if on else "c_show"))

    def copy(self, key):
        value = self.info.get(key)
        if value:
            self.clipboard_clear()
            self.clipboard_append(value)
            self.status.configure(text=self.app.t("c_copied", name=dict(self.ROWS).get(key) or key))


def fade_in(window):
    """Fade a Toplevel in. Needs a compositing window manager; elsewhere -alpha is ignored and it just appears."""
    try:
        window.attributes("-alpha", 0.0)
    except tk.TclError:
        return
    animate(window, "fade", PANEL_MS, lambda e: window.attributes("-alpha", e))
