#!/bin/bash
# Builds the menu-bar app.
#   mac/build.sh                 -> build/Glowtrack.app, runs the server from this folder (for development)
#   mac/build.sh --dist          -> self-contained downloads: build/dist/Glowtrack-<design>.zip for
#                                   classic, a, b, c and d (server, Pillow and the Now Playing helper inside),
#                                   each one runs on Apple silicon and on Intel Macs
#   mac/build.sh --dist --theme c  -> just one design
set -euo pipefail
cd "$(dirname "$0")"
DIST=0; ONLY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dist) DIST=1 ;;
    --theme) ONLY="$2"; shift ;;
    *) echo "usage: build.sh [--dist [--theme classic|a|b|c|d]]"; exit 1 ;;
  esac
  shift
done

# The self-contained downloads carry a Pillow that runs on both chips (downloaded once, checked, cached)
PIL_UNIVERSAL="../build/cache"
if [[ "$DIST" == "1" && ! -d "$PIL_UNIVERSAL/PIL" ]]; then
  /usr/bin/python3 universal_pillow.py "$PIL_UNIVERSAL"
fi

build_app() {  # build_app <output .app> <embed 0|1> <default theme or empty>
  local APP="$1" EMBED="$2" THEME="$3"
  rm -rf "$APP"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  cp Info.plist "$APP/Contents/Info.plist"
  cp AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
  printf 'APPL????' > "$APP/Contents/PkgInfo"
  if [[ -n "$THEME" ]]; then
    /usr/libexec/PlistBuddy -c "Add :GoveeDefaultTheme string $THEME" "$APP/Contents/Info.plist"
  fi
  if [[ "$EMBED" == "1" ]]; then
    mkdir -p "$APP/Contents/Resources/server" "$APP/Contents/Resources/vendor"
    rsync -a --exclude '__pycache__' --exclude '*.pyc' ../server/ "$APP/Contents/Resources/server/"
    clang -dynamiclib -fobjc-arc -arch arm64 -arch x86_64 -mmacosx-version-min=13.0 -framework Foundation ../server/nowplaying/mr.m -o "$APP/Contents/Resources/server/nowplaying/libmr.dylib"
    cp -R "$PIL_UNIVERSAL/PIL" "$APP/Contents/Resources/vendor/PIL"
    find "$APP/Contents/Resources/vendor" -name '__pycache__' -prune -exec rm -rf {} +
  fi
  # One app for both kinds of Mac: build each chip's version and join them
  local TMPB; TMPB="$(mktemp -d)"
  for ARCH in arm64 x86_64; do
    swiftc -O -swift-version 5 -target "$ARCH-apple-macos13.0" \
      -framework AppKit -framework WebKit -framework ServiceManagement \
      main.swift -o "$TMPB/Glowtrack-$ARCH"
  done
  lipo -create "$TMPB/Glowtrack-arm64" "$TMPB/Glowtrack-x86_64" -output "$APP/Contents/MacOS/Glowtrack"
  rm -rf "$TMPB"
  codesign --force --deep --sign - "$APP"
}

if [[ "$DIST" == "0" ]]; then
  build_app "../build/Glowtrack.app" 0 ""
  echo "Built: $(cd ../build && pwd)/Glowtrack.app"
else
  OUT="../build/dist"; rm -rf "$OUT"; mkdir -p "$OUT"
  for T in classic a b c d; do
    if [[ -n "$ONLY" && "$ONLY" != "$T" ]]; then continue; fi
    build_app "$OUT/$T/Glowtrack.app" 1 "$T"
    (cd "$OUT/$T" && ditto -c -k --keepParent Glowtrack.app "../Glowtrack-$T.zip")
    echo "Built: $(cd "$OUT" && pwd)/Glowtrack-$T.zip"
  done
fi
