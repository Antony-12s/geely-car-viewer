## Geely Car Viewer 1.1.2

> [!WARNING]
> **Graphics driver compatibility:** The app may crash or the desktop may freeze on some graphics driver configurations. A system freeze with an Intel `i915` GPU reset failure was observed on Linux while the app was open, even with host GPU polling disabled. The exact trigger has not been confirmed. The Linux safe rendering workaround is not included in the v1.1.2 download.

- Telemetry dashboard with separate PC and vehicle metrics, T-Box carrier status, and expandable vehicle details.
- English is the default for new installations. Thai remains available in settings.
- APK Launchpad with drag and drop on supported systems and a file picker on all platforms, multiple-file installation, batch progress, and per-file ADB results. The optional firmware 1.3 mode temporarily pauses ADB APK verification and checks that the previous setting is restored.
- HUD preserves the source aspect ratio. Cluster connects through the regular ADB shell first, with the previous relay available as a fallback.
- Linux host GPU polling is disabled after Intel i915 reset failures. Vehicle GPU telemetry remains available.

| Download | Platform |
|---|---|
| `GeelyCarViewer-windows-x64.zip` | Windows x64 |
| `GeelyCarViewer-macos-arm64.zip` | macOS on Apple Silicon, ad-hoc signed |
| `GeelyCarViewer-linux-x86_64.tar.gz` | Linux x86-64, built on Ubuntu 22.04 |

ADB must be enabled on the head unit. The packages include the ADB binary.
