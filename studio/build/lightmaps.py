# The terrain's baked light, redone where a mission rebuilt the terrain mesh
# (terrain_mesh.py), so a new mountain has a lit side and a dark side and a
# removed one leaves no shading of it behind.
#
#   terrain/terrain.lmp   light maps back to back: u32 size, then size x size
#                         grey bytes, the bottom row first. 0 is "no light map".
#   TerrainLightMap task  Position, Level (the cube it covers), Size, TextureIndex
#                         (which light map), GeneratedWhenCreated. The game draws
#                         a spot with the light map of the smallest such cube
#                         round it; they run from 256 m to 8 m a pixel.
#
# How the level was lit is not written anywhere the studio reads, so it is
# worked out from the light maps themselves: over every light map pixel, how
# bright it is against how the ground there faces (fit_sun), for the direction
# of light that explains it best. Where that is weak (night levels, rain, a
# level lit mostly by hand) the light maps are left as they are. Otherwise a
# pixel over changed ground is made brighter or darker by what the change did
# to the way the ground faces that light, and to the shadow it lies in (new
# ground throwing one, or ground taken away no longer throwing it): a march
# towards the light over the heights before and after, for every pixel whose
# ray passes over changed ground.
#
#   fit = fit_sun(level, terrain, qsc_text, lmp_path)       cached per level
#   items = relight(lmp_items, tasks, before, after, box, fit)
import json, math, pathlib, re, struct

from studio import paths

R_TASK = re.compile(r'Task_New\(-?\d+, "TerrainLightMap", "[^"]*", (-?[\d.eE+-]+), (-?[\d.eE+-]+), (-?[\d.eE+-]+), '
                    r'(\d+), (\d+), (\d+), (?:TRUE|FALSE)\)')
MIN_FIT = 0.25                  # correlation below which a level's light is not redone
SCALE = 4096.0
# A light map's first row is its cube's lowest y. Read the other way up, the
# levels' own light fits the ground they lie on at r 0.29-0.42; this way, 0.76-0.80
# (levels 1, 3 and 7). Read upside down, a rebuilt mountain's light and shade were
# written mirrored across each light map (2026-09-21). Bumped whenever the fit
# changes, so a fit cached before is worked out again.
FIT_VERSION = 2


def _px(size, i, j):
    """The pixel at column i, row j counted from the cube's lowest y."""
    return j * size + i


def read_lmp(path):
    b = pathlib.Path(path).read_bytes()
    items, off = [], 0
    while off + 4 <= len(b):
        n = struct.unpack_from("<I", b, off)[0]
        off += 4
        items.append([n, bytearray(b[off:off + n * n])])
        off += n * n
    return items


def write_lmp(path, items):
    out = bytearray()
    for n, px in items:
        out += struct.pack("<I", n) + bytes(px)
    pathlib.Path(path).write_bytes(bytes(out))


def tasks_of(qsc_text):
    """[(min_x, min_y, cube, texture index)] of the level's light maps (raw units)."""
    out = []
    for m in R_TASK.finditer(qsc_text):
        x, y, lod, tex = float(m.group(1)), float(m.group(2)), int(m.group(4)), int(m.group(6))
        cube = 1 << (31 - lod)
        out.append((math.floor(x / cube) * cube, math.floor(y / cube) * cube, cube, tex))
    return out


def _normal(terrain, x, y, e):
    zs = [terrain.z_raw(x + a, y + c) for a, c in ((e, 0), (-e, 0), (0, e), (0, -e))]
    if None in zs:
        return None
    nx, ny = (zs[1] - zs[0]) / (2 * e), (zs[3] - zs[2]) / (2 * e)
    ln = math.sqrt(nx * nx + ny * ny + 1)
    return nx / ln, ny / ln, 1 / ln


def _lambert(n, sun):
    return max(0.0, n[0] * sun[0] + n[1] * sun[1] + n[2] * sun[2])


