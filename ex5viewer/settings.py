"""User settings, saved as JSON next to the log file."""
import json
import logging

from . import paths

log = logging.getLogger(__name__)

DEFAULTS = {
    "language": "en",          # th / en
    "theme": "telemetry",      # telemetry / oled / dark
    "size": "auto",            # auto (medium, small when the screen is too small) / small / medium / large
    "scale": 0.0,              # screen scale picked by dragging the window corner; 0 = use "size"
    "topmost": False,
    "animations": True,        # switches, meters, numbers and panels move instead of jumping
    "port": 5566,              # this car's adb port; plain IPs get it appended
    "auto_connect": True,
    "auto_reconnect": True,
    "max_fps": 30,             # 15 / 30 / 60
    "cluster_interval": 1.0,   # 0.5 / 1 / 2 / 5 seconds
    "rotate_hud": True,        # HUD is drawn upside down for the windshield mirror
    "graph_seconds": 60,       # 30 / 60 / 120
    "show_host": True,
    "show_car": True,
    "show_vehicle": True,      # car panel: battery, tires, gear, T-Box
    # remembered state
    "link": "wifi",            # wifi / usb
    "address": "",
    "usb_serial": "",
    "model": "auto",           # auto / EX5 / EX2
    "control": False,
    "cluster_refresh": True,
}

CHOICES = {
    "language": ["th", "en"], "theme": ["telemetry", "oled", "dark"], "size": ["auto", "small", "medium", "large"],
    "max_fps": [15, 30, 60], "cluster_interval": [0.5, 1.0, 2.0, 5.0], "graph_seconds": [30, 60, 120],
    "link": ["wifi", "usb"], "model": ["auto", "EX5", "EX2"],
}


MIN_SCALE, MAX_SCALE = 0.8, 3.0  # below 0.8 (the small preset) the top bar no longer fits


class Settings(dict):
    def __init__(self, path=None):
        super().__init__(DEFAULTS)
        self.path = path or paths.config_dir() / "settings.json"
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            saved = {}
        except (OSError, ValueError) as error:  # a broken file must not stop the app from opening
            log.warning("ignoring unreadable settings: %s", error)
            saved = {}
        for key, value in saved.items():
            if key in DEFAULTS and self._valid(key, value):
                self[key] = value

    @staticmethod
    def _valid(key, value):
        default = DEFAULTS[key]
        if key in CHOICES:
            return value in CHOICES[key]
        if key == "port":
            return isinstance(value, int) and 0 < value < 65536
        if key == "scale":
            return isinstance(value, float) and (value == 0 or MIN_SCALE <= value <= MAX_SCALE)
        return isinstance(value, type(default))

    def set(self, key, value):
        if self._valid(key, value) and self.get(key) != value:
            self[key] = value
            self.save()

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)  # atomic: a crash mid-write keeps the old file

    def reset(self):
        self.clear()
        self.update(DEFAULTS)
        self.save()
