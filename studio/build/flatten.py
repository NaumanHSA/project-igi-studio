# Flatten the ground under new buildings, the way the level designers did:
# with height maps.
#
# A "HeightMap" task (in the Static container) lays item <Bitmap ID> of
# terrain/terrain.hmp over the octree cube of its <Level> that holds its
# position. Each item is a (size+1)^2 grid of bytes, 0..127; the terrain's
# vertices inside the cube move up or down by (value - 64) / 16 m, bilinear
# between samples. Where several cover a point, the one created last wins
# (studio/build/terrain.py, ported from the game's own height query). So a pad is:
#
#   1. the 64 m cubes (level 13, 129 x 129 samples every 0.5 m) that the
#      building's footprint and apron touch;
#   2. each starting from the heights the level already applies there, so an
#      existing height map is carried over rather than lost;
#   3. inside the footprint plus FLAT metres, the ground set to one height (the
#      median of the ground there, so as little is cut or filled as possible);
#      over the next BLEND metres, eased back to the ground as it was;
#   4. a new terrain.hmp item and a HeightMap task after the level's own.
#
# One sample moves the ground by at most about 4 m either way; a pad that needs
# more is flattened as far as it can be and reported.
#
#   hmp = read_hmp(path); write_hmp(path, hmp)
#   pads = [pad_for(building, sizes, terrain), ...]
#   patches, notes = build_patches(terrain, pads, first_free_id(hmp))
#   add_items(hmp, patches); register(terrain, patches); qsc = add_tasks(qsc, patches)
import math, struct

SCALE = 4096.0
LOD = 13                      # 64 m cubes
SIZE = 128                    # 129 x 129 samples, 0.5 m apart
FLAT = 1.5                    # metres of level ground around the footprint
BLEND = 4.0                   # metres over which it eases back
STEP = 1.0 / 16.0             # metres per height map value
SLOTS = 256


# ------------------------------------------------------------------ terrain.hmp
def read_hmp(path):
    b = open(path, "rb").read()
    heads = [list(struct.unpack_from("<III", b, i * 12)) for i in range(SLOTS)]
    items, off = {}, SLOTS * 12
    for i, h in enumerate(heads):
        if h[2]:
            n = (h[2] + 1) ** 2
            items[i] = bytearray(b[off:off + n])
            off += n
    if off != len(b):
        raise ValueError("%s: %d bytes left over after the height maps" % (path, len(b) - off))
    return {"heads": heads, "items": items}


def empty_hmp():
    return {"heads": [[0, 0, 0] for _ in range(SLOTS)], "items": {}}


def write_hmp(path, hmp):
    out = bytearray()
    for h in hmp["heads"]:
        out += struct.pack("<III", *h)
    for i in range(SLOTS):
        if hmp["heads"][i][2]:
            out += hmp["items"][i]
    open(path, "wb").write(bytes(out))


def first_free_id(hmp):
    used = [i for i, h in enumerate(hmp["heads"]) if h[2]]
    return (max(used) + 1) if used else 0


def add_items(hmp, patches):
    """New items after the existing ones. The header's first field is a pointer
    the level editor saved (each item's is the previous one's plus its length);
    new ones carry the pattern on."""
    heads = hmp["heads"]
    last = max((i for i, h in enumerate(heads) if h[2]), default=None)
    ptr = heads[last][0] + (heads[last][2] + 1) ** 2 if last is not None else 0x1000000
    for p in sorted(patches, key=lambda p: p["id"]):
        size = p.get("size", SIZE)
        if p.get("replace"):
            # the level's own map for that cube, rewritten where it stands
            if heads[p["id"]][2] != size or len(hmp["items"][p["id"]]) != (size + 1) ** 2:
                raise ValueError("height map %d is not the %d-sample map it was read as" % (p["id"], size))
            hmp["items"][p["id"]] = bytearray(p["data"])
            continue
        if p["id"] >= SLOTS or heads[p["id"]][2]:
            raise ValueError("height map slot %d is not free" % p["id"])
        heads[p["id"]] = [ptr, 0, size]
        hmp["items"][p["id"]] = bytearray(p["data"])
        ptr += (size + 1) ** 2


# ------------------------------------------------------------------ pads
def body_rects(model, sizes):
    s = sizes.get(model) or {}
    return s.get("body") or []


