## Geely Car Viewer 1.1.2

- Add the Telemetry theme and reorganize connection controls, separate PC/car metrics, persistent T-Box carrier status, and expandable vehicle details. HUD stays above the larger cluster viewport.

Host GPU telemetry is disabled on Linux as a precaution after system hangs with Intel i915 reset failures. Host CPU and RAM metrics and vehicle GPU metrics still update.

Full history: [CHANGELOG.md](https://github.com/Antony-12s/geely-car-viewer/blob/main/CHANGELOG.md)

| File | |
|---|---|
| `GeelyCarViewer-windows-x64.zip` | Windows 10/11 · SmartScreen may warn: More info → Run anyway |
| `GeelyCarViewer-linux-x86_64.tar.gz` | Ubuntu 22.04+ · run `./install-linux.sh` to add it to the app menu |
| `GeelyCarViewer-macos-arm64.zip` | Apple Silicon Mac · first launch: right-click → Open |

Requires adb enabled on the head unit. The cluster view needs root (`su`) on the head unit. Car and T-Box data are read-only; nothing is sent to the car.
