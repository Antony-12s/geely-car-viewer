# Changelog

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
