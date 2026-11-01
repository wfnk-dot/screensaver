#!/bin/bash
# Double-click to build the screensaver, install it with the loops, and open
# Screen Saver settings. Safe to run again after adding new loops.

set -e
cd "$(dirname "$0")"

SAVERS="$HOME/Library/Screen Savers"
VIDEOS="$SAVERS/Screensaver Videos"
BUILD="build"
SAVER="$BUILD/Screensaver.saver"

echo "Building the screensaver..."

if ! xcrun --find swiftc >/dev/null 2>&1; then
    echo
    echo "This Mac needs Apple's free developer tools first."
    echo "A window will open: click Install, wait for it to finish,"
    echo "then double-click 'Install Screensaver' again."
    xcode-select --install || true
    exit 1
fi

rm -rf "$SAVER"
mkdir -p "$SAVER/Contents/MacOS" "$SAVER/Contents/Resources"
cp screensaver-app/Info.plist "$SAVER/Contents/Info.plist"

for arch in arm64 x86_64; do
    xcrun swiftc -O -parse-as-library -emit-library \
        -target "$arch-apple-macos13.0" \
        -module-name Screensaver \
        -framework ScreenSaver -framework AVFoundation -framework AppKit \
        -Xlinker -bundle \
        -o "$BUILD/Screensaver-$arch" \
        screensaver-app/LoopSaverView.swift
done
lipo -create "$BUILD/Screensaver-arm64" "$BUILD/Screensaver-x86_64" \
    -output "$SAVER/Contents/MacOS/Screensaver"
rm -f "$BUILD"/Screensaver-arm64 "$BUILD"/Screensaver-x86_64
codesign --force --sign - "$SAVER"

echo "Installing..."

# Quit any screensaver still running so the new version is picked up.
killall legacyScreenSaver 2>/dev/null || true
killall "legacyScreenSaver (Wallpaper)" 2>/dev/null || true

mkdir -p "$SAVERS" "$VIDEOS"
rm -rf "$SAVERS/Screensaver.saver"
cp -R "$SAVER" "$SAVERS/"
for f in loops/*.mp4; do
    [ -e "$f" ] && cp -f "$f" "$VIDEOS/"
done

echo
echo "Done. In the window that opens, pick 'Screensaver'."
echo "Click 'Options...' to choose which loop plays on each screen."
open "x-apple.systempreferences:com.apple.ScreenSaver-Settings.extension" \
    || open -b com.apple.systempreferences
