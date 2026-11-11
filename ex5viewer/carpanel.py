"""Car data section in the lower tray (design A "OLED cinema"): battery, range, gear/speed, tires, T-Box/GPS.
Plus the T-Box info dialog (SIM numbers masked until asked)."""
import tkinter as tk
import webbrowser

from .vehicle import compass
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


def split(total, weights):
    """Integer widths that add up to total, in proportion to weights."""
    scale = total / sum(weights)
    widths = [int(w * scale) for w in weights]
    widths[-1] += total - sum(widths)
    return widths


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
    """Car data beside the HUD / Cluster cards in the lower tray (design A): one open section with a hairline on
    its left. Row 1: battery | range | gear + speed. Row 2: tires | T-Box + GPS."""

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
            if not self.shown:
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
    def rows(self):
        """Vertical positions, stretched between the small (137 px) and medium (165 px) tray heights."""
        f = (self.h - 137) / 28
        at = lambda small, medium: round(small + (medium - small) * f)  # noqa: E731
        return dict(head=at(7, 10), label=at(31, 36), value=at(60, 70), track=at(65, 76), sub=at(76, 90),
                    rule=at(85, 104), title=at(97, 118), line2=at(113, 136), line3=at(128, 153))

    def value(self, x, baseline, number, unit, colour):
        app, pal = self.app, self.app.pal
        item = baseline_text(self, x, baseline, number, app.f_value, fill=colour)
        if unit:
            baseline_text(self, self.bbox(item)[2] + 4, baseline, unit, app.f_small, fill=pal["muted"])
        return item

    def draw(self):
        self.delete("all")
        app, pal, t = self.app, self.app.pal, self.app.t
        small = app.size_name == "small"
        connected = app.conn == "connected"
        car = (self.shown or self.data.get("car") or {}) if connected else {}
        r, w = self.rows(), self.w
        self.create_line(0.5, 0, 0.5, self.h, fill=pal["line"])
        x0, inner = PAD, w - 2 * PAD
        head = self.create_text(x0, r["head"] + 6, text=t("c_status"), anchor="w", fill=pal["text"],
                                font=app.f_caption)
        self.create_text(self.bbox(head)[2] + 8, r["head"] + 6, text=app.layout_model(), anchor="w",
                         fill=pal["muted"], font=app.f_tiny)
        info = self.data.get("tcam_info")
        if connected and info:
            link = self.create_text(w - PAD, r["head"] + 6, text=t("c_tbox_info"), anchor="e", fill=pal["accent"],
                                    font=app.f_tiny, tags="info")
            draw_icon(self, "info", self.bbox(link)[0] - 15, r["head"], 11, pal["accent"], width=1.2, tags="info")

        # row 1: battery | range | gear + speed
        c1, c2, c3 = split(inner - 2 * 18, [0.8, 1.0, 1.4])
        xs = (x0, x0 + c1 + 18, x0 + c1 + c2 + 36)
        for x, key in zip(xs, ("c_battery", "c_range_title", "c_gear_speed")):
            self.create_text(x, r["label"], text=t(key), anchor="w", fill=pal["muted"], font=app.f_tiny)
        soc = car.get("soc")
        colour = pal["muted"] if soc is None else pal["bad"] if soc < 20 else pal["warn"] if soc < 40 else pal["live"]
        self.value(xs[0], r["value"], fmt(soc, "{:.0f}"), "%" if soc is not None else "", colour)
        track = min(68, c1 - 4)
        self.create_rectangle(xs[0], r["track"], xs[0] + track, r["track"] + 3, fill=pal["track"], outline="")
        if soc is not None:
            self.create_rectangle(xs[0], r["track"], xs[0] + track * max(0, min(100, soc)) / 100, r["track"] + 3,
                                  fill=colour, outline="")
        rng = car.get("range_km")
        self.value(xs[1], r["value"], fmt(rng, "{:.0f}"), "km" if rng is not None else "", pal["text"])
        charging = car.get("plugged")
        odo = car.get("odometer")
        sub = (t("c_charging", kw=f"{car.get('charge_kw') or 0:.1f}") if charging
               else t("c_odo", km=f"{odo:,.0f}") if odo is not None else "–")
        self.create_text(xs[1], r["sub"], text=sub, anchor="w", fill=pal["live"] if charging else pal["muted"],
                         font=app.f_tiny, width=c2)
        gear = car.get("gear")
        driving = gear is not None and gear != "P"
        box = 26 if small else 30
        gy = r["value"] - box + 4
        round_rect(self, xs[2] + 0.5, gy + 0.5, xs[2] + box - 0.5, gy + box - 0.5, 4, fill=pal["bg"],
                   outline=pal["line"])
        self.create_text(xs[2] + box / 2, gy + box / 2, text=gear or "–",
                         fill=pal["accent"] if driving else pal["text"], font=app.f_value)
        self.value(xs[2] + box + 10, r["value"], fmt(car.get("speed_kmh"), "{:.0f}"), "km/h", pal["text"])
        temp = car.get("temp_c")
        self.create_text(xs[2], r["sub"], text=t("c_outside", t=f"{temp:.0f}") if temp is not None else "–",
                         anchor="w", fill=pal["muted"], font=app.f_tiny)

        # row 2: tires | T-Box
        self.create_line(x0, r["rule"], w - PAD, r["rule"], fill=pal["line"])
        d1, _d2 = split(inner - 18, [1.0, 1.5])
        tx = x0 + d1 + 18
        title = self.create_text(x0, r["title"], text=t("c_tires"), anchor="w", fill=pal["text"], font=app.f_caption)
        self.create_text(self.bbox(title)[2] + 8, r["title"], text="psi", anchor="w", fill=pal["muted"],
                         font=app.f_tiny)
        tires = car.get("tires") or {}
        known = [v for v in tires.values() if v is not None]
        average = sum(known) / len(known) if known else None
        axles = ((t("c_front"), ("fl", "fr")), (t("c_rear"), ("rl", "rr")))
        label_w = max(measure(app.f_tiny, label) for label, _pair in axles) + 6
        axle_w = label_w + 2 * measure(app.f_num, "00.0") + 2 * 6
        stacked = 2 * axle_w + 8 > d1  # narrow tray: front on one line, rear on the next
        for index, (label, pair) in enumerate(axles):
            x = x0 if stacked or index == 0 else x0 + axle_w + 8
            y = r["line3"] if stacked and index else r["line2"]
            self.create_text(x, y, text=label, anchor="w", fill=pal["muted"], font=app.f_tiny)
            x += label_w
            for key in pair:
                value = tires.get(key)
                bad = value is not None and (value < TIRE_LOW or value > TIRE_HIGH or abs(value - average) > TIRE_SPREAD)
                item = self.create_text(x, y, text=fmt(value, "{:.1f}"), anchor="w",
                                        fill=pal["warn"] if bad else pal["text"], font=app.f_num)
                x = self.bbox(item)[2] + 6
        self._tbox(tx, w - PAD - tx, r, connected, small)

    def _tbox(self, x, width, r, connected, small):
        """T-Box: network + signal | GPS + map link | data through the T-Box."""
        app, pal, t = self.app, self.app.pal, self.app.t
        tcam = self.data.get("tcam") if connected else None
        title = self.create_text(x, r["title"], text="T-Box", anchor="w", fill=pal["text"], font=app.f_caption)
        if tcam and tcam.get("network"):
            self.create_text(self.bbox(title)[2] + 8, r["title"], text=tcam["network"], anchor="w", fill=pal["live"],
                             font=app.f_tiny)
        level = (tcam or {}).get("level") or 0
        for i in range(4):  # signal bars, growing left to right
            on = tcam and tcam.get("network") and i < level
            height = 4 + 2 * i
            self.create_rectangle(x + i * 4, r["line2"] + 5 - height, x + i * 4 + 2, r["line2"] + 5,
                                  fill=pal["live"] if on else pal["track"], outline="")
        if not tcam:
            net = "–"
        elif not tcam.get("network"):
            net = t("tcam_offline")
        else:
            net = f"{level}/4" + (f"  {tcam['operator']}" if tcam.get("operator") else "")
        self.create_text(x + 22, r["line2"], text=net, anchor="w", fill=pal["text"], font=app.f_small,
                         width=width - 22)
        rate, total = (self.data.get("tbox_rate"), self.data.get("tbox_total")) if connected else (None, None)
        gps = self.data.get("gps") if connected else None
        cursor = x
        if gps:
            angle = gps["heading"]
            car = self.data.get("car") or {}
            moving = gps.get("speed", 0) > 0.5 or (car.get("speed_kmh") or 0) > 2
            # heading is 0 while parked: say "parked" instead of a meaningless "0° N"
            where = f"{angle:.0f}° {compass(angle)}" if moving else t("c_parked")
            item = self.create_text(x, r["line3"], text=f"GPS · {where}", anchor="w", fill=pal["muted"],
                                    font=app.f_tiny)
            label = self.create_text(self.bbox(item)[2] + 14, r["line3"], text=t("c_map") + " ↗", anchor="w",
                                     fill=pal["accent"], font=app.f_tiny, tags="map")
            x1, y1, x2, y2 = self.bbox(label)
            round_rect(self, x1 - 6, y1 - 2, x2 + 6, y2 + 2, RADIUS_CHIP - 2, fill=pal["accent_soft"], outline="",
                       tags="map")
            self.tag_raise(label)
            cursor = x2 + 14
        else:
            item = self.create_text(x, r["line3"], text="GPS –", anchor="w", fill=pal["muted"], font=app.f_tiny)
            cursor = self.bbox(item)[2] + 14
        if rate and total is not None and not small:
            text = f"↓ {human_bytes(rate[0])}/s  ↑ {human_bytes(rate[1])}/s"
            if cursor + measure(app.f_tiny, text) <= x + width:
                self.create_text(cursor, r["line3"], anchor="w", fill=pal["muted"], font=app.f_tiny, text=text)


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
