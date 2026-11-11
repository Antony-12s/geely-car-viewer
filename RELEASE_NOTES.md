## Geely Car Viewer 1.2.0

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

Full history: [CHANGELOG.md](https://github.com/Antony-12s/geely-car-viewer/blob/main/CHANGELOG.md)

| File | |
|---|---|
| `GeelyCarViewer-windows-x64.zip` | Windows 10/11 · SmartScreen may warn: More info → Run anyway |
| `GeelyCarViewer-linux-x86_64.tar.gz` | Ubuntu 22.04+ · run `./install-linux.sh` to add it to the app menu |
| `GeelyCarViewer-macos-arm64.zip` | Apple Silicon Mac · first launch: right-click → Open |

Requires adb enabled on the head unit. The cluster view needs root (`su`) on the head unit.

**What the app does on the car:**
- Car and T-Box data are read-only: the app only reads values, it never changes car settings.
- Touch control of Main is optional and **off by default**. Only when you turn on **Control Main** do clicks and drags on the picture go to the car screen as touches.
- Streaming starts temporary services while you watch: a scrcpy server on the head unit (its jar is copied to `/data/local/tmp` and removed when the server starts) and, for the cluster view, a capture session on the cluster (temporary files in `/tmp`, cleaned up by the next session). They stop when you disconnect or close the app.
