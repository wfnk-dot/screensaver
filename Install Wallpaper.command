#!/bin/bash
# Double-click to build the moving wallpaper, install it with the loops, and
# start it. It starts by itself at login. Safe to run again after adding loops.

set -e
cd "$(dirname "$0")"

APPS="$HOME/Applications"
VIDEOS="$HOME/Library/Screen Savers/Screensaver Videos"
BUILD="build"
APP="$BUILD/Wallpaper.app"

echo "Building the wallpaper..."

if ! xcrun --find swiftc >/dev/null 2>&1; then
    echo
    echo "This Mac needs Apple's free developer tools first."
    echo "A window will open: click Install, wait for it to finish,"
    echo "then double-click 'Install Wallpaper' again."
    xcode-select --install || true
    exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp wallpaper-app/Info.plist "$APP/Contents/Info.plist"

for arch in arm64 x86_64; do
    xcrun swiftc -O -parse-as-library \
        -target "$arch-apple-macos13.0" \
        -framework AVFoundation -framework AppKit -framework ServiceManagement \
        -o "$BUILD/Wallpaper-$arch" \
        wallpaper-app/WallpaperApp.swift
done
lipo -create "$BUILD/Wallpaper-arm64" "$BUILD/Wallpaper-x86_64" \
    -output "$APP/Contents/MacOS/Wallpaper"
rm -f "$BUILD"/Wallpaper-arm64 "$BUILD"/Wallpaper-x86_64
codesign --force --sign - "$APP"

echo "Installing..."

pkill -x Wallpaper 2>/dev/null || true
mkdir -p "$APPS" "$VIDEOS"
rm -rf "$APPS/Wallpaper.app"
cp -R "$APP" "$APPS/"
for f in loops/*.mp4; do
    [ -e "$f" ] && cp -f "$f" "$VIDEOS/"
done

sleep 1
open "$APPS/Wallpaper.app"

echo
echo "Done. The wallpaper is running and will start by itself at login."
echo "To stop it, click the moon in the menu bar and choose Quit Wallpaper."
