# Changelog

## 1.2.0

### New
- **OLED Cinema layout.** A true-black window built around the car's main screen:
  - **Main stage:** the main screen is the largest picture, centred, with its title, the **Control Main** switch and live stream details in the side columns
  - **Aux tray** under the stage: HUD, Cluster and the car data card (battery and range, gear and speed, odometer, outside temperature, tire pressures) side by side
  - **System floor** at the bottom: PC and car CPU / GPU / RAM, and the network traffic of this app only
- Clear view / control modes: with **Control Main** off (the default) clicks on the picture stay on the PC; when on, click and drag on Main touches the car screen. Only Main accepts touches.

### Better
- Drag-to-resize, size presets and all settings work as before and carry over from 1.1.x.
- The settings panel drops down right under the ⚙ button.

### Fixed
- Cluster (JPEG mode): frames lagged by several seconds and, with long refresh times, the stream could time out and reconnect without ever showing a frame. Frames now show as soon as they arrive.
- Disconnect, closing the window, or changing a stream setting could freeze the window for several seconds on a slow Wi-Fi link. Stream cleanup now runs in the background.
- One unexpected error could silently stop the picture and the meters for good. The app now logs the error and keeps running.
- Typing a wrong IP (or connecting by USB with no device) while connected stopped the streams but still showed "Live". The address is now checked first, and a working session is kept.
- After a quick reconnect or a setting change, a late frame or status from the old stream could appear in the new session. Old streams can no longer update the screen.
- Touch and drag on Main no longer stutter the whole window when the Wi-Fi link is congested; touch start and end are never dropped.

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
