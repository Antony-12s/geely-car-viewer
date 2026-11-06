#!/bin/sh
# Add Geely Car Viewer to the application menu (run once from the unpacked folder).
set -e
here=$(cd "$(dirname "$0")" && pwd)
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$apps"
rm -f "$apps/ex5-viewer.desktop"  # menu entry of the old name (EX5 Viewer)
cat > "$apps/geely-car-viewer.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Geely Car Viewer
Comment=Geely EX5 screens, car data and T-Box on your computer
Exec="$here/GeelyCarViewer"
Icon=$here/icon.png
Terminal=false
Categories=Utility;
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$apps" || true
echo "Geely Car Viewer added to the menu: $apps/geely-car-viewer.desktop"
