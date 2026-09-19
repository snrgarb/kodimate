#!/bin/sh
# Renders the Live TV remote-hint bar's SVG icon sources to PNG via headless
# Chrome (no PIL/rsvg available). Each hint_*.svg's width/height attributes
# set the render size (2x the size displayed in the skin, for crispness).
set -e

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$SCRIPT_DIR/../../resources/skins/Main/media/src"
OUT_DIR="$SCRIPT_DIR/../../resources/skins/Main/media"

[ -x "$CHROME" ] || { echo "Chrome not found at $CHROME" >&2; exit 1; }

for svg in "$SRC_DIR"/hint_*.svg; do
    name="$(basename "$svg" .svg)"
    width=$(sed -n 's/.*width="\([0-9]*\)".*/\1/p' "$svg" | head -1)
    height=$(sed -n 's/.*height="\([0-9]*\)".*/\1/p' "$svg" | head -1)
    if [ -z "$width" ] || [ -z "$height" ]; then
        echo "Could not read width/height from $svg" >&2
        exit 1
    fi
    out="$OUT_DIR/$name.png"
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
        --default-background-color=00000000 \
        --window-size="${width},${height}" \
        --screenshot="$out" "file://$svg"
    echo "wrote $out"
done
