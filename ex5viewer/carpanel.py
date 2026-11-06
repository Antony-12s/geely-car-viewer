"""Car panel under the top bar: battery, drive, tires and temperature cards over the main screen's column,
and the T-Box card over the right column, so the card edges line up with the screens below."""
import tkinter as tk
import webbrowser

from .vehicle import compass
from .widgets import GAP, RADIUS_CARD, RADIUS_CHIP, baseline_text, draw_icon, round_rect

HEIGHT = 100
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


class CarPanel(tk.Canvas):
    def __init__(self, app, parent, left, right):
        """left / right: widths of the main and HUD columns below; the cards fill both with one GAP between."""
        super().__init__(parent, width=left + GAP + right, height=HEIGHT, bg=app.pal["bg"], highlightthickness=0)
        self.app, self.left, self.right = app, left, right
        self.data = {}
        self.tag_bind("map", "<Button-1>", lambda _e: self.open_map())
        self.tag_bind("info", "<Button-1>", lambda _e: TboxInfo(self.app, self.data.get("tcam_info")))
        for tag in ("map", "info"):
            self.tag_bind(tag, "<Enter>", lambda _e: self.configure(cursor="hand2"))
            self.tag_bind(tag, "<Leave>", lambda _e: self.configure(cursor=""))
        self.draw()

    def update_data(self, **data):
        self.data.update(data)
        self.draw()

    def open_map(self):
        gps = self.data.get("gps")
        if gps:
            webbrowser.open(f"https://www.google.com/maps?q={gps['lat']:.6f},{gps['lon']:.6f}")

    # ---------- drawing ----------
    def card(self, x, width, title, icon):
        pal, app = self.app.pal, self.app
        round_rect(self, x + 0.5, 0.5, x + width - 0.5, HEIGHT - 0.5, RADIUS_CARD, fill=pal["panel2"],
                   outline=pal["line"], width=1)
        draw_icon(self, icon, x + PAD, 10, 11, pal["muted"], width=1.2)
        self.create_text(x + PAD + 17, 16, text=title, anchor="w", fill=pal["muted"], font=app.f_caption)

    def draw(self):
        self.delete("all")
        app = self.app
        small = app.size_name == "small"
        connected = app.conn == "connected"
        car = self.data.get("car") or {}
        cards = [self._card_battery, self._card_drive, self._card_tires] + ([] if small else [self._card_temp])
        weights = [1.0, 1.0, 1.1] + ([] if small else [0.9])
        widths = split(self.left - GAP * (len(cards) - 1), weights)
        x = 0
        for draw_card, w in zip(cards, widths):
            draw_card(x, w, car, connected, small)
            x += w + GAP
        self._card_tbox(self.left + GAP, self.right, connected, small)

    def _card_battery(self, x, w, car, connected, small):
        app, pal, t = self.app, self.app.pal, self.app.t
        self.card(x, w, t("c_battery"), "battery")
        soc = car.get("soc") if connected else None
        colour = pal["muted"] if soc is None else pal["bad"] if soc < 20 else pal["warn"] if soc < 40 else pal["live"]
        bx, by, bw, bh = x + PAD, 38, 46, 24
        round_rect(self, bx + 1, by + 1, bx + bw - 1, by + bh - 1, 6, fill="", outline=colour, width=2)
        self.create_rectangle(bx + bw + 2, by + 7, bx + bw + 5, by + bh - 7, fill=colour, outline="")  # cap
        if soc is not None:
            self.create_rectangle(bx + 5, by + 5, bx + 5 + int((bw - 10) * soc / 100), by + bh - 5, fill=colour,
                                  outline="")
        charging = connected and car.get("plugged")
        baseline_text(self, bx + bw + 14, by + bh, fmt(soc, "{:.0f}%"), app.f_value, fill=pal["text"])
        sub = (t("c_charging", kw=f"{car.get('charge_kw') or 0:.1f}") if charging
               else (t("c_range", km=f"{car['range_km']:.0f}") if connected and car.get("range_km") is not None
                     else "–"))
        baseline_text(self, x + PAD, 84, sub, app.f_small, fill=pal["live"] if charging else pal["muted"])

    def _card_drive(self, x, w, car, connected, small):
        app, pal, t = self.app, self.app.pal, self.app.t
        self.card(x, w, t("c_drive"), "gauge")
        gear = car.get("gear") if connected else None
        driving = gear is not None and gear != "P"
        gx, gy = x + PAD, 36
        round_rect(self, gx, gy, gx + 40, gy + 40, RADIUS_CHIP, fill=pal["seg_on"], outline="")
        self.create_text(gx + 20, gy + 20, text=gear or "–", fill=pal["accent"] if driving else pal["text"],
                         font=app.f_value)
        speed = car.get("speed_kmh") if connected else None
        vx = gx + 52
        number = baseline_text(self, vx, gy + 22, fmt(speed, "{:.0f}"), app.f_value, fill=pal["text"])
        baseline_text(self, self.bbox(number)[2] + 4, gy + 22, "km/h", app.f_small, fill=pal["muted"])
        odo = car.get("odometer") if connected else None
        baseline_text(self, vx, gy + 44, fmt(odo, "{:,.0f} km"), app.f_small, fill=pal["muted"])
        if small and connected and car.get("temp_c") is not None:  # small window: no temperature card, so it sits on the title row
            self.create_text(x + w - PAD, 16, text=f"{car['temp_c']:.0f}°C", anchor="e", fill=pal["muted"],
                             font=app.f_small)

    def _card_tires(self, x, w, car, connected, small):
        app, pal, t = self.app, self.app.pal, self.app.t
        self.card(x, w, t("c_tires"), "tire")
        self.create_text(x + w - PAD, 16, text="psi", anchor="e", fill=pal["muted"], font=app.f_small)
        tires = (car.get("tires") or {}) if connected else {}
        cx, top = x + w // 2, 30
        round_rect(self, cx - 17, top, cx + 17, top + 62, 12, fill=pal["seg_on"], outline="")  # car, top view
        round_rect(self, cx - 10, top + 12, cx + 10, top + 22, 3, fill=pal["track"], outline="")  # windshield
        round_rect(self, cx - 10, top + 40, cx + 10, top + 50, 3, fill=pal["track"], outline="")  # rear window
        known = [v for v in tires.values() if v is not None]
        average = sum(known) / len(known) if known else None
        front_y, rear_y = top + 14, top + 48
        for key, dx, dy in (("fl", -1, -1), ("fr", 1, -1), ("rl", -1, 1), ("rr", 1, 1)):
            value = tires.get(key)
            bad = value is not None and (value < TIRE_LOW or value > TIRE_HIGH or abs(value - average) > TIRE_SPREAD)
            wy = front_y if dy < 0 else rear_y
            wx = cx + dx * 21  # wheels sit outside the body
            round_rect(self, wx - 2.5, wy - 7, wx + 2.5, wy + 7, 2, fill=pal["warn"] if bad else pal["text"], outline="")
            # values in two columns: left wheels right-aligned to the left of the body, right wheels to the right
            self.create_text(cx + dx * 34, wy, text=fmt(value, "{:.1f}"), anchor="e" if dx < 0 else "w",
                             fill=pal["warn"] if bad else pal["text"], font=app.f_num_bold)

    def _card_temp(self, x, w, car, connected, small):
        app, pal, t = self.app, self.app.pal, self.app.t
        self.card(x, w, t("c_temp"), "thermo")
        temp = car.get("temp_c") if connected else None
        number = baseline_text(self, x + PAD, 80, fmt(temp, "{:.0f}"), app.f_value, fill=pal["text"])
        baseline_text(self, self.bbox(number)[2] + 4, 80, "°C", app.f_small, fill=pal["muted"])

    def _card_tbox(self, x, w, connected, small):
        """Three rows: network + signal | GPS + map link | data through the T-Box."""
        app, pal, t = self.app, self.app.pal, self.app.t
        self.card(x, w, "T-Box", "signal")
        info = self.data.get("tcam_info")
        if connected and info:
            link = self.create_text(x + w - PAD, 16, text=t("c_tbox_info"), anchor="e", fill=pal["accent"],
                                    font=app.f_small, tags="info")
            draw_icon(self, "info", self.bbox(link)[0] - 15, 10, 11, pal["accent"], width=1.2, tags="info")
        tcam = self.data.get("tcam") if connected else None
        level = (tcam or {}).get("level") or 0
        row1, row2, row3 = 40, 62, 84
        for i in range(4):  # signal bars, growing left to right
            on = tcam and tcam.get("network") and i < level
            height = 6 + 3 * i
            self.create_rectangle(x + PAD + i * 6, row1 + 7 - height, x + PAD + i * 6 + 4, row1 + 7,
                                  fill=pal["live"] if on else pal["track"], outline="")
        if not tcam:
            net = "–"
        elif not tcam.get("network"):
            net = t("tcam_offline")
        else:
            net = tcam["network"] + (f"  {tcam['operator']}" if tcam.get("operator") else "")
        self.create_text(x + PAD + 34, row1, text=net, anchor="w", fill=pal["text"], font=app.f_bold)
        rate, total = (self.data.get("tbox_rate"), self.data.get("tbox_total")) if connected else (None, None)
        if rate and total is not None and not small:
            self.create_text(x + w - PAD, row1, text=t("c_since_boot", n=human_bytes(total)), anchor="e",
                             fill=pal["muted"], font=app.f_small)

        gps = self.data.get("gps") if connected else None
        if gps:
            angle = gps["heading"]
            car = self.data.get("car") or {}
            moving = gps.get("speed", 0) > 0.5 or (car.get("speed_kmh") or 0) > 2
            # heading is 0 while parked: say "parked" instead of a meaningless "0° N"
            where = f"{angle:.0f}° {compass(angle)}" if moving else t("c_parked")
            self.create_oval(x + PAD, row2 - 3, x + PAD + 6, row2 + 3, fill=pal["live"], outline="")
            self.create_text(x + PAD + 12, row2, text=f"GPS  {where}", anchor="w", fill=pal["text"], font=app.f_small)
            label = self.create_text(x + w - PAD - 9, row2, text=t("c_map") + " ↗", anchor="e", fill=pal["accent"],
                                     font=app.f_small, tags="map")
            x1, y1, x2, y2 = self.bbox(label)
            round_rect(self, x1 - 9, y1 - 4, x2 + 9, y2 + 4, RADIUS_CHIP, fill=pal["accent_soft"], outline="",
                       tags="map")
            self.tag_raise(label)  # the pill is drawn after the text, so lift the text back on top
        else:
            self.create_text(x + PAD, row2, text="GPS –", anchor="w", fill=pal["muted"], font=app.f_small)

        if rate and total is not None and not small:
            self.create_text(x + PAD, row3, anchor="w", fill=pal["muted"], font=app.f_small,
                             text=f"{t('c_via_tbox')}  ↓ {human_bytes(rate[0])}/s  ↑ {human_bytes(rate[1])}/s")


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
