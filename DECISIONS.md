# Decisions

- **No scrcpy client / ffmpeg binaries.** The app speaks the scrcpy 5.0.1 server protocol itself and decodes with PyAV: one Python bundle runs on Windows, Linux and macOS, and touch control goes through scrcpy's control socket (instant) instead of `adb shell input` (0.2–0.5 s per tap).
- **Always capture 2560×1600.** A smaller scrcpy capture size makes the car's video wallpaper render at native pixel size (zoomed by 2560/max-size).
- **Software decoding only.** Measured 30% of one core for 2560×1600@30 → 704×440 (i5-12450H). PyAV wheels ship no VAAPI/D3D11/VideoToolbox; not worth a per-OS path. `thread_type=SLICE`: AUTO frame-threading added 12 frames (~400 ms) of lag.
- **Cluster over paramiko + a pipe socket.** No ssh binary needed on Windows. The cluster's dropbear has no stored host key (new key every boot), so the host key is not pinned; the trust boundary is the adb root tunnel to an in-car IP.
- **adb choice:** `$ADB`, then an installed Android SDK, then the bundled copy. Two adb versions on one PC kill each other's server and the car drops off.
- **EX2:** main screen via the same path; cluster shown as "not supported" until someone with an EX2 checks `dumpsys display`.
- **macOS build is Apple Silicon only** (GitHub retired Intel macOS runners), ad-hoc signed, not notarized.
- **Window size "auto" (default):** medium, or small when medium does not fit the screen (screen minus 16 px width / 90 px height for title bar and taskbar). Never grows to large on its own: the user wanted a window that does not fill the screen. An explicit S/M/L choice is kept even if it overflows.
