#!/bin/bash
# Builds "Glowtrack.app" (the menu-bar app) into ../build/
set -euo pipefail
cd "$(dirname "$0")"
APP="../build/Glowtrack.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp Info.plist "$APP/Contents/Info.plist"
cp AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
printf 'APPL????' > "$APP/Contents/PkgInfo"
swiftc -O -swift-version 5 -target arm64-apple-macos13.0 \
  -framework AppKit -framework WebKit -framework ServiceManagement \
  main.swift -o "$APP/Contents/MacOS/Glowtrack"
codesign --force --sign - "$APP"
echo "Built: $(cd "$(dirname "$APP")" && pwd)/$(basename "$APP")"
