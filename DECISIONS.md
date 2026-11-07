# Decisions

- **APK tab:** Install a user-selected APK on the connected head unit through its explicit ADB serial. Keep the operation off the UI thread and display ADB’s result.
- **Compact system meters:** Show GPU utilization as a percentage in the System card so the clock suffix cannot clip it. Linux PC RAM follows CPU directly while host GPU polling is disabled.

- **Telemetry desktop layout:** Keep T-Box carrier, signal, GPS and data usage on the main page, with separate PC/car metric rows and a Wi-Fi/USB connection form. Vehicle cards open through the info button. Compact windows overlay the detail row to keep all controls on screen. HUD is above a larger cluster viewport, with letterboxing instead of stretching the display. Existing saved themes remain selectable.

- **Linux host GPU telemetry:** Stop polling host GPU counters after repeated i915 reset failures around reported system hangs. This removes one driver interaction from the app while the freeze trigger is investigated. Keep host CPU/RAM and vehicle telemetry available.

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
- **T-Box (TCAM) status in the top bar:** read from the head unit's own log line `onEsimStatusoNotification` (logged every 2 s by ECARX TcamService) every 10 s: network, signal level 0–4, operator. Read-only: nothing is sent to the TCAM. The TCAM model/firmware is not stored on the head unit (only reachable over UDS diagnostics), so it is not shown.
- **Car panel (battery, drive, tires, temperature, T-Box):** VHAL via `cmd car_service get-property-value` every 4 s in its own thread (car_service hangs ~20 s while the car powers down; that must not freeze the other meters). Battery % and range use EX5 vendor ids `2160730e` / `216072da`, matched to the cluster (19% / 98 km); AOSP `EV_BATTERY_LEVEL / capacity` gave 22% on the same car, so it is only a fallback. Tires `17600309` in psi, warn below 30, above 42, or 3 psi off the average. T-Box GPS heading + map link and the `eth0.11` byte counters come from the 2 s car stats call. No location is stored or sent anywhere; the map link opens only on click.
- **T-Box carrier from the IMSI:** the status log says `Operator_Chinamobile` on a car whose eSIM is TrueMove H (IMSI 520-04). The panel asks TcamService once per connection with `service call tcam 133` (`ITcamService.getTcamInfo`, its cached copy; nothing goes to the TCAM) and maps MCC+MNC to a name. The same reply feeds the "T-Box info" dialog: part numbers shown, ICCID/IMSI/IMEI/TCAM ID masked until "show", click to copy. Never logged or saved by the app.
- **Renamed to Geely Car Viewer (1.1.0):** app name, executable `GeelyCarViewer`, menu entry `geely-car-viewer.desktop` (installer removes the old `ex5-viewer.desktop`), macOS bundle id. Kept the Python package `ex5viewer` and the config dir `ex5-viewer` so existing settings and logs carry over.
- **Drag-to-resize:** the window is resizable; 250 ms after a drag settles the layout rebuilds at the scale that fits (screens grow linearly, bars/chins/padding stay fixed, solved from the last layout and corrected once). Saved as `scale` (0.8–3.0); picking a size preset clears it. `minsize` = the layout at 0.8, because below that the top bar no longer fits.
- **Motion:** one `animate()` helper (Tk `after`, ~60 fps, ease-out cubic, same key retargets instead of queueing, instant when the "animations" setting is off). Switch knob 160 ms, segmented pill 180 ms, meter bars 350 ms, car panel numbers/battery fill/tires 400 ms, settings panel slides 14 px in 170 ms (Tk frames have no opacity), T-Box dialog fades via `-alpha` where a compositor exists, status dot pulses (1.2 s) while connecting/reconnecting.

- APK tab separates the local file, target head unit, and ADB output so users can verify the destination before installing and keep the result visible afterward.

- Install selected APKs sequentially on one ADB target, preserving each file result and continuing after individual errors.

- Give the APK queue the main workspace and group the target and ADB output in the sidebar.

- APK Launchpad shares one selection path for file picker and native drops, and measures progress by completed ADB attempts.

- HUD fills its assigned viewport, with decoder output matching that viewport to avoid a second aspect-fit shrink.

- Correct HUD fill: use its native 5:3 frame geometry and preserve source aspect during decoding and display, with letterboxing for differing sources.

- Make the firmware 1.3 ADB verifier override opt-in per session and restore the exact previous setting in a verified cleanup step.

- Prefer the unprivileged ADB shell for the Cluster relay because firmware 1.3 rejects su; retain the legacy relay as a handshake fallback.

- Publish release assets from a successful build matrix on the exact release commit. Tag creation does not publish partially built assets.

- If the native Tk drag-and-drop extension cannot load, keep the APK file picker available. The macOS release runner exposed an incompatible Tcl stubs mechanism.
