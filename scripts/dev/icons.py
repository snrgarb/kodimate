#!/usr/bin/env python3
"""Generate 48x48 RGBA PNG icons for the OSD button row.

White shapes on a fully transparent background, 8px padding (shapes fill a
32x32 area), rendered via 4x supersampling for soft anti-aliased edges. Pure
Python, no third-party deps: a minimal RGBA PNG writer plus a per-pixel
polygon rasteriser.

Usage: scripts/dev/icons.py
"""
import os
import struct
import zlib

SIZE = 48
SCALE = 4
BIG = SIZE * SCALE
PAD = 8 * SCALE  # 32x32 active area within the 48x48 canvas

OUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "resources", "skins", "Main", "media",
)


def write_png(path, width, height, pixels):
    """pixels: list of rows, each a list of (r, g, b, a) tuples."""
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # no filter
        for (r, g, b, a) in row:
            raw += bytes((r, g, b, a))

    def chunk(tag, data):
        c = tag + data
        return struct.pack("!I", len(data)) + c + struct.pack("!I", zlib.crc32(c))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    with open(path, "wb") as f:
        f.write(sig)
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))


def point_in_polygon(x, y, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def render(polygons):
    """Rasterise a list of polygons (each a list of (x, y) in 0..BIG coords)
    at supersample resolution, then box-downsample to SIZE x SIZE RGBA."""
    mask = bytearray(BIG * BIG)
    for y in range(BIG):
        py = y + 0.5
        for x in range(BIG):
            px = x + 0.5
            if any(point_in_polygon(px, py, poly) for poly in polygons):
                mask[y * BIG + x] = 1

    pixels = []
    for oy in range(SIZE):
        row = []
        for ox in range(SIZE):
            total = 0
            for sy in range(SCALE):
                base = (oy * SCALE + sy) * BIG + ox * SCALE
                total += sum(mask[base:base + SCALE])
            alpha = round(total * 255 / (SCALE * SCALE))
            row.append((255, 255, 255, alpha))
        pixels.append(row)
    return pixels


def triangle_right(x0, y0, x1):
    """Right-pointing triangle spanning x0..x1, vertically centred in the
    active area, full active-area height."""
    top = PAD
    bottom = BIG - PAD
    mid = (top + bottom) / 2
    return [(x0, top), (x0, bottom), (x1, mid)]


def triangle_left(x0, x1, y0=PAD, y1=BIG - PAD):
    mid = (y0 + y1) / 2
    return [(x1, y0), (x1, y1), (x0, mid)]


def bar(x0, x1, y0=PAD, y1=BIG - PAD):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def icon_play():
    return render([triangle_right(PAD, PAD, BIG - PAD)])


def icon_pause():
    active = BIG - 2 * PAD
    bar_w = active * 0.28
    gap = active * 0.2
    left0 = PAD + (active - 2 * bar_w - gap) / 2
    left1 = left0 + bar_w
    right0 = left1 + gap
    right1 = right0 + bar_w
    return render([bar(left0, left1), bar(right0, right1)])


def icon_rewind():
    active = BIG - 2 * PAD
    half = active / 2
    return render([
        triangle_left(PAD, PAD + half),
        triangle_left(PAD + half, PAD + active),
    ])


def icon_fastforward():
    active = BIG - 2 * PAD
    half = active / 2
    return render([
        triangle_right(PAD, PAD, PAD + half),
        triangle_right(PAD + half, PAD, PAD + active),
    ])


def icon_backtolive():
    active = BIG - 2 * PAD
    bar_w = active * 0.18
    gap = active * 0.12
    tri_w = active - bar_w - gap
    tri_x0 = PAD
    tri_x1 = tri_x0 + tri_w
    bar_x0 = tri_x1 + gap
    bar_x1 = bar_x0 + bar_w
    return render([
        triangle_right(tri_x0, tri_x0, tri_x1),
        bar(bar_x0, bar_x1),
    ])


ICONS = {
    "play.png": icon_play,
    "pause.png": icon_pause,
    "rewind.png": icon_rewind,
    "fastforward.png": icon_fastforward,
    "backtolive.png": icon_backtolive,
}


def main():
    for name, fn in ICONS.items():
        pixels = fn()
        path = os.path.join(OUT_DIR, name)
        write_png(path, SIZE, SIZE, pixels)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
