## Geely Car Viewer 1.2.0

A new window layout, plus six stability fixes. Everything added in 1.1.2 and 1.1.3 is still here: the APK install tab, the HUD aspect ratio fix, Cluster on firmware 1.3, and Linux safe rendering.

### New
- **OLED Cinema layout**, now the default. A true-black window built around the car's main screen:
  - **Main stage:** the main screen is the largest picture, centred, with its title, the **Control Main** switch and live stream details in the side columns
  - **Aux tray** under the stage: HUD, Cluster and the car data card (battery and range, gear and speed, odometer, outside temperature, tire pressures, T-Box signal and carrier) side by side, always visible
  - **System floor** at the bottom: PC and car CPU / GPU / RAM, and the network traffic of this app only
- Clear view / control modes: with **Control Main** off (the default) clicks on the picture stay on the PC; when on, click and drag on Main touches the car screen. Only Main accepts touches.

### Changed
- The **APK** tab is in the top bar, next to **Connect**. It opens the install workspace in place of the screens; **Screens** goes back.
- The 1.1.2 Telemetry window layout is replaced by OLED Cinema. Its colours remain as the **Telemetry** theme in ⚙ Settings. Saved settings are kept: if your settings were saved by 1.1.2 or 1.1.3, the new layout opens in the Telemetry colours until you pick **OLED** under ⚙ Settings → Theme.
- Car data and T-Box status are always visible in the tray (no **Vehicle info** button). HUD and Cluster sit side by side.
- Drag-to-resize, size presets and all settings carry over from 1.1.x.

### Fixed
- Cluster (JPEG mode): frames lagged by several seconds and, with long refresh times, the stream could time out and reconnect without ever showing a frame. Frames now show as soon as they arrive.
- Disconnect, closing the window, or changing a stream setting could freeze the window for several seconds on a slow Wi-Fi link. Stream cleanup now runs in the background.
- One unexpected error could silently stop the picture and the meters for good. The app now logs the error and keeps running.
- Typing a wrong IP (or connecting by USB with no device) while connected stopped the streams but still showed "Live". The address is now checked first, and a working session is kept.
- After a quick reconnect or a setting change, a late frame or status from the old stream could appear in the new session. Old streams can no longer update the screen.
- Touch and drag on Main no longer stutter the whole window when the Wi-Fi link is congested; touch start and end are never dropped.

> [!WARNING]
> Linux still starts in the reduced graphics mode from 1.1.3 (software OpenGL, no app animations, video capped at 12 fps, no auto-connect: click **Connect**). Graphics driver compatibility varies by machine; a fix for the observed Intel i915 freeze has not been confirmed in an extended live session. `--no-linux-safe-rendering` turns the mode off.

Full history: [CHANGELOG.md](https://github.com/Antony-12s/geely-car-viewer/blob/main/CHANGELOG.md)

| Download | Platform |
|---|---|
| `GeelyCarViewer-windows-x64.zip` | Windows x64 |
| `GeelyCarViewer-macos-arm64.zip` | macOS on Apple Silicon, ad-hoc signed |
| `GeelyCarViewer-linux-x86_64.tar.gz` | Linux x86-64, built on Ubuntu 22.04 |

ADB must be enabled on the head unit. The packages include the ADB binary. The cluster view uses the regular ADB shell and falls back to `su` on head units that need it.

**What the app does on the car:**
- Car and T-Box data are read-only: the app only reads values, it never changes car settings.
- Touch control of Main is optional and **off by default**. Only when you turn on **Control Main** do clicks and drags on the picture go to the car screen as touches.
- Streaming starts temporary services while you watch: a scrcpy server on the head unit (its jar is copied to `/data/local/tmp` and removed when the server starts) and, for the cluster view, a capture session on the cluster (temporary files in `/tmp`, cleaned up by the next session). They stop when you disconnect or close the app.
- The **APK** tab installs apps on the head unit, and only when you click **Install on vehicle** (`adb install -r`: an existing app is replaced and keeps its data). The optional firmware 1.3 checkbox turns the head unit's ADB install verification off for that batch and restores the previous value afterwards.