def fit_sun(level, terrain, qsc_text, lmp_path):
    """{"sun": (x, y, z), "a", "b", "r"}: pixel = a + b x how squarely the ground
    faces the sun, and how well that holds (r). Cached per level and light map file."""
    lmp_path = pathlib.Path(lmp_path)
    cache = paths.cache() / "lightfit" / ("level%d.json" % level)
    stamp = [lmp_path.stat().st_size, int(lmp_path.stat().st_mtime), FIT_VERSION]
    try:
        got = json.loads(cache.read_text(encoding="utf-8"))
        if got.get("stamp") == stamp:
            return got
    except (OSError, ValueError):
        pass
    items = read_lmp(lmp_path)
    samples = []
    for min_x, min_y, cube, tex in tasks_of(qsc_text):
        if tex >= len(items):
            continue
        n, px = items[tex]
        if not n:
            continue
        step = cube / n
        every = max(1, n // 8)
        for j in range(0, n, every):
            for i in range(0, n, every):
                v = px[_px(n, i, j)]
                if not v:
                    continue
                nrm = _normal(terrain, min_x + (i + 0.5) * step, min_y + (j + 0.5) * step, max(8 * SCALE, step / 2))
                if nrm is not None:
                    samples.append((nrm, v))
    best = {"sun": (0.0, 0.0, 1.0), "a": 0.0, "b": 0.0, "r": 0.0, "az": 0, "el": 90}
    if len(samples) >= 50:
        ys = [v for _, v in samples]
        my = sum(ys) / len(ys)
        syy = sum((v - my) ** 2 for v in ys)

        def trial(az, el):
            c = math.cos(math.radians(el))
            sun = (c * math.cos(math.radians(az)), c * math.sin(math.radians(az)), math.sin(math.radians(el)))
            xs = [_lambert(n, sun) for n, _ in samples]
            mx = sum(xs) / len(xs)
            sxx = sum((x - mx) ** 2 for x in xs)
            if not sxx or not syy:
                return None
            sxy = sum((x - mx) * (v - my) for x, v in zip(xs, ys))
            b = sxy / sxx
            return {"sun": sun, "a": my - b * mx, "b": b, "r": sxy / math.sqrt(sxx * syy), "az": az, "el": el}
        # a coarse look all round the sky, then closer round the best of it
        for az in range(0, 360, 20):
            for el in range(4, 90, 6):
                got = trial(az, el)
                if got and got["r"] > best["r"]:
                    best = got
        a0, e0 = best["az"], best["el"]
        for az in range(a0 - 15, a0 + 16, 5):
            for el in (e0 - 4, e0 - 2, e0, e0 + 2, e0 + 4):
                if 1 <= el <= 89:
                    got = trial(az % 360, el)
                    if got and got["r"] > best["r"]:
                        best = got
    best["stamp"] = stamp
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(best), encoding="utf-8")
    except OSError:
        pass
    return best


class _Grid:
    """A terrain's heights (raw) every `step` raw over a box, read at once
    (Terrain.base_block), looked up bilinearly."""

    def __init__(self, terrain, x0, y0, n, step):
        self.x0, self.y0, self.n, self.step = x0, y0, n, step
        self.z = terrain.base_block(x0, y0, n, step)

    def at(self, x, y):
        fx, fy = (x - self.x0) / self.step, (y - self.y0) / self.step
        i, j = int(math.floor(fx)), int(math.floor(fy))
        if i < 0 or j < 0 or i >= self.n or j >= self.n:
            return None
        tx, ty, row = fx - i, fy - j, self.n + 1
        a, b = self.z[j * row + i], self.z[j * row + i + 1]
        c, d = self.z[(j + 1) * row + i], self.z[(j + 1) * row + i + 1]
        if a is None or b is None or c is None or d is None:
            return None
        return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty

    def normal(self, x, y, e):
        zs = [self.at(x + a, y + c) for a, c in ((e, 0), (-e, 0), (0, e), (0, -e))]
        if None in zs:
            return None
        nx, ny = (zs[1] - zs[0]) / (2 * e), (zs[3] - zs[2]) / (2 * e)
        ln = math.sqrt(nx * nx + ny * ny + 1)
        return nx / ln, ny / ln, 1 / ln


