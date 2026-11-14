# Changelog

## 1.3.0

### New
- **Pop-out windows.** Main, HUD and Cluster can each open in their own resizable window that keeps the picture's aspect ratio. Main has a **Pop out** button in its side column; HUD and Cluster have an icon in their card header.
  - While a screen is popped out it is shown only in its window. Its place in the main window keeps the same size and shows "Opened in a window" with a **Dock back** button, so nothing jumps around.
  - Closing the window, pressing Escape, **Dock back**, disconnecting or quitting the app puts the screen back.
  - Popping out does not start a second stream: each stream is still decoded once.

### Changed
- **Car status moved to a column on the right of Main.** Battery and range, gear and speed, tire pressures, T-Box signal and GPS sit beside the main screen. In a small window the column hides the odometer and outside temperature lines so nothing overlaps.
- **Bigger HUD and Cluster.** With car status out of the tray, the tray holds only HUD and Cluster and both are about twice the area (HUD 240x144 at 1920x1080, was 170x102).
- The **Medium** size preset is a little smaller so it still fits a 1600x900 screen with the bigger tray. On a 1920x1080 screen the window opens at 1192x808. Drag the window corner to make it bigger.

### Fixed
- Linux: lower sustained graphics load, aimed at the Intel i915 freeze that could lock the whole desktop after a while:
  - Video is always decoded in software; the app refuses to use hardware decoding.
  - Linux safe rendering caps video at 8 fps (was 12) and refreshes the window every 125 ms.
  - The picture is drawn into reused buffers instead of new ones for every frame.
- When the car drops off the network, failed reconnects now wait 4, 8, 16, then 30 seconds instead of retrying every few seconds. A stream that was live and then dropped still retries after 1 second (Main/HUD) or 2 seconds (Cluster).

## 1.2.0

Everything from 1.1.2 and 1.1.3 (APK install tab, HUD aspect ratio, Cluster on firmware 1.3, Linux safe rendering) is kept; the window around it is new.

### New
- **OLED Cinema layout**, now the default. A true-black window built around the car's main screen:
  - **Main stage:** the main screen is the largest picture, centred, with its title, the **Control Main** switch and live stream details in the side columns
  - **Aux tray** under the stage: HUD, Cluster and the car data card (battery and range, gear and speed, odometer, outside temperature, tire pressures, T-Box signal and carrier) side by side, always visible
  - **System floor** at the bottom: PC and car CPU / GPU / RAM, and the network traffic of this app only
- Clear view / control modes: with **Control Main** off (the default) clicks on the picture stay on the PC; when on, click and drag on Main touches the car screen. Only Main accepts touches.

### Changed
- The **APK** tab moved into the top bar, next to **Connect**. It opens the install workspace in place of the screens; the connection bar and the system floor stay visible. **Screens** goes back.
- The 1.1.2 Telemetry window layout is replaced by OLED Cinema. Its colours remain as the **Telemetry** theme in ⚙ Settings. Saved settings are kept: if your settings were saved by 1.1.2 or 1.1.3, the new layout opens in the Telemetry colours until you pick **OLED** under ⚙ Settings → Theme.
- Car data and T-Box status no longer hide behind a **Vehicle info** button: they sit in the tray. ⚙ **Car panel** still turns the card off.
- HUD and Cluster sit side by side at the same height. The HUD keeps its source aspect ratio (from 1.1.2).
- RAM shows used / total again (for example `12.8/31G`).
- Drag-to-resize, size presets and all settings work as before and carry over from 1.1.x.
- The settings panel drops down right under the ⚙ button.

