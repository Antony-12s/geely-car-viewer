"""Car data for the car panel: VHAL properties (battery, range, gear, tires...) and the T-Box GPS.

Read-only: `cmd car_service get-property-value <id>` on the head unit, no root.
Ids marked "EX5 vendor" were matched against the cluster on 2026-11-06 (19% / 98 km / 39 °C);
AOSP ids follow android.hardware.automotive.vehicle units (m/s, km, mW).
"""
import math
import re
import time

from . import adb

# name: candidate ids, first one with status 0 wins
PROPS = {
    "soc": ["2160730e", "21608057"],      # % (EX5 vendor; AOSP Wh/capacity gave 22% when the car said 19%)
    "range_km": ["216072da", "11600308"],  # km (EX5 vendor, then AOSP RANGE_REMAINING)
    "temp_c": ["216072cc"],               # °C shown top right on the cluster (EX5 vendor)
    "speed": ["11600207"],                # PERF_VEHICLE_SPEED, m/s
    "gear": ["11400400"],                 # GEAR_SELECTION
    "odometer": ["11600204"],             # PERF_ODOMETER, km
    "battery_wh": ["11600309"],           # EV_BATTERY_LEVEL, Wh: fallback for soc on other cars
    "capacity_wh": ["11600106"],          # INFO_EV_BATTERY_CAPACITY, Wh
    "plugged": ["1120030a"],              # EV_CHARGE_PORT_CONNECTED
    "charge_mw": ["1160030c"],            # EV_BATTERY_INSTANTANEOUS_CHARGE_RATE, mW
}
TIRES_ID = "17600309"                     # TIRE_PRESSURE, areas 1/2/4/8 = FL/FR/RL/RR (psi on the EX5)
TIRE_AREAS = {1: "fl", 2: "fr", 4: "rl", 8: "rr"}
GEARS = {1: "N", 2: "R", 4: "P", 8: "D", 16: "1", 32: "2", 64: "3", 128: "4"}

# Android 11 (EX5): "Property:0x..,status: 0,timestamp:1,zone:0x0,floatValues: [..],int32Values: [..]"
# Android 13: same with a space after every comma and colon
VALUE = re.compile(r"Property:0x([0-9a-f]+), ?status: (\d+), ?timestamp: ?\d+, ?zone: ?0x([0-9a-f]+), ?"
                   r"floatValues: \[([^\]]*)\], ?int32Values: \[([^\]]*)\]")


def parse_values(text):
    """{(id, area): number} for every readable (status 0) value in car_service output."""
    values = {}
    for prop, status, area, floats, ints in VALUE.findall(text):
        raw = (floats or ints).split(",")[0].strip()
        if status == "0" and raw:
            try:
                values[(prop, int(area, 16))] = float(raw)
            except ValueError:
                pass
    return values


def build(values):
    """Turn raw property values into the panel's dict (None = unknown)."""
    def first(name):
        return next((values[(prop, 0)] for prop in PROPS[name] if (prop, 0) in values), None)

    speed, gear, plugged, charge = first("speed"), first("gear"), first("plugged"), first("charge_mw")
    tires = {key: values.get((TIRES_ID, area)) for area, key in TIRE_AREAS.items()}
    soc = first("soc")
    if soc is None and first("battery_wh") is not None and first("capacity_wh"):
        soc = 100 * first("battery_wh") / first("capacity_wh")
    range_km = first("range_km")
    if range_km is not None and range_km > 2000:  # AOSP sends meters; the EX5 vendor value is km
        range_km /= 1000
    return {
        "soc": soc if soc is not None and 0 <= soc <= 100 else None,
        "range_km": range_km,
        "temp_c": first("temp_c"),
        "speed_kmh": speed * 3.6 if speed is not None else None,
        "gear": GEARS.get(int(gear)) if gear is not None else None,
        "odometer": first("odometer"),
        "plugged": bool(plugged) if plugged is not None else None,
        "charge_kw": abs(charge) / 1e6 if charge else 0.0 if charge is not None else None,
        "tires": tires if any(v is not None for v in tires.values()) else None,
    }


class VehicleStats:
    """One adb shell per sample asks car_service for every property the panel shows."""

    def __init__(self, serial):
        self.serial = serial
        self.prefix = ""  # the EX5 (Android 11) reads ids as hex; Android 13 needs "0x" or reads them as decimal

    def script(self):
        ids = [prop for candidates in PROPS.values() for prop in candidates] + [TIRES_ID]
        return "; ".join(f"cmd car_service get-property-value {self.prefix}{prop}" for prop in ids)

    def sample(self):
        out = adb.run("-s", self.serial, "shell", self.script(), timeout=15).stdout
        if not self.prefix and " // 0x" in out:  # "Property Id: 11600204 // 0xb1014c": parsed as decimal
            self.prefix = "0x"
            out = adb.run("-s", self.serial, "shell", self.script(), timeout=15).stdout
        values = parse_values(out)
        return build(values) if values else None


# ---------- T-Box GPS (from the head unit log, see stats.CarStats) ----------
POSITION = re.compile(r"posnFromSatlt\{ ?posnLat:(-?[\d.]+), posnLgt:(-?[\d.]+), posnAlti:(-?[\d.]+), "
                      r"posnSpd:(-?[\d.]+), posnDir:(-?[\d.]+)")


def parse_position(line):
    """lat/lon in degrees (the HAL log uses milliarcseconds), heading in degrees; None if no fix."""
    match = POSITION.search(line)
    if not match:
        return None
    lat, lon, alt, speed, heading = map(float, match.groups())
    if abs(lat) > 90 or abs(lon) > 180:
        lat, lon = lat / 3.6e6, lon / 3.6e6
    if (lat, lon) == (0.0, 0.0) or not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    return {"lat": lat, "lon": lon, "alt": alt, "speed": speed, "heading": heading % 360, "time": time.monotonic()}


def compass(degrees):
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((degrees + 22.5) % 360 // 45)]
