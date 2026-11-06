## Geely Car Viewer 1.1.1


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

Full history: [CHANGELOG.md](https://github.com/Antony-12s/geely-car-viewer/blob/main/CHANGELOG.md)

| File | |
|---|---|
| `GeelyCarViewer-windows-x64.zip` | Windows 10/11 · SmartScreen may warn: More info → Run anyway |
| `GeelyCarViewer-linux-x86_64.tar.gz` | Ubuntu 22.04+ · run `./install-linux.sh` to add it to the app menu |
| `GeelyCarViewer-macos-arm64.zip` | Apple Silicon Mac · first launch: right-click → Open |

Requires adb enabled on the head unit. The cluster view needs root (`su`) on the head unit. Car and T-Box data are read-only; nothing is sent to the car.
