## Geely Car Viewer 1.1.3

Linux now starts in a reduced graphics mode after a desktop freeze was observed alongside an Intel i915 GPU reset failure. This mode requests software OpenGL, disables app animations, and caps live video at 12 fps. Open the app and click **Connect** to start streaming. Windows and macOS continue to use their normal rendering settings.

> [!WARNING]
> Graphics driver compatibility varies by machine. This release reduces graphics load, but a fix for the observed driver freeze has not been confirmed in an extended live session.

| Download | Platform |
|---|---|
| `GeelyCarViewer-windows-x64.zip` | Windows x64 |
| `GeelyCarViewer-macos-arm64.zip` | macOS on Apple Silicon, ad-hoc signed |
| `GeelyCarViewer-linux-x86_64.tar.gz` | Linux x86-64, built on Ubuntu 22.04 |

ADB must be enabled on the head unit. The packages include the ADB binary.
