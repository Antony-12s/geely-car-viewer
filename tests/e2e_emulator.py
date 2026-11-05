"""End-to-end against the Android emulator (USB-style serial). Run under Xvfb."""
import os
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, "/mnt/work/Project/ex5-viewer")
from PIL import ImageGrab

from ex5viewer import adb, ui
from ex5viewer.settings import Settings

OUT = Path(os.environ["TMPDIR"])
SERIAL = "emulator-5580"
adb.usb_devices = lambda: [(SERIAL, "sdk_car")]
ui.DISPLAYS["hud"] = 2  # the emulator's working secondary display

cfg = OUT / "e2e-settings.json"
cfg.unlink(missing_ok=True)
s = Settings(cfg)
s.update(link="usb", usb_serial=SERIAL, auto_connect=False, cluster_interval=1.0)
root = tk.Tk()
root.geometry("+0+0")
app = ui.App(root, s)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def shot(name):
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()), xdisplay=os.environ["DISPLAY"]).save(OUT / name)


def states():
    return {n: sc.state for n, sc in app.screens.items()}


def device_procs():
    return adb.run("-s", SERIAL, "shell", "ps -A | grep -c app_process; ls /data/local/tmp | grep -c ex5viewer").stdout.split()


pump(3)  # usb list arrives
print("button:", app.conn_button.cget("text"))
app.on_conn_button()
print("after click:", app.conn, app.conn_button.cget("text"))
pump(8)
print("conn:", app.conn, "model:", app.model, "states:", states())
print("fps main/hud:", app.screens["main"].fps_label.cget("text"), app.screens["hud"].fps_label.cget("text"))
print("rates:", app.down_label.cget("text"), app.up_label.cget("text"))
print("car meters:", {k: v.value.cget("text") for k, v in app.meters_box["car"].items()})
shot("e2e_live.png")

# touch: open app grid by tapping the bottom bar centre on the emulator launcher (display 0)
app.control_var.set(True)
app.set_control(True)
m = app.screens["main"]
w, h = m.size
before = app.meters["main"]._up
for kind, fx in (("ButtonPress", 0.49), ("ButtonRelease", 0.49)):
    event = tk.Event()
    event.type = getattr(tk.EventType, kind)
    event.x, event.y = int(ui.PAD + fx * w), int(ui.PAD + 0.97 * h)
    app.on_touch(event)
pump(3)
shot("e2e_after_tap.png")

# kill the server on the device: streams must come back on their own
adb.run("-s", SERIAL, "shell", "pkill -f com.genymobile.scrcpy")
seen = set()
end = time.time() + 12
while time.time() < end:
    pump(0.2)
    seen.add(app.screens["main"].state)
    if "reconnecting" in seen and app.screens["main"].state == "live":
        break
print("after server kill, main states seen:", seen, "now:", states())

# settings panel + language/theme rebuild while streaming
app.toggle_settings()
pump(0.5)
shot("e2e_settings.png")
app.change_setting("language", "en")
pump(2)
print("after EN rebuild:", app.conn_label.cget("text"), states())
shot("e2e_en.png")
app.change_setting("language", "th")
app.close_settings()

app.on_conn_button()  # disconnect
pump(3)
print("after disconnect:", app.conn, states(), "button:", app.conn_button.cget("text"))
print("device app_process count, leftover jars:", device_procs())
print("forwards:", adb.run("forward", "--list").stdout.strip() or "none")
app.quit()