### Fixed
- Cluster (JPEG mode): frames lagged by several seconds and, with long refresh times, the stream could time out and reconnect without ever showing a frame. Frames now show as soon as they arrive.
- Disconnect, closing the window, or changing a stream setting could freeze the window for several seconds on a slow Wi-Fi link. Stream cleanup now runs in the background.
- One unexpected error could silently stop the picture and the meters for good. The app now logs the error and keeps running.
- Typing a wrong IP (or connecting by USB with no device) while connected stopped the streams but still showed "Live". The address is now checked first, and a working session is kept.
- After a quick reconnect or a setting change, a late frame or status from the old stream could appear in the new session. Old streams can no longer update the screen.
- Touch and drag on Main no longer stutter the whole window when the Wi-Fi link is congested; touch start and end are never dropped.
- APK tab: long sentences in the target card were cut off in a small window. They now wrap.
- The app starts even when the native drag-and-drop module is missing; the APK tab then uses the file picker.

## 1.1.3

- Default to lower graphics load on Linux after Intel i915 reset failures. Request software GL, disable app animations, limit video to 12 fps, and wait for the user to connect.

## 1.1.2
- Add APK Launchpad with multi-file drag and drop, batch progress, and optional temporary verifier handling for firmware 1.3.
- Preserve HUD aspect ratio and prefer the regular ADB shell for Cluster capture.

- Add the Telemetry theme and reorganize connection controls, separate PC/car metrics, persistent T-Box carrier status, and expandable vehicle details. HUD stays above the larger cluster viewport.

- Disable host GPU telemetry on Linux while investigating system hangs associated with Intel i915 reset failures. Host CPU and RAM metrics and vehicle GPU metrics still update.

## 1.1.1

### New
- **Resize by dragging** the window corner (or maximise). The screens and car panel rescale to fit, and the size is remembered. Picking a size preset in ⚙ Settings goes back to that size.
- **Motion** across the app:
  - switches slide, and the selected option in segmented controls glides to the new choice
  - CPU / GPU / RAM bars and the car panel numbers (battery, range, speed, tires) count smoothly to new values
  - the status dot pulses while connecting or reconnecting
  - the settings panel slides in; the T-Box info window fades in (where the desktop supports transparency)
  - ⚙ Settings → **Animations** turns it all off for slow computers

### Notes
- The smallest drag size is the "small" preset (~1000 × 676); below that the top bar no longer fits.
- The car GPU figure is for the whole GPU (Mali-G76, 10 cores), as busy time at the current clock. Read it together with the MHz shown next to it.

## 1.1.0 — Geely Car Viewer

New name: **EX5 Viewer → Geely Car Viewer**. Existing settings carry over.

### New
- **Car panel** under the top bar (can be hidden in ⚙ "Car panel")
  - battery % and range, matching the car's cluster; "Charging X kW" when plugged in
  - gear P/R/N/D, speed, odometer
  - tire pressure for all 4 wheels on a top-view car; a wheel turns yellow when low, high, or 3 psi off the others
  - outside temperature as shown on the cluster
- **T-Box (the car's 4G box)**
  - 4G signal bars and the real carrier from the eSIM (e.g. TrueMove H)
  - T-Box GPS: heading while driving, "parked" while parked, and a **Map ↗** button that opens Google Maps
  - data the car uses through the T-Box: current rate and total since the car started
  - **T-Box info ⓘ**: box part and firmware numbers, eSIM ICCID, IMEI (masked until "Show numbers"; click a value to copy)
- **GPU clock** next to GPU % for both the PC and the car (e.g. `64% 850M`)
- **"Auto" window size** (default): medium, or small when the screen is too small

### Improved
- New look across the app: one rounded card style, aligned columns, larger readable numbers, clear empty states
- Medium and large windows are 10% bigger
- Faster cluster view: JPEG frames of ~20 KB instead of a 4 MB BMP; a 0.5 s refresh really gives ~1.7 frames/s

### Fixed
- Car GPU always showed "–"
- Opening and closing the cluster view left processes and a 4 MB file behind on the car
- The cluster connection broke on close, so reconnecting failed for a while
- The T-Box carrier showed "China Mobile" by mistake
- The PC (Intel) GPU clock kept disappearing
- While the car powers down, the CPU / ping meters no longer freeze

## 1.0.0
- First release: main screen + HUD + cluster in one window, Wi-Fi / USB connection, main screen touch control, network graph, PC and car CPU / GPU / RAM, settings, EX5 / EX2 model choice