def pad_for(p, sizes, terrain, target=None):
    """What one building needs: its footprint in world space and the height to
    level it at (the median of the ground under it, unless given)."""
    rects = body_rects(p.get("model"), sizes)
    if not rects:
        return None
    g = p.get("gamma") or 0.0
    pad = {"name": p.get("name") or p.get("model"), "x": p["x"], "y": p["y"], "c": math.cos(g), "s": math.sin(g),
           "rects": rects}
    xs, ys, zs = [], [], []
    for r in rects:
        nx, ny = max(1, int(math.ceil(r[2]))), max(1, int(math.ceil(r[3])))
        for i in range(nx + 1):
            for j in range(ny + 1):
                wx, wy = _to_world(pad, r[0] + r[2] * i / nx, r[1] + r[3] * j / ny)
                xs.append(wx)
                ys.append(wy)
                z = terrain.z(wx, wy)
                if z is not None:
                    zs.append(z)
    if not zs:
        return None
    zs.sort()
    pad["target"] = target if target is not None else zs[len(zs) // 2]
    pad["low"], pad["high"] = zs[0], zs[-1]
    reach = FLAT + BLEND
    pad["box"] = (min(xs) - reach, max(xs) + reach, min(ys) - reach, max(ys) + reach)
    return pad


def _to_world(pad, mx, my):
    return pad["x"] + mx * pad["c"] - my * pad["s"], pad["y"] + mx * pad["s"] + my * pad["c"]


def _distance(pad, x, y):
    """Metres from (x, y) to the footprint (0 inside)."""
    dx, dy = x - pad["x"], y - pad["y"]
    mx, my = dx * pad["c"] + dy * pad["s"], -dx * pad["s"] + dy * pad["c"]
    if pad.get("round"):
        r = pad["rects"][0]
        rx, ry = max(0.25, r[2] / 2), max(0.25, r[3] / 2)
        d = math.hypot((mx - (r[0] + rx)) / rx, (my - (r[1] + ry)) / ry)
        return 0.0 if d <= 1.0 else (d - 1.0) * min(rx, ry)
    best = 1e9
    for r in pad["rects"]:
        ex = max(r[0] - mx, 0.0, mx - (r[0] + r[2]))
        ey = max(r[1] - my, 0.0, my - (r[1] + r[3]))
        best = min(best, math.hypot(ex, ey))
    return best


def _weight(pad, d, gx=0.0, gy=0.0):
    """1 on the pad itself, easing to 0 over its edge. A building's pad eases
    with a smoothstep; an area of the Ground tool with a smootherstep (no crease
    where the slope starts or ends) over an edge that wanders a little, so it
    reads as ground rather than as a drawn shape."""
    flat = pad.get("flat", FLAT)
    blend = pad.get("blend", BLEND)
    if pad.get("amp") and d > flat:
        d = max(flat, d + gnoise(gx, gy, pad.get("seed", 0)) * pad["amp"])
    if d <= flat:
        return 1.0
    if blend <= 0 or d >= flat + blend:
        return 0.0
    t = (flat + blend - d) / blend
    if pad.get("area"):
        return t * t * t * (t * (t * 6 - 15) + 10)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ the Ground tool
# Areas the mission shapes anywhere on the map (editor: "Shape the ground").
# Each is a pad with no building on it, flat right up to its own outline and
# eased back over "blend" metres:
#   level   to a height            raise / lower   by "delta" metres
#   smooth  towards the ground averaged over "strength" metres
#   ramp    an even slope from z0 (at -w/2 along its angle) to z1 (at +w/2)
# They apply in order, each on the ground the ones before it left, then the
# brush strokes. The ground under the level's own buildings is kept (keep_for):
# a building does not move with the earth, so the earth stays under it.
#
# The edge noise is the editor's too (plotter.html ghash/gnoise): the same
# integer hash, so the preview and the build wander alike.
def _hash(ix, iy, seed):
    h = (ix * 374761393 + iy * 668265263 + seed * 144665) & 0xffffffff
    h = ((h ^ (h >> 13)) * 1274126177) & 0xffffffff
    return ((h ^ (h >> 16)) & 0xffff) / 65535.0


def gnoise(x, y, seed):
    """Smooth value noise, -1..1: 9 m swells with 3.5 m ripples on them."""
    total = 0.0
    for f, a in ((1.0 / 9.0, 0.65), (1.0 / 3.5, 0.35)):
        fx, fy = x * f, y * f
        ix, iy = math.floor(fx), math.floor(fy)
        tx, ty = fx - ix, fy - iy
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        v = ((_hash(ix, iy, seed) * (1 - tx) + _hash(ix + 1, iy, seed) * tx) * (1 - ty) +
             (_hash(ix, iy + 1, seed) * (1 - tx) + _hash(ix + 1, iy + 1, seed) * tx) * ty)
        total += a * (v * 2 - 1)
    return total


def seed_of(uid):
    h = 7
    for ch in str(uid or ""):
        h = (h * 31 + ord(ch)) & 0xffff
    return h


EDGE_WANDER = 0.3               # of the edge's width, at most WANDER_MAX metres
WANDER_MAX = 3.0


def pad_for_area(a, terrain):
    w = max(0.5, float(a.get("w") or 0.0))
    h = max(0.5, float(a.get("h") or 0.0))
    blend = max(0.0, float(a["blend"] if a.get("blend") is not None else BLEND))
    ang = float(a.get("angle") or 0.0)
    mode = a.get("mode") or "level"
    pad = {"name": a.get("name") or "ground area", "x": float(a["x"]), "y": float(a["y"]),
           "c": math.cos(ang), "s": math.sin(ang), "rects": [[-w / 2, -h / 2, w, h]],
           "round": bool(a.get("round")) and mode != "ramp", "flat": 0.0, "blend": blend, "area": True,
           "mode": mode, "seed": seed_of(a.get("uid")), "amp": min(EDGE_WANDER * blend, WANDER_MAX)}
    mid = _median(pad, terrain)
    if mode == "level":
        t = a.get("height")
        pad["target"] = float(t) if t is not None else mid
        if pad["target"] is None:
            return None
    elif mode in ("raise", "lower"):
        pad["target"] = None
        pad["delta"] = float(a.get("delta") or 0.0)
        if not pad["delta"]:
            return None
    elif mode == "smooth":
        pad["target"] = None
        pad["radius"] = max(1.0, min(20.0, float(a.get("strength") or 4.0)))
    elif mode == "remove":
        pad["target"] = None
        pad["ring"] = _ring(pad, w, h, blend, terrain)
        if not pad["ring"]:
            return None
    elif mode == "ramp":
        pad["target"] = None
        ends = [_to_world(pad, -w / 2, 0.0), _to_world(pad, w / 2, 0.0)]
        z0 = a.get("z0") if a.get("z0") is not None else terrain.z(*ends[0])
        z1 = a.get("z1") if a.get("z1") is not None else terrain.z(*ends[1])
        if z0 is None or z1 is None:
            return None
        pad["z0"], pad["z1"] = float(z0), float(z1)
    else:
        return None
    pad["low"] = pad["high"] = mid if mid is not None else (pad.get("target") or 0.0)
    r = math.hypot(w, h) / 2 + blend + pad["amp"]
    pad["box"] = (pad["x"] - r, pad["x"] + r, pad["y"] - r, pad["y"] + r)
    return pad


RING = 48                       # points round a Remove area its fill is drawn from


def _ring(pad, w, h, blend, terrain):
    """A Remove area's surroundings: the level's ground at RING points on the
    ellipse through its outer edge (the area plus its blend), as (x, y, z)."""
    out = []
    rx, ry = w / 2 + blend, h / 2 + blend
    for k in range(RING):
        t = 2 * math.pi * k / RING
        x, y = _to_world(pad, rx * math.cos(t), ry * math.sin(t))
        z = terrain.z(x, y)
        if z is not None:
            out.append((x, y, z))
    return out


def ring_fill(ring, x, y):
    """The ground a Remove area leaves: its surroundings drawn in across it,
    each weighed by the inverse square of its distance (plotter.html ringFill)."""
    tw = tz = 0.0
    for rx, ry, rz in ring:
        w = 1.0 / ((rx - x) ** 2 + (ry - y) ** 2 + 1.0)
        tw += w
        tz += w * rz
    return tz / tw


def _median(pad, terrain):
    """The middling height of the ground the pad covers."""
    r = pad["rects"][0]
    zs = []
    for j in range(13):
        for i in range(13):
            mx, my = r[0] + r[2] * i / 12.0, r[1] + r[3] * j / 12.0
            wx, wy = _to_world(pad, mx, my)
            if _distance(pad, wx, wy) > 0:
                continue
            z = terrain.z(wx, wy)
            if z is not None:
                zs.append(z)
    if not zs:
        return terrain.z(pad["x"], pad["y"])
    zs.sort()
    return zs[len(zs) // 2]


KEEP_NEAR = 0.5                 # metres round a building where the ground stays exactly as it was
KEEP_EASE = 3.0                 # ... then over this far it may change fully


KEEP_POINT = 0.6               # a pickup, a lamp, the player start: this far round its position


def keep_for(o, sizes):
    """The footprint of something standing on the ground, whose ground the
    Ground tool leaves alone (its collision body, or a small square round it)."""
    rects = body_rects(o.get("model"), sizes) or [[-KEEP_POINT, -KEEP_POINT, 2 * KEEP_POINT, 2 * KEEP_POINT]]
    g = o.get("gamma") or 0.0
    k = {"x": o["x"], "y": o["y"], "c": math.cos(g), "s": math.sin(g), "rects": rects}
    xs, ys = [], []
    for r in rects:
        for mx, my in ((r[0], r[1]), (r[0] + r[2], r[1]), (r[0], r[1] + r[3]), (r[0] + r[2], r[1] + r[3])):
            wx, wy = _to_world(k, mx, my)
            xs.append(wx)
            ys.append(wy)
    reach = KEEP_NEAR + KEEP_EASE
    k["box"] = (min(xs) - reach, max(xs) + reach, min(ys) - reach, max(ys) + reach)
    return k


def _keep(keeps, gx, gy):
    f = 1.0
    for k in keeps:
        x0, x1, y0, y1 = k["box"]
        if not (x0 <= gx <= x1 and y0 <= gy <= y1):
            continue
        t = (_distance(k, gx, gy) - KEEP_NEAR) / KEEP_EASE
        if t <= 0:
            return 0.0
        if t < 1:
            f = min(f, t * t * (3 - 2 * t))
    return f


def brush_cells(rows):
    """The plan's brush strokes, [[ix, iy, metres], ...] on a 1 m grid, as a dict."""
    out = {}
    for r in rows or []:
        try:
            ix, iy, d = int(r[0]), int(r[1]), float(r[2])
        except (TypeError, ValueError, IndexError):
            continue
        if d:
            out[(ix, iy)] = max(-SHAPE_MAX, min(SHAPE_MAX, d))
    return out


# The big shapes: brush strokes wider than the fine brush's and the mountains,
# hills, craters and valleys stamped with it, as metres on the terrain mesh's
# own 4 m grid (plan "sculpt": [[ix, iy, centimetres], ...], cell (ix, iy) at
# (4 ix, 4 iy)). They apply first, before the areas, the fine brush and the
# building pads (plotter.html sculptAt, in the same order).
SCULPT_M = 4.0
SHAPE_MAX = 600.0               # a sanity bound on any one change, metres


def sculpt_cells(rows):
    out = {}
    for r in rows or []:
        try:
            ix, iy, cm = int(r[0]), int(r[1]), float(r[2])
        except (TypeError, ValueError, IndexError):
            continue
        if cm:
            out[(ix, iy)] = max(-SHAPE_MAX, min(SHAPE_MAX, cm / 100.0))
    return out


def _sculpt_at(cells, gx, gy):
    """Bilinear between the 4 m grid points."""
    fx, fy = gx / SCULPT_M, gy / SCULPT_M
    ix, iy = math.floor(fx), math.floor(fy)
    tx, ty = fx - ix, fy - iy
    g = cells.get
    return ((g((ix, iy), 0.0) * (1 - tx) + g((ix + 1, iy), 0.0) * tx) * (1 - ty) +
            (g((ix, iy + 1), 0.0) * (1 - tx) + g((ix + 1, iy + 1), 0.0) * tx) * ty)


def _brush_at(cells, gx, gy):
    """Bilinear between cell centres (ix + 0.5, iy + 0.5)."""
    fx, fy = gx - 0.5, gy - 0.5
    ix, iy = math.floor(fx), math.floor(fy)
    tx, ty = fx - ix, fy - iy
    g = cells.get
    return ((g((ix, iy), 0.0) * (1 - tx) + g((ix + 1, iy), 0.0) * tx) * (1 - ty) +
            (g((ix, iy + 1), 0.0) * (1 - tx) + g((ix + 1, iy + 1), 0.0) * tx) * ty)


def _smoothed(terrain, pad):
    """The ground under a smooth pad, averaged over its radius: a grid of
    heights (two box blurs, close to a gaussian) to look up per sample."""
    x0, x1, y0, y1 = pad["box"]
    r = pad["radius"]
    step = max(1.0, math.sqrt((x1 - x0 + 2 * r) * (y1 - y0 + 2 * r) / 12000.0))
    gx0, gy0 = x0 - r, y0 - r
    nx, ny = int((x1 - x0 + 2 * r) / step) + 2, int((y1 - y0 + 2 * r) / step) + 2
    z = [[terrain.z(gx0 + i * step, gy0 + j * step) for i in range(nx)] for j in range(ny)]
    fill = [v for row in z for v in row if v is not None]
    if not fill:
        return None
    mean = sum(fill) / len(fill)
    z = [[mean if v is None else v for v in row] for row in z]
    k = max(1, int(round(r / step / 2)))

    def blur_rows(a):
        out = []
        for row in a:
            n = len(row)
            pre = [0.0]
            for v in row:
                pre.append(pre[-1] + v)
            out.append([(pre[min(n, i + k + 1)] - pre[max(0, i - k)]) / (min(n, i + k + 1) - max(0, i - k))
                        for i in range(n)])
        return out

    def transpose(a):
        return [list(c) for c in zip(*a)]

    for _ in range(2):
        z = transpose(blur_rows(transpose(blur_rows(z))))
    return {"x0": gx0, "y0": gy0, "step": step, "nx": nx, "ny": ny, "z": z}


def _grid_at(g, x, y):
    fx, fy = (x - g["x0"]) / g["step"], (y - g["y0"]) / g["step"]
    i = min(g["nx"] - 2, max(0, int(math.floor(fx))))
    j = min(g["ny"] - 2, max(0, int(math.floor(fy))))
    tx, ty = min(1.0, max(0.0, fx - i)), min(1.0, max(0.0, fy - j))
    z = g["z"]
    return ((z[j][i] * (1 - tx) + z[j][i + 1] * tx) * (1 - ty) +
            (z[j + 1][i] * (1 - tx) + z[j + 1][i + 1] * tx) * ty)


def _shape(pad, g, wt, gx, gy):
    """The ground at one sample after this pad, at weight wt."""
    mode = pad.get("mode")
    if mode in ("raise", "lower"):
        return g + pad["delta"] * wt
    if mode == "smooth":
        grid = pad.get("grid")
        return g if grid is None else g + (_grid_at(grid, gx, gy) - g) * wt
    if mode == "remove":
        return g + (ring_fill(pad["ring"], gx, gy) - g) * wt
    if mode == "ramp":
        dx, dy = gx - pad["x"], gy - pad["y"]
        mx = dx * pad["c"] + dy * pad["s"]
        w = pad["rects"][0][2]
        t = min(1.0, max(0.0, (mx + w / 2) / w))
        want = pad["z0"] + (pad["z1"] - pad["z0"]) * t
        return g + (want - g) * wt
    return g + (pad["target"] - g) * wt


class Shaped:
    """The level's ground with the areas and brush strokes applied - what a
    building placed on shaped ground is measured against (pad_for(..., Shaped))."""

    def __init__(self, terrain, areas, keep=None, brush=None, sculpt=None):
        self.t, self.areas, self.keep, self.brush = terrain, areas, keep or [], brush or {}
        self.sculpt = sculpt or {}
        for pad in areas:
            if pad.get("mode") == "smooth" and "grid" not in pad:
                pad["grid"] = _smoothed(terrain, pad)

    def z(self, x, y):
        g = self.t.z(x, y)
        if g is None:
            return None
        kf = _keep(self.keep, x, y) if self.keep else 1.0
        if kf <= 0:
            return g
        if self.sculpt:
            g += _sculpt_at(self.sculpt, x, y) * kf
        for pad in self.areas:
            bx0, bx1, by0, by1 = pad["box"]
            if bx0 <= x <= bx1 and by0 <= y <= by1:
                wt = _weight(pad, _distance(pad, x, y), x, y) * kf
                if wt > 0:
                    g = _shape(pad, g, wt, x, y)
        if self.brush:
            g += _brush_at(self.brush, x, y) * kf
        return g


# ------------------------------------------------------------------ patches
def _sample(near, keeps, brush, brushed, gx, gy, v0, base_at, sculpt=None):
    """The ground wanted at one point (metres), and whether anything shapes it:
    the areas in order, then the brush, then the nearest building pad - each on
    the ground the ones before it left, starting from the level's own (its mesh,
    base_at() in raw units, plus its height map, v0). Returns (ground, mesh
    height, touched, the pad that holds it fully or None)."""
    g = base = full = None
    touched = False
    kf = None
    best, bw = None, 0.0
    if sculpt:
        sd = _sculpt_at(sculpt, gx, gy)
        if sd:
            kf = _keep(keeps, gx, gy) if keeps else 1.0
            if kf > 0:
                base = base_at()
                if base is not None:
                    g = base / SCALE + (v0 - 64.0) * STEP + sd * kf
                    touched = True
    for pad in near:
        bx0, bx1, by0, by1 = pad["box"]
        if not (bx0 <= gx <= bx1 and by0 <= gy <= by1):
            continue
        wt = _weight(pad, _distance(pad, gx, gy), gx, gy)
        if wt <= 0:
            continue
        if not pad.get("area"):
            if wt > bw:              # buildings: the nearest pad wins, after the areas
                best, bw = pad, wt
            continue
        if keeps:
            if kf is None:
                kf = _keep(keeps, gx, gy)
            wt *= kf
            if wt <= 0:
                continue
        if g is None:
            base = base_at()
            if base is None:
                break
            g = base / SCALE + (v0 - 64.0) * STEP
        g = _shape(pad, g, wt, gx, gy)
        touched = True
        if wt > 0.99:
            full = pad
    if brushed and (base is not None or g is None):
        bd = _brush_at(brush, gx, gy)
        if bd:
            if kf is None:
                kf = _keep(keeps, gx, gy) if keeps else 1.0
            if kf > 0:
                if g is None:
                    base = base_at()
                    if base is not None:
                        g = base / SCALE + (v0 - 64.0) * STEP
                if g is not None:
                    g += bd * kf
                    touched = True
    if best is not None:
        if g is None:
            base = base_at()
            if base is not None:
                g = base / SCALE + (v0 - 64.0) * STEP
        if g is not None:
            g = _shape(best, g, bw, gx, gy)
            touched = True
            if bw > 0.99:
                full = best
    return g, base, touched, full


def _cubes_of(pads, brush, cube, sculpt=None):
    cubes = set()
    for (ix, iy) in sculpt or ():
        for cx in range(math.floor((ix - 1) * SCULPT_M * SCALE / cube), math.floor((ix + 1) * SCULPT_M * SCALE / cube) + 1):
            for cy in range(math.floor((iy - 1) * SCULPT_M * SCALE / cube), math.floor((iy + 1) * SCULPT_M * SCALE / cube) + 1):
                cubes.add((cx, cy))
    for pad in pads:
        x0, x1, y0, y1 = pad["box"]
        for cx in range(math.floor(x0 * SCALE / cube), math.floor(x1 * SCALE / cube) + 1):
            for cy in range(math.floor(y0 * SCALE / cube), math.floor(y1 * SCALE / cube) + 1):
                cubes.add((cx, cy))
    for (ix, iy) in brush:
        for cx in range(math.floor((ix - 0.5) * SCALE / cube), math.floor((ix + 1.5) * SCALE / cube) + 1):
            for cy in range(math.floor((iy - 0.5) * SCALE / cube), math.floor((iy + 1.5) * SCALE / cube) + 1):
                cubes.add((cx, cy))
    return cubes


def _near(pads, keep, brush, mx0, my0, mx1, my1, sculpt=None):
    near = [p for p in pads if p["box"][0] <= mx1 and p["box"][1] >= mx0 and p["box"][2] <= my1 and p["box"][3] >= my0]
    keeps = [k for k in keep if k["box"][0] <= mx1 and k["box"][1] >= mx0 and k["box"][2] <= my1 and k["box"][3] >= my0]
    brushed = bool(brush) and any(mx0 - 1 <= ix <= mx1 and my0 - 1 <= iy <= my1 for (ix, iy) in brush)
    sub = None
    if sculpt:
        i0, i1 = math.floor(mx0 / SCULPT_M) - 1, math.ceil(mx1 / SCULPT_M) + 1
        j0, j1 = math.floor(my0 / SCULPT_M) - 1, math.ceil(my1 / SCULPT_M) + 1
        sub = {k: v for k, v in sculpt.items() if i0 <= k[0] <= i1 and j0 <= k[1] <= j1} or None
    return near, keeps, brushed, sub


# How far the ground has to move before the terrain mesh itself is built again
# there (studio/build/terrain_mesh.py) rather than only its height map: a height
# map moves it 4 m at most, and the mesh keeps a margin under that for what it
# cannot follow exactly (its coarse points sit on steps, the finest detail).
MESH_FROM = 3.0
GRID_M = 4.0                    # the terrain mesh's grid: a height every 4 m


def mesh_changes(terrain, pads, keep=None, brush=None, sculpt=None):
    """{(gi, gj): metres}: how far the terrain mesh's grid points have to move
    for the shaped ground - where the change there, smoothed over the 4 m round
    the point (a tent filter over samples 2 m apart, so a narrow brush stroke
    stays in the height map), is more than a height map can carry. A point that
    moves takes the level's own height map there into the mesh as well: the
    map over a rebuilt cube is written again whole (build_patches), and then
    has all its ±4 m for what the mesh cannot follow."""
    keep = keep or []
    brush = brush or {}
    for pad in pads:
        if pad.get("mode") == "smooth" and "grid" not in pad:
            pad["grid"] = _smoothed(terrain, pad)
    cube = 1 << (31 - LOD)
    step = int(2 * SCALE)                                # 2 m between samples
    per = cube // step                                   # 32 of them across a 64 m cube
    gstep = int(GRID_M * SCALE)
    out = {}
    for (cx, cy) in sorted(_cubes_of(pads, brush, cube, sculpt)):
        min_x, min_y = cx * cube, cy * cube
        mx0, my0, mx1, my1 = min_x / SCALE, min_y / SCALE, (min_x + cube) / SCALE, (min_y + cube) / SCALE
        near, keeps, brushed, sub = _near(pads, keep, brush, mx0 - 4, my0 - 4, mx1 + 4, my1 + 4, sculpt)
        if not near and not brushed and not sub:
            continue
        # one sample past the cube each way, for the filter at its edge
        n = per + 3
        base = terrain.base_block(min_x - step, min_y - step, n - 1, step)
        d = [0.0] * (n * n)
        own_map = [0.0] * (n * n)                        # the level's height map, metres
        for j in range(n):
            ry = min_y + (j - 1) * step
            for i in range(n):
                rx = min_x + (i - 1) * step
                b = base[j * n + i]
                if b is None:
                    continue
                h = terrain._hmp_for(rx, ry)
                v0 = 64.0 + (terrain._hmp_delta(h, rx, ry) / 256.0 if h is not None else 0.0)
                own_map[j * n + i] = (v0 - 64.0) * STEP
                g, _, touched, _ = _sample(near, keeps, brush, brushed, rx / SCALE, ry / SCALE, v0, lambda: b, sub)
                if touched and g is not None:
                    d[j * n + i] = g - (b / SCALE + (v0 - 64.0) * STEP)
        # the grid points in this cube (its low edges; the high ones are the next cube's)
        for j in range(1, n - 2, 2):
            for i in range(1, n - 2, 2):
                acc = 0.0
                for dj, wj in ((-1, 0.25), (0, 0.5), (1, 0.25)):
                    row = (j + dj) * n
                    acc += wj * (0.25 * d[row + i - 1] + 0.5 * d[row + i] + 0.25 * d[row + i + 1])
                if abs(acc) > MESH_FROM:
                    out[((min_x + (i - 1) * step) // gstep, (min_y + (j - 1) * step) // gstep)] = acc + own_map[j * n + i]
    return out


def build_patches(terrain, pads, first_id, keep=None, brush=None, mesh=None, mesh_cubes=None, sculpt=None,
                  folds=None):
    """One height map per terrain cube the pads (and brush strokes) touch.

    A cube the level already maps is rewritten IN PLACE, keeping its bitmap id,
    size and task: a second map over the same cube is ignored by the game - it
    keeps the one it loaded first, which is why flattened ground used to come
    out unflattened (level 3, 2026-09-18). Only a cube with no map of its own
    gets a new one.

    Pads apply in the order given, each on the ground the ones before it left;
    then the brush. keep: footprints (keep_for) whose ground areas and brush
    leave alone - a building pad levels its own ground regardless.

    mesh: the terrain with its mesh built again where the ground moves further
    than a height map can (terrain_mesh.py), or None. The ground is still worked
    out on the level's own (terrain); the maps then carry what is left between
    it and the new mesh, and every cube in mesh_cubes ((cx, cy) of 64 m cubes
    whose mesh changed) is mapped whole, so nothing standing where the mesh
    moved but the ground did not is left on the new mesh. folds: the grid
    points where the level's ground hung over itself and the new mesh does
    not (terrain_mesh._folds); in the 8 m squares round them the level's
    ground says nothing about the new one, and their maps are left as they
    were."""
    cube = 1 << (31 - LOD)
    keep = keep or []
    brush = brush or {}
    leaf = int(2 * GRID_M * SCALE)                      # a terrain leaf's square, raw
    fold_sq = {(i0, j0) for gi, gj in (folds or ())
               for i0 in {gi // 2 * 2, (gi - 1) // 2 * 2} for j0 in {gj // 2 * 2, (gj - 1) // 2 * 2}}
    for pad in pads:
        if pad.get("mode") == "smooth" and "grid" not in pad:
            pad["grid"] = _smoothed(terrain, pad)
    cubes = _cubes_of(pads, brush, cube, sculpt) | set(mesh_cubes or ())
    patches, notes, nid = [], [], first_id
    short, off_by = {}, 0.0
    for (cx, cy) in sorted(cubes):
        min_x, min_y = cx * cube, cy * cube
        mx0, my0, mx1, my1 = min_x / SCALE, min_y / SCALE, (min_x + cube) / SCALE, (min_y + cube) / SCALE
        near, keeps, brushed, sub = _near(pads, keep, brush, mx0, my0, mx1, my1, sculpt)
        # the level's own map for this cube, if it has one
        have = None
        for h in terrain.hmaps:
            if h.get("id") is not None and h["min_x"] == min_x and h["min_y"] == min_y and h["cube"] == cube:
                have = h
        size = have["size"] if have else SIZE
        spacing = cube // size
        data = bytearray((size + 1) ** 2)
        changed = False
        whole = mesh is not None and (cx, cy) in (mesh_cubes or ())
        if mesh is not None:
            base0 = terrain.base_block(min_x, min_y, size, spacing)
            base1 = mesh.base_block(min_x, min_y, size, spacing)
        for j in range(size + 1):
            ry = min_y + j * spacing
            for i in range(size + 1):
                rx = min_x + i * spacing
                h = terrain._hmp_for(rx, ry)
                v0 = 64.0 + (terrain._hmp_delta(h, rx, ry) / 256.0 if h is not None else 0.0)
                v = v0
                if mesh is None:
                    g, base, touched, full = _sample(near, keeps, brush, brushed, rx / SCALE, ry / SCALE, v0,
                                                     lambda: terrain.z_raw_base(rx, ry), sub)
                    if touched and g is not None and base is not None:
                        v = 64.0 + (g - base / SCALE) / STEP
                        if (v < 0 or v > 127) and full is not None:
                            miss = (v - min(127.0, max(0.0, v))) * STEP
                            if abs(miss) > abs(short.get(full["name"], 0.0)):
                                short[full["name"]] = miss
                        changed = True
                else:
                    k = j * (size + 1) + i
                    b0, b1 = base0[k], base1[k]
                    g, _, touched, full = _sample(near, keeps, brush, brushed, rx / SCALE, ry / SCALE, v0, lambda: b0, sub)
                    if not touched or g is None:
                        g = None if b0 is None else b0 / SCALE + (v0 - 64.0) * STEP     # the level's own ground
                    if fold_sq and ((int(rx // leaf) * 2, int(ry // leaf) * 2) in fold_sq):
                        g = None        # where the level's ground hung over itself: the new mesh as it is
                    if g is not None and b1 is not None and (touched or whole):
                        v = 64.0 + (g - b1 / SCALE) / STEP
                        if v < 0 or v > 127:
                            off_by = max(off_by, abs(v - min(127.0, max(0.0, v))) * STEP)
                        changed = True
                data[j * (size + 1) + i] = int(round(min(127.0, max(0.0, v))))
        if not changed:
            continue
        if have:
            patches.append({"id": have["id"], "min_x": min_x, "min_y": min_y, "cube": cube, "size": size,
                            "data": bytes(data), "replace": True,
                            "task": ((min_x + cube / 2), (min_y + cube / 2))})
            continue
        if nid >= SLOTS:
            notes.append("no free height map slots left in terrain.hmp - some ground is not shaped")
            break
        patches.append({"id": nid, "min_x": min_x, "min_y": min_y, "cube": cube, "size": size,
                        "data": bytes(data), "replace": False,
                        "task": ((min_x + cube / 2), (min_y + cube / 2))})
        nid += 1
    for name, miss in short.items():
        notes.append("%s: the ground can only be moved about 4 m - it is still %.1f m %s where it was asked to be"
                     % (name, abs(miss), "above" if miss < 0 else "below"))
    if off_by > 1.5:
        notes.append("the terrain follows the shaped ground to within %.1f m (it is a height every 4 m, some of "
                     "them on fixed steps; the steepest shapes are smoothed a little)" % off_by)
    return patches, notes


def register(terrain, patches):
    """Let the height queries that follow see the flattened ground."""
    for p in patches:
        size = p.get("size", SIZE)
        terrain.hmaps.append({
            "id": p["id"], "size": size, "lod": LOD,
            "min_x": p["min_x"], "min_y": p["min_y"], "cube": p["cube"],
            "shift": size.bit_length() - 1,
            "scale": 1.0 / (1 << ((30 - LOD) - (size.bit_length() - 2))),
            "data": p["data"],
        })


def task_text(p, z_raw):
    x, y = p["task"]
    return 'Task_New(-1, "HeightMap", "", %.1f, %.1f, %.1f, %d, %d, FALSE, %d, 8, 7)' % (
        x, y, z_raw, LOD, p.get("size", SIZE), p["id"])


def add_tasks(qsc, patches, z_raw, task_end, eol="\r\n"):
    """Insert the new HeightMap tasks after the level's last one, or as the
    first thing in the Static container when the level has none. A patch that
    rewrote the level's own map needs no task - the level already has one."""
    patches = [p for p in patches if not p.get("replace")]
    if not patches:
        return qsc
    text = "".join(", " + eol + task_text(p, z_raw) for p in patches)
    last = qsc.rfind('Task_New(-1, "HeightMap"')
    if last >= 0:
        end = task_end(qsc, last)
        return qsc[:end] + text + qsc[end:]
    at = qsc.find('Task_New(-1, "Static", "", ')
    if at < 0:
        raise ValueError("the level script has no Static container")
    head = at + len('Task_New(-1, "Static", "", ')
    first = "".join(task_text(p, z_raw) + ", " + eol for p in patches)
    return qsc[:head] + eol + first + qsc[head:]
