# Draws the app's icon, in the editor's own colours, with nothing but the
# standard library: a map computer's screen with a grid, a range ring, a
# crosshair and one yellow marker.
#
#   python app/tools/make-icon.py        writes app/build/icon.png (256 x 256)
#                                        and app/build/icon.ico (16 to 256)
import math, pathlib, struct, zlib

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "build"

GROUND = (0x08, 0x18, 0x0a)
SURFACE = (0x0e, 0x2a, 0x12)
GRID = (0x1b, 0x4a, 0x22)
LINE = (0x2a, 0x6b, 0x33)
PHOSPHOR = (0x8d, 0xff, 0x9a)
ACCENT = (0xff, 0xd2, 0x4a)


def render(size):
    """RGBA rows, drawn at 4x and averaged down so edges are smooth."""
    ss = 4
    n = size * ss
    px = [[(0, 0, 0, 0)] * n for _ in range(n)]
    c = n / 2.0
    r_box = n * 0.47                   # the screen
    corner = n * 0.16
    for y in range(n):
        for x in range(n):
            # inside the rounded square?
            dx = max(abs(x + 0.5 - c) - (r_box - corner), 0)
            dy = max(abs(y + 0.5 - c) - (r_box - corner), 0)
            if dx * dx + dy * dy > corner * corner:
                continue
            col = GROUND
            # a soft glow toward the middle
            d = math.hypot(x + 0.5 - c, y + 0.5 - c) / (n * 0.5)
            mix = max(0.0, 1.0 - d) * 0.55
            col = tuple(int(g + (s - g) * mix) for g, s in zip(GROUND, SURFACE))
            # grid every eighth of the screen
            step = n / 8.0
            if min((x % step), step - (x % step)) < ss * 0.9 or min((y % step), step - (y % step)) < ss * 0.9:
                col = GRID
            # the screen's rim
            edge = math.hypot(dx, dy) if (dx or dy) else min(r_box - abs(x + 0.5 - c), r_box - abs(y + 0.5 - c)) + corner
            if (dx or dy) and corner - math.hypot(dx, dy) < ss * 3.2:
                col = LINE
            elif not (dx or dy) and edge - corner < ss * 3.2:
                col = LINE
            # range ring and crosshair
            rr = math.hypot(x + 0.5 - c, y + 0.5 - c)
            if abs(rr - n * 0.30) < ss * 1.6:
                col = PHOSPHOR
            if abs(rr - n * 0.16) < ss * 1.0:
                col = LINE
            if (abs(x + 0.5 - c) < ss * 1.2 or abs(y + 0.5 - c) < ss * 1.2) and rr < n * 0.40:
                col = PHOSPHOR
            px[y][x] = col + (255,)
    # the marker: a yellow triangle, up and to the right of the middle
    mx, my, ms = c + n * 0.13, c - n * 0.15, n * 0.075
    for y in range(n):
        for x in range(n):
            u, v = (x + 0.5 - mx) / ms, (y + 0.5 - my) / ms
            if -1.0 <= v <= 0.8 and abs(u) <= (v + 1.0) * 0.62:
                px[y][x] = ACCENT + (255,)
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            acc = [0, 0, 0, 0]
            for yy in range(ss):
                for xx in range(ss):
                    p = px[y * ss + yy][x * ss + xx]
                    a = p[3]
                    acc[0] += p[0] * a
                    acc[1] += p[1] * a
                    acc[2] += p[2] * a
                    acc[3] += a
            a = acc[3]
            row.append((acc[0] // a, acc[1] // a, acc[2] // a, a // (ss * ss)) if a else (0, 0, 0, 0))
        rows.append(row)
    return rows


def png(rows):
    size = len(rows)
    raw = b"".join(b"\x00" + b"".join(bytes(p) for p in row) for row in rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(pngs):
    """An .ico holding PNG images, which Windows has read since Vista."""
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, data in pngs:
        s = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", s, s, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return head + entries + blobs


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    big = png(render(256))
    (OUT / "icon.png").write_bytes(big)
    sizes = [(s, png(render(s))) for s in (16, 24, 32, 48, 64, 128)] + [(256, big)]
    (OUT / "icon.ico").write_bytes(ico(sizes))
    print("wrote %s and %s" % (OUT / "icon.png", OUT / "icon.ico"))
