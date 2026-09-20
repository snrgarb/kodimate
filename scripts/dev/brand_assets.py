#!/usr/bin/env python3
"""Generate the addon's brand assets: icon.png and fanart.jpg.

Pure Python (stdlib only): a minimal RGBA PNG writer plus a per-pixel
polygon rasteriser, following the same approach as scripts/dev/icons.py.

Writes icon.png (256x256) and fanart.png (1280x720) at the repo root, a
dark background with a simple white play-triangle glyph, then converts
fanart.png to fanart.jpg via macOS `sips` and removes the intermediate
PNG. The JPEG conversion step is macOS-only (requires `sips`); on other
platforms fanart.png is left in place and must be converted separately.

Usage: scripts/dev/brand_assets.py
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from icons import write_png, point_in_polygon  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

BG = (30, 33, 41)  # flat dark background


def play_glyph(cx, cy, size):
    """A right-pointing triangle centred at (cx, cy), `size` tall."""
    half = size / 2
    return [(cx - half * 0.6, cy - half), (cx - half * 0.6, cy + half), (cx + half * 0.8, cy)]


def render(width, height, glyph_polys):
    pixels = []
    for y in range(height):
        row = []
        for x in range(width):
            px, py = x + 0.5, y + 0.5
            if any(point_in_polygon(px, py, poly) for poly in glyph_polys):
                row.append((255, 255, 255, 255))
            else:
                row.append(BG + (255,))
        pixels.append(row)
    return pixels


def build_icon(path):
    size = 256
    glyph = play_glyph(size / 2, size / 2, size * 0.5)
    write_png(path, size, size, render(size, size, [glyph]))


def build_fanart_png(path):
    width, height = 1280, 720
    size = min(width, height) * 0.28
    glyph = play_glyph(width / 2, height / 2, size)
    write_png(path, width, height, render(width, height, [glyph]))


def main():
    icon_path = os.path.join(REPO_ROOT, "icon.png")
    fanart_png_path = os.path.join(REPO_ROOT, "fanart.png")
    fanart_jpg_path = os.path.join(REPO_ROOT, "fanart.jpg")

    build_icon(icon_path)
    build_fanart_png(fanart_png_path)

    if sys.platform == "darwin" and shutil.which("sips"):
        subprocess.run(
            ["sips", "-s", "format", "jpeg", fanart_png_path, "--out", fanart_jpg_path],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        os.remove(fanart_png_path)
    else:
        print(
            "sips not available (macOS-only step): leaving fanart.png in place; "
            "convert it to fanart.jpg manually."
        )

    print("wrote %s" % icon_path)
    if os.path.exists(fanart_jpg_path):
        print("wrote %s" % fanart_jpg_path)


if __name__ == "__main__":
    main()