def _sunlit(grid, x, y, sun, reach, step):
    """Does the sun reach the ground at (x, y), or does ground towards it stand
    in the way (a march along the ray, `step` raw at a time, `reach` raw far)?"""
    z0 = grid.at(x, y)
    if z0 is None:
        return 1.0
    h = math.hypot(sun[0], sun[1])
    if h < 1e-6:
        return 1.0
    dx, dy, rise = sun[0] / h, sun[1] / h, sun[2] / h
    t = step
    while t <= reach:
        z = grid.at(x + dx * t, y + dy * t)
        if z is not None and z > z0 + rise * t + 2 * SCALE:     # 2 m of slack for the ground's own grain
            return 0.0
        t += step
    return 1.0


def relight(items, tasks, before, after, box, fit, changed=None):
    """The light maps with every pixel over box (raw x0, x1, y0, y1) made
    brighter or darker by how the change turned the ground to the level's light,
    and by the shadow new ground throws (or old ground no longer throws).
    changed: the box the ground actually changed in; the shadows reach from it
    away from the light. Returns the number of pixels changed; items are
    changed in place."""
    if not fit or fit.get("r", 0) < MIN_FIT:
        return 0
    sun, b = fit["sun"], fit["b"]
    cx0, cx1, cy0, cy1 = changed or box
    # how far a shadow can fall: the tallest change over the height of the sun
    el = math.asin(max(0.05, min(1.0, sun[2])))
    reach = min(1500 * SCALE, (fit.get("tallest", 150.0) + 20) * SCALE / math.tan(el))
    h = math.hypot(sun[0], sun[1]) or 1.0
    ax, ay = -sun[0] / h * reach, -sun[1] / h * reach          # away from the light
    x0, x1, y0, y1 = box
    x0, x1 = min(x0, cx0 + ax), max(x1, cx1 + ax)
    y0, y1 = min(y0, cy0 + ay), max(y1, cy1 + ay)
    step = 8 * SCALE
    pad = reach + 64 * SCALE
    gx0, gy0 = math.floor((x0 - pad) / step) * step, math.floor((y0 - pad) / step) * step
    n = int(math.ceil(max(x1 + pad - gx0, y1 + pad - gy0) / step)) + 1
    g0, g1 = _Grid(before, gx0, gy0, n, step), _Grid(after, gx0, gy0, n, step)

    def crosses(x, y):
        """Does the ray from (x, y) towards the light pass over changed ground?"""
        ex, ey = x + sun[0] / h * reach, y + sun[1] / h * reach
        return not (max(x, ex) < cx0 or min(x, ex) > cx1 or max(y, ey) < cy0 or min(y, ey) > cy1)
    changed_px = 0
    for min_x, min_y, cube, tex in tasks:
        if tex >= len(items) or min_x > x1 or min_x + cube < x0 or min_y > y1 or min_y + cube < y0:
            continue
        size, px = items[tex]
        if not size:
            continue
        pstep = cube / size
        e = max(step, pstep / 2)
        i0, i1 = max(0, int((x0 - min_x) / pstep)), min(size - 1, int((x1 - min_x) / pstep))
        j0, j1 = max(0, int((y0 - min_y) / pstep)), min(size - 1, int((y1 - min_y) / pstep))
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                k = _px(size, i, j)
                v = px[k]
                if not v:
                    continue
                x, y = min_x + (i + 0.5) * pstep, min_y + (j + 0.5) * pstep
                n0, n1 = g0.normal(x, y, e), g1.normal(x, y, e)
                if n0 is None or n1 is None:
                    continue
                l0, l1 = _lambert(n0, sun), _lambert(n1, sun)
                if crosses(x, y):
                    l0 *= _sunlit(g0, x, y, sun, reach, step)
                    l1 *= _sunlit(g1, x, y, sun, reach, step)
                d = b * (l1 - l0)
                if abs(d) < 0.5:
                    continue
                px[k] = max(1, min(255, int(round(v + d))))
                changed_px += 1
    return changed_px
