"""Car panel under the top bar: battery, drive, tires, temperature and T-Box cards on one canvas."""
import tkinter as tk
import webbrowser

from .vehicle import compass
from .widgets import round_rect

HEIGHT = 84
TIRE_LOW, TIRE_HIGH, TIRE_SPREAD = 30.0, 42.0, 3.0  # psi: warn outside the band or when one tire is off


def fmt(value, pattern, missing="–"):
    return pattern.format(value) if value is not None else missing


def human_bytes(count):
    for unit, size in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if count >= size:
            return f"{count / size:.1f} {unit}"
    return f"{count:.0f} B"


class CarPanel(tk.Canvas):
    def __init__(self, app, parent, width):
        super().__init__(parent, width=width, height=HEIGHT, bg=app.pal["bg"], highlightthickness=0)
        self.app, self.width = app, width
        self.data = {}
        self.tag_bind("map", "<Button-1>", lambda _e: self.open_map())
        self.tag_bind("map", "<Enter>", lambda _e: self.configure(cursor="hand2"))
        self.tag_bind("map", "<Leave>", lambda _e: self.configure(cursor=""))
        self.draw()

    def update_data(self, **data):
        self.data.update(data)
        self.draw()

    def open_map(self):
        gps = self.data.get("gps")
        if gps:
            webbrowser.open(f"https://www.google.com/maps?q={gps['lat']:.6f},{gps['lon']:.6f}")

    # ---------- drawing ----------
    def card(self, x, width, title):
        pal = self.app.pal
        round_rect(self, x, 1, x + width, HEIGHT - 1, 14, fill=pal["panel2"], outline=pal["line"])
        self.create_text(x + 14, 14, text=title, anchor="w", fill=pal["muted"], font=self.app.f_tiny)

    def draw(self):
        self.delete("all")
        app, pal, t = self.app, self.app.pal, self.app.t
        small = app.size_name == "small"
        k = 0.85 if small else 1.0
        gap = 10
        widths = [int(w * k) for w in (200, 190, 196, 92)]
        if small:
            widths[3] = 0  # temperature folds into the drive card
        x = 0
        car = self.data.get("car") or {}
        connected = app.conn == "connected"
        big = (app.f_title[0], 20 if not small else 17, "bold")

        # battery
        w = widths[0]
        self.card(x, w, t("c_battery"))
        soc = car.get("soc") if connected else None
        colour = pal["muted"] if soc is None else pal["bad"] if soc < 20 else pal["warn"] if soc < 40 else pal["live"]
        bx, by = x + 14, 30
        round_rect(self, bx, by, bx + 46, by + 24, 6, fill="", outline=colour, width=2)
        self.create_rectangle(bx + 46, by + 8, bx + 50, by + 16, fill=colour, outline="")
        if soc is not None:
            self.create_rectangle(bx + 4, by + 4, bx + 4 + int(38 * soc / 100), by + 20, fill=colour, outline="")
        self.create_text(bx + 60, by + 12, text=fmt(soc, "{:.0f}%"), anchor="w", fill=pal["text"], font=big)
        charging = connected and car.get("plugged")
        sub = (t("c_charging", kw=f"{car.get('charge_kw') or 0:.1f}") if charging
               else (t("c_range", km=f"{car['range_km']:.0f}") if connected and car.get("range_km") is not None else "–"))
        self.create_text(bx, by + 40, text=("⚡ " if charging else "") + sub, anchor="w",
                         fill=pal["live"] if charging else pal["muted"], font=app.f_small)
        x += w + gap

        # drive: gear tile, speed, odometer (+ temperature in the small window)
        w = widths[1]
        self.card(x, w, t("c_drive"))
        gear = car.get("gear") if connected else None
        gx, gy = x + 14, 28
        round_rect(self, gx, gy, gx + 40, gy + 40, 10, fill=pal["seg_on"],
                   outline=pal["accent"] if gear and gear != "P" else pal["line"], width=2)
        self.create_text(gx + 20, gy + 20, text=gear or "–", fill=pal["accent"] if gear and gear != "P" else pal["text"],
                         font=(app.f_title[0], 17, "bold"))
        speed = car.get("speed_kmh") if connected else None
        number = self.create_text(gx + 52, gy + 9, text=fmt(speed, "{:.0f}"), anchor="w", fill=pal["text"], font=big)
        self.create_text(self.bbox(number)[2] + 4, gy + 14, text="km/h", anchor="w", fill=pal["muted"],
                         font=app.f_tiny)
        odo = car.get("odometer") if connected else None
        extra = f"  ·  {car['temp_c']:.0f}°C" if small and connected and car.get("temp_c") is not None else ""
        self.create_text(gx + 52, gy + 31, text=fmt(odo, "{:,.0f} km") + extra, anchor="w", fill=pal["muted"],
                         font=app.f_small)
        x += w + gap

        # tires: top view of the car, pressure at each wheel
        w = widths[2]
        self.card(x, w, t("c_tires"))
        tires = (car.get("tires") or {}) if connected else {}
        cx, cy = x + w // 2, 49
        round_rect(self, cx - 13, cy - 30, cx + 13, cy + 30, 12, fill=pal["seg_on"], outline=pal["muted"])
        round_rect(self, cx - 9, cy - 17, cx + 9, cy - 7, 4, fill=pal["track"], outline="")   # windshield
        round_rect(self, cx - 9, cy + 13, cx + 9, cy + 20, 3, fill=pal["track"], outline="")  # rear window
        known = [v for v in tires.values() if v is not None]
        average = sum(known) / len(known) if known else None
        for key, dx, dy, anchor in (("fl", -1, -1, "e"), ("fr", 1, -1, "w"), ("rl", -1, 1, "e"), ("rr", 1, 1, "w")):
            value = tires.get(key)
            bad = value is not None and (value < TIRE_LOW or value > TIRE_HIGH or abs(value - average) > TIRE_SPREAD)
            wx, wy = cx + dx * 16, cy + dy * 18
            round_rect(self, wx - 3, wy - 8, wx + 3, wy + 8, 3, fill=pal["warn"] if bad else pal["text"], outline="")
            self.create_text(cx + dx * 27, wy, text=fmt(value, "{:.1f}"), anchor=anchor,
                             fill=pal["warn"] if bad else pal["text"], font=(app.f_num[0], 10, "bold"))
        self.create_text(x + w - 12, 14, text="psi", anchor="e", fill=pal["muted"], font=app.f_tiny)
        x += w + gap

        # temperature
        w = widths[3]
        if w:
            self.card(x, w, t("c_temp"))
            temp = car.get("temp_c") if connected else None
            number = self.create_text(x + 14, 46, text=fmt(temp, "{:.0f}"), anchor="w", fill=pal["text"], font=big)
            self.create_text(self.bbox(number)[2] + 3, 40, text="°C", anchor="w", fill=pal["muted"], font=app.f_small)
            x += w + gap

        # T-Box: network + signal bars, GPS + heading + map link, data through the T-Box
        w = self.width - x
        self.card(x, w, "T-Box")
        tcam = self.data.get("tcam") if connected else None
        level = (tcam or {}).get("level") or 0
        sx, sy = x + 14, 44
        for i in range(4):
            on = tcam and tcam.get("network") and i < level
            self.create_rectangle(sx + i * 6, sy - 4 - i * 3, sx + i * 6 + 4, sy + 6,
                                  fill=pal["live"] if on else pal["track"], outline="")
        if not tcam:
            net = "–"
        elif not tcam.get("network"):
            net = t("tcam_offline")
        else:
            net = tcam["network"] + (f"  {tcam['operator']}" if tcam.get("operator") else "")
        self.create_text(sx + 32, sy + 1, text=net, anchor="w", fill=pal["text"], font=app.f_bold)

        gps = self.data.get("gps") if connected else None
        line2 = sy + 26
        if gps:
            angle = gps["heading"]
            self.create_text(sx, line2, text=f"GPS ✓  {angle:.0f}° {compass(angle)}", anchor="w", fill=pal["text"],
                             font=app.f_small)
            mx = x + w - 14
            label = self.create_text(mx, line2, text=t("c_map") + " ↗", anchor="e", fill=pal["accent"],
                                     font=app.f_small, tags="map")
            x1, y1, x2, y2 = self.bbox(label)
            self.create_rectangle(x1 - 8, y1 - 3, x2 + 8, y2 + 3, outline=pal["accent"], tags="map")
        else:
            self.create_text(sx, line2, text="GPS –", anchor="w", fill=pal["muted"], font=app.f_small)

        rate, total = (self.data.get("tbox_rate"), self.data.get("tbox_total")) if connected else (None, None)
        if rate and total is not None and not small:
            tx = x + w // 2 - 20
            self.create_text(tx, sy + 1, text=f"{t('c_via_tbox')}  ↓ {human_bytes(rate[0])}/s  ↑ {human_bytes(rate[1])}/s", anchor="w",
                             fill=pal["muted"], font=app.f_num_small)
            self.create_text(tx, line2, text=t("c_since_boot", n=human_bytes(total)), anchor="w", fill=pal["muted"],
                             font=app.f_tiny)
