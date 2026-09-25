# How each model stands on the ground, as the game's own levels have it.
#
#   python -m studio.extract.seats      -> "seat" in each model's size, models.json
#
# The build sets a model down on the lowest ground under its footprint, and how
# high its origin is above that ground is the model's own. A barracks, a power
# building or a garage has its origin at the ground and a foundation below it
# that is meant to be in the earth (11 m of it under a barracks); a tank or a
# car has its origin in its middle; the big warehouse stands 3.2 m into the
# ground, so its floor is the yard's. Set down by its lowest point, as the build
# did, a barracks stood 11 m in the air and the warehouse's doors 3 m up a wall.
#
# So the height is read from the levels: every copy of a model standing on open
# ground that is level under it - not inside or on top of something, not on a
# slope - and, where most of them agree, that is its seat (metres from the
# lowest ground under its footprint up to its origin). A model no level stands
# on the ground keeps the old rule: its lowest point on the ground
# (surface.seat_of). So do fences and walls, furniture, crates, lights, signs,
# roads and plants: a level sinks a wall to make a low one of it, or sets a
# fusebox into a bank, and a copy placed by hand is wanted whole.
import json, math, struct, sys, zlib

from studio import paths

DATA = paths.data()
SPACING = 1.5          # the build's footprint samples (surface.py under_footprint)
FLAT = 1.0             # a copy whose ground varies more than this under it is not read
AGREE = 0.25           # copies within this of each other agree
# the inventory's kinds of thing placed whole, on their lowest point (catalog.py)
WHOLE = {"fences", "furniture", "crates", "doors", "lights", "signs", "roads", "nature"}


class Grid:
    """The level's terrain as the editor has it (extract/terrain.py)."""

    def __init__(self, lv):
        self.m = m = json.loads((DATA / "terrain" / ("level%d.json" % lv)).read_text())
        raw = zlib.decompress((DATA / "terrain" / ("level%d.bin" % lv)).read_bytes())
        self.h = struct.unpack("<%dH" % (m["w"] * m["h"]), raw)

    def z(self, x, y):
        m = self.m
        gx, gy = (x - m["x0"]) / m["cell"], (y - m["y0"]) / m["cell"]
        if not (0 <= gx <= m["w"] - 1 and 0 <= gy <= m["h"] - 1):
            return None
        i, j = min(m["w"] - 2, int(gx)), min(m["h"] - 2, int(gy))
        fx, fy = gx - i, gy - j
        q = [self.h[(j + b) * m["w"] + i + a] for b in (0, 1) for a in (0, 1)]
        if any(v == m["nodata"] for v in q):
            return None
        a, b, c, d = (m["zmin"] + v * m["step"] for v in q)
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def _to_model(o, x, y):
    c, s = math.cos(o.get("gamma") or 0.0), math.sin(o.get("gamma") or 0.0)
    dx, dy = x - o["x"], y - o["y"]
    return dx * c + dy * s, -dx * s + dy * c


def _in_body(size, o, x, y):
    mx, my = _to_model(o, x, y)
    return any(r[0] <= mx <= r[0] + r[2] and r[1] <= my <= r[1] + r[3] for r in size["body"])


def ground_under(size, o, grid):
    """(lowest, highest) terrain under a model's footprint, or None."""
    c, s = math.cos(o.get("gamma") or 0.0), math.sin(o.get("gamma") or 0.0)
    zs = []
    for r in size["body"]:
        nx, ny = max(1, math.ceil(r[2] / SPACING)), max(1, math.ceil(r[3] / SPACING))
        for i in range(nx + 1):
            for j in range(ny + 1):
                mx, my = r[0] + r[2] * i / nx, r[1] + r[3] * j / ny
                z = grid.z(o["x"] + mx * c - my * s, o["y"] + mx * s + my * c)
                if z is not None:
                    zs.append(z)
    return (min(zs), max(zs)) if zs else None


def consensus(vals):
    """The height most copies agree on (the middle of the largest group within
    AGREE of each other), or None when no group is a majority."""
    vals = sorted(vals)
    best = []
    for i, v in enumerate(vals):
        grp = [w for w in vals[i:] if w - v <= AGREE]
        if len(grp) > len(best):
            best = grp
    if not best or len(best) * 2 <= len(vals):
        return None
    return best[len(best) // 2]


def main(argv):
    mp = DATA / "models.json"
    models = json.loads(mp.read_text())
    sizes = models.get("sizes", {})
    try:
        cat = json.loads((DATA / "catalog.json").read_text()).get("structures", [])
    except (OSError, ValueError):
        cat = []
    whole = {c.get("model") for c in cat if c.get("cat") in WHOLE}
    seen = {}
    for lv in range(1, 15):
        try:
            grid = Grid(lv)
        except (OSError, ValueError, zlib.error):
            print("level %2d: no terrain" % lv)
            continue
        objs = [o for o in json.loads((DATA / ("level%d.json" % lv)).read_text())["objects"]
                if o.get("type") in ("building", "prop") and not o.get("cutscene") and o.get("x") is not None
                and (sizes.get(o.get("model")) or {}).get("body")]
        read = 0
        for o in objs:
            size = sizes[o["model"]]
            g = ground_under(size, o, grid)
            if g is None or g[1] - g[0] > FLAT:
                continue
            # on or in something else - a crate on a crate, a desk in a house, a
            # hut on a platform - it stands on that, not on the ground
            on = False
            for q in objs:
                if q is o:
                    continue
                sq = sizes[q["model"]]
                bot = q["z"] + sq.get("z0", 0.0)
                if bot - 0.3 <= o["z"] <= bot + sq.get("h", 0.0) + 0.5 and _in_body(sq, q, o["x"], o["y"]):
                    on = True
                    break
            if on:
                continue
            seen.setdefault(o["model"], []).append(o["z"] - g[0])
            read += 1
        print("level %2d: %d of %d models on open, level ground" % (lv, read, len(objs)))
    changed, kept = [], 0
    for m, size in sizes.items():
        size.pop("seat", None)
        vals = seen.get(m) if m not in whole else None
        seat = consensus(vals) if vals else None
        if seat is None:
            continue
        z0, h = size.get("z0", 0.0), size.get("h", 0.0)
        old = -(z0 if z0 < -0.1 else 0.0)
        # buried whole (the tunnels under level 13), or above the ground in every
        # copy (a lamp on a ceiling): not a way of standing on the ground
        if seat + z0 + h < 0.5 or seat > old + 0.3:
            continue
        size["seat"] = round(seat, 3)
        kept += 1
        if abs(seat - old) > 0.3:
            changed.append((seat - old, m, len(vals)))
    mp.write_text(json.dumps(models, separators=(",", ":")))
    print("%d models have a seat read from the levels; %d stand differently from their lowest point:" % (kept, len(changed)))
    for d, m, n in sorted(changed)[:12]:
        print("  %-10s %+7.2f m (%d cop%s)" % (m, d, n, "y" if n == 1 else "ies"))


if __name__ == "__main__":
    main(sys.argv[1:])
