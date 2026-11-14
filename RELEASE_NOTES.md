## Geely Car Viewer 1.3.0

Pop-out windows, car status beside the main screen, a bigger HUD, and lower graphics load on Linux.

### New
- **Pop-out windows.** Main, HUD and Cluster can each open in their own resizable window that keeps the picture's aspect ratio. Main has a **Pop out** button in its side column; HUD and Cluster have an icon in their card header.
  - While a screen is popped out it is shown only in its window. Its place in the main window keeps the same size and shows "Opened in a window" with a **Dock back** button.
  - Closing the window, pressing Escape, **Dock back**, disconnecting or quitting puts the screen back.
  - Popping out does not start a second stream.

### Changed
- **Car status is now a column on the right of Main** (battery and range, gear and speed, tire pressures, T-Box signal, GPS). In a small window it hides the odometer and outside temperature lines.
- **Bigger HUD and Cluster:** the tray under Main holds only these two, at about twice the area.
- The **Medium** size preset is a little smaller so it still fits a 1600x900 screen. Drag the window corner to make it bigger.

### Fixed
- Linux: lower sustained graphics load, aimed at the Intel i915 freeze that could lock the whole desktop: software video decoding only, 8 fps in safe rendering (was 12), and reused picture buffers.
- When the car drops off the network, failed reconnects back off to 4, 8, 16, then 30 seconds instead of retrying every few seconds.

> [!WARNING]
> Linux still starts in reduced graphics mode (software OpenGL, no app animations, video capped at 8 fps, no auto-connect: click **Connect**). The changes above lower the load behind the observed Intel i915 freeze, but the fix has not yet been confirmed in an extended live session. `--no-linux-safe-rendering` turns the mode off.

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
