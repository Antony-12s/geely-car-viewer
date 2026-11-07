## Geely Car Viewer 1.1.2

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
