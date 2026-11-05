#!/bin/sh
# Add EX5 Viewer to the application menu (run once from the unpacked folder).
set -e
here=$(cd "$(dirname "$0")" && pwd)
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$apps"
cat > "$apps/ex5-viewer.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=EX5 Viewer
Comment=Mirror the Geely EX5 main screen, HUD and cluster
Exec="$here/EX5Viewer"
Icon=$here/icon.png
Terminal=false
Categories=Utility;
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$apps" || true
echo "EX5 Viewer added to the menu: $apps/ex5-viewer.desktop"
