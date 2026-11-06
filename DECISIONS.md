# Decisions

- **No scrcpy client / ffmpeg binaries.** The app speaks the scrcpy 5.0.1 server protocol itself and decodes with PyAV: one Python bundle runs on Windows, Linux and macOS, and touch control goes through scrcpy's control socket (instant) instead of `adb shell input` (0.2–0.5 s per tap).
- **Always capture 2560×1600.** A smaller scrcpy capture size makes the car's video wallpaper render at native pixel size (zoomed by 2560/max-size).
- **Software decoding only.** Measured 30% of one core for 2560×1600@30 → 704×440 (i5-12450H). PyAV wheels ship no VAAPI/D3D11/VideoToolbox; not worth a per-OS path. `thread_type=SLICE`: AUTO frame-threading added 12 frames (~400 ms) of lag.
- **Cluster over paramiko + a pipe socket.** No ssh binary needed on Windows. The cluster's dropbear has no stored host key (new key every boot), so the host key is not pinned; the trust boundary is the adb root tunnel to an in-car IP.
- **adb choice:** `$ADB`, then an installed Android SDK, then the bundled copy. Two adb versions on one PC kill each other's server and the car drops off.
- **EX2:** main screen via the same path; cluster shown as "not supported" until someone with an EX2 checks `dumpsys display`.
- **macOS build is Apple Silicon only** (GitHub retired Intel macOS runners), ad-hoc signed, not notarized.
- **Window size "auto" (default):** medium (screens 1.1×, user asked +10%), or small (0.8×, fits a 1024 px screen) when medium does not fit the screen (screen minus 16 px width / 90 px height for title bar and taskbar). Never grows to large on its own: the user wanted a window that does not fill the screen. An explicit S/M/L choice is kept even if it overflows.
- **Cluster capture (measured on the car, 2026-11-06):** the cluster is a 2-core Cortex-A55 at load ~3–5. JPEG made on the cluster (960 px, ~20 KB) instead of a 4 MB BMP: 0.3 → 1.7 fps max; `dump surface` alone takes ~234 ms. Setting 0.5 s gives 1.70 fps (0.59 s/frame), 1 s gives 0.96 fps. Weston: ~4–16% of a core idle, 24–30% while capturing. No faster option offered: the cluster is the limit and the gauges come first.
- **Cluster session teardown:** killing the local `adb shell` does not kill `toybox nc` on the head unit, so dropbear kept each session (shell + 4 MB temp file) alive. Now: `nc -q 1`, clean SSH close on stop, and each session deletes temp files of dead sessions.
