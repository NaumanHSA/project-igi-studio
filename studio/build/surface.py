# What an object placed at (x, y) actually stands on.
#
# The walkable surface is the terrain, or the top of something built on it - a
# concrete apron, a warehouse floor, a watchtower platform. Navmesh nodes only
# sample those surfaces where a node happens to be, and blending nearby nodes
# drags an object off bare ground up to the height of an apron a few metres away
# (that is what left desks hovering). Here the terrain comes from the level's
# own terrain files (terrain.py) and the built surfaces from the collision mesh
# of every static model around the point.
#
#   s = Surface(slot_dir, objects_qsc, level_objects)
#   s.height(x, y, near_z)   -> the surface closest to near_z (game units)
import math, pathlib, struct

from studio.build.terrain import Terrain
from studio.build import models as MI

SCALE = 4096.0
UP = 0.6                     # a triangle is a floor if its normal is this close to vertical
NODE_REACH = 2.5             # metres: a node this close says what floor you are on


def _ilff(buf, start=20):
    off = start
    while off + 16 <= len(buf):
        tag = buf[off:off + 4]
        ln, al, _ = struct.unpack_from("<III", buf, off + 4)
        if al == 0 or off + 16 + ln > len(buf):
            return
        yield tag, buf[off + 16:off + 16 + ln]
        off += 16 + ((ln + al - 1) // al) * al


def collision_mesh(mef):
    """Upward-facing collision triangles of a model, in metres, model space."""
    vs, out = None, []
    for tag, pay in _ilff(mef):
        if tag[:4] == b"XTVC":
            vs = [tuple(v / SCALE for v in struct.unpack_from("<fff", pay, i))
                  for i in range(0, len(pay) - 11, 16)]
        elif tag[:4] == b"ECFC" and vs:
            for k in range(len(pay) // 8):
                i0, i1, i2, _ = struct.unpack_from("<4H", pay, k * 8)
                if max(i0, i1, i2) >= len(vs):
                    continue
                a, b, c = vs[i0], vs[i1], vs[i2]
                ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
                wx, wy, wz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
                nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
                ln = math.sqrt(nx * nx + ny * ny + nz * nz)
                if ln and abs(nz) / ln >= UP:
                    out.append((a, b, c, nx, ny, nz))
    return out


def collision_all(mef):
    """Every collision triangle of a model (walls included), metres, model space."""
    vs, out = None, []
    for tag, pay in _ilff(mef):
        if tag[:4] == b"XTVC":
            vs = [tuple(v / SCALE for v in struct.unpack_from("<fff", pay, i))
                  for i in range(0, len(pay) - 11, 16)]
        elif tag[:4] == b"ECFC" and vs:
            for k in range(len(pay) // 8):
                i0, i1, i2, _ = struct.unpack_from("<4H", pay, k * 8)
                if max(i0, i1, i2) < len(vs):
                    out.append((vs[i0], vs[i1], vs[i2]))
    return out


def _seg_hits_tri(p, d, tri):
    """Moller-Trumbore: does p + t*d, t in [0, 1], cross the triangle?"""
    a, b, c = tri
    e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    h = (d[1] * e2[2] - d[2] * e2[1], d[2] * e2[0] - d[0] * e2[2], d[0] * e2[1] - d[1] * e2[0])
    det = e1[0] * h[0] + e1[1] * h[1] + e1[2] * h[2]
    if abs(det) < 1e-9:
        return False
    f = 1.0 / det
    s = (p[0] - a[0], p[1] - a[1], p[2] - a[2])
    u = f * (s[0] * h[0] + s[1] * h[1] + s[2] * h[2])
    if u < 0.0 or u > 1.0:
        return False
    q = (s[1] * e1[2] - s[2] * e1[1], s[2] * e1[0] - s[0] * e1[2], s[0] * e1[1] - s[1] * e1[0])
    v = f * (d[0] * q[0] + d[1] * q[1] + d[2] * q[2])
    if v < 0.0 or u + v > 1.0:
        return False
    t = f * (e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2])
    return 0.02 < t < 0.98          # touching at either end does not count


def _z_on(tri, x, y):
    a, b, c, nx, ny, nz = tri
    # inside test that does not care about winding
    def side(p, q):
        return (q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0])
    s1, s2, s3 = side(a, b), side(b, c), side(c, a)
    if (s1 < -1e-9 or s2 < -1e-9 or s3 < -1e-9) and (s1 > 1e-9 or s2 > 1e-9 or s3 > 1e-9):
        return None
    return a[2] - (nx * (x - a[0]) + ny * (y - a[1])) / nz


class Surface:
    def __init__(self, level_dir, objects_qsc, objects, sizes, skip_refs=(), nodes=()):
        self.terrain = None
        try:
            self.terrain = Terrain(level_dir, objects_qsc)
        except (OSError, struct.error):
            pass
        f = MI.level_files(level_dir)
        self._res = None
        self._res_path = f["models"] if f else None
        self._meshes = {}
        self._others = {}
        skip = set(skip_refs)
        self._sizes = sizes
        # navmesh nodes sit exactly on walkable surfaces - including building
        # floors, which are not part of a building's collision mesh
        self.nodes = [(n["x"], n["y"], n["z"]) for n in nodes]
        self.objects = []
        for o in objects:
            if o.get("type") not in ("building", "prop") or o.get("cutscene") or o.get("ref") in skip:
                continue
            if sizes.get(o.get("model")):
                self.objects.append((o, self.radius(o)))

    def _body(self, model):
        """A model's .mef, from this level's archive or - for a model the plan is
        about to import - from the first other level that packs it."""
        if self._res is None:
            self._res = {}
            if self._res_path and self._res_path.exists():
                for stem, _, body in MI.res_entries(self._res_path)[1]:
                    self._res[stem] = body
        if model not in self._res and self._res_path is not None:
            location0 = self._res_path.parents[2]
            for lv in sorted(location0.glob("level*")):
                f = MI.level_files(lv)
                if not f or not f["models"].exists() or f["models"] == self._res_path:
                    continue
                idx = self._others.get(lv)
                if idx is None:
                    idx = self._others[lv] = {stem: body for stem, _, body in MI.res_entries(f["models"])[1]}
                if model in idx:
                    self._res[model] = idx[model]
                    break
            else:
                self._res[model] = None
        body = self._res.get(model)
        # BODY chunk = 16-byte chunk header + the .mef (itself an ILFF file)
        return body[16:] if body else None

    def _mesh(self, model):
        if model not in self._meshes:
            body = self._body(model)
            self._meshes[model] = collision_mesh(body) if body else []
        return self._meshes[model]

    def _solid(self, model):
        key = ("all", model)
        if key not in self._meshes:
            body = self._body(model)
            self._meshes[key] = collision_all(body) if body else []
        return self._meshes[key]

    def radius(self, o):
        """A circle round the model origin that surely contains its footprint."""
        s = self._sizes.get(o.get("model")) or {}
        return math.hypot(s.get("w", 0), s.get("d", 0)) / 2 + math.hypot(s.get("cx", 0), s.get("cy", 0))

    def add_object(self, o):
        """Count another object as solid ground and wall (one the plan places)."""
        if self._sizes.get(o.get("model")):
            self.objects.append((o, self.radius(o)))

    def blocked(self, a, b, heights=(0.5, 1.3), ignore=(), width=0.6, only=None):
        """What solid thing a guard walking from a to b (world, feet) would pass through.

        Tested at knee and chest height, so kerbs and low sills do not count but
        walls and fences do. Doors are not in the object list - they open. The
        walk is blocked only if the centre line and the lines `width` to either
        side all hit: shipped links often shave a building's corner or pass a
        pole, and guards slide round those in the game. `only` tests one object,
        listed or not. Returns the blocking object, or None when the way is clear.
        """
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1e-6:
            return None
        px, py = -(b[1] - a[1]) / L * width, (b[0] - a[0]) / L * width
        pool = [(only, self.radius(only))] if only is not None else             [(o, r) for o, r in self.objects if not any(o is x for x in ignore)]
        for o, r in pool:
            if not self._hit(o, r, a, b, heights):
                continue
            if all(self._hit(o, r, (a[0] + k * px, a[1] + k * py, a[2]),
                             (b[0] + k * px, b[1] + k * py, b[2]), heights) for k in (1, -1)):
                return o
        return None

    def _hit(self, o, r, a, b, heights):
        """Does the segment a-b cross the object's collision mesh?"""
        ax, ay = a[0] - o["x"], a[1] - o["y"]
        bx, by = b[0] - o["x"], b[1] - o["y"]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        if (ax + t * dx) ** 2 + (ay + t * dy) ** 2 > r * r:
            return False
        tris = self._solid(o["model"])
        if not tris:
            return False
        g = o.get("gamma") or 0.0
        c, s = math.cos(g), math.sin(g)
        ma = (ax * c + ay * s, -ax * s + ay * c)
        mb = (bx * c + by * s, -bx * s + by * c)
        for h in heights:
            pa = (ma[0], ma[1], a[2] + h - o["z"])
            pb = (mb[0], mb[1], b[2] + h - o["z"])
            d = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
            if any(_seg_hits_tri(pa, d, tri) for tri in tris):
                return True
        return False

    def candidates(self, x, y, skip=None):
        """Every surface height at (x, y): terrain first, then built surfaces.
        `skip` is an object ref whose own surfaces do not count (the object being set down)."""
        out = []
        if self.terrain is not None:
            t = self.terrain.z(x, y)
            if t is not None:
                out.append(("terrain", t, None))
        for o, r in self.objects:
            if skip is not None and o.get("ref") == skip:
                continue
            out.extend(self.tops(o, x, y, r))
        for nx, ny, nz in self.nodes:
            if (nx - x) ** 2 + (ny - y) ** 2 <= NODE_REACH ** 2:
                out.append(("node", nz, None))
        return out

    def tops(self, o, x, y, r=None):
        """Heights of one object's upward surfaces above (x, y): (model, z, object)."""
        r = self.radius(o) if r is None else r
        dx, dy = x - o["x"], y - o["y"]
        if dx * dx + dy * dy > r * r:
            return []
        g = o.get("gamma") or 0.0
        c, s = math.cos(g), math.sin(g)
        mx, my = dx * c + dy * s, -dx * s + dy * c          # world -> model
        out = []
        for tri in self._mesh(o["model"]):
            z = _z_on(tri, mx, my)
            if z is not None:
                out.append((o.get("model"), o["z"] + z, o))
        return out

    def height(self, x, y, near_z, reach_up=0.8, skip=None, trust_near=True):
        """The surface an object dropped near near_z comes to rest on: (source, z).

        Out in the open the terrain and the tops of built surfaces are exact, and
        nodes are ignored - a node on a concrete apron two metres away must not
        lift an object that stands on bare ground. Under a roof the building's
        collision floor is often its foundation, not the floor people walk on;
        there the nodes, which sit on that floor, are the better answer - and so is
        near_z itself when it is a floor someone picked (trust_near).
        """
        cs = self.candidates(x, y, skip)
        if not cs:
            return None, None
        roofed = any(c[1] > near_z + 1.8 for c in cs if c[0] not in ("terrain", "node"))
        if roofed:
            pool = cs + ([("floor", near_z, None)] if trust_near else [])
        else:
            pool = [c for c in cs if c[0] != "node"]
        pool = pool or cs
        below = [c for c in pool if c[1] <= near_z + reach_up]
        if below:
            best = max(below, key=lambda c: c[1])
        else:
            best = min(pool, key=lambda c: c[1])
        return best[0], best[1]

    # How high each kind of thing may sit above the terrain when it is dropped
    # without a height: a guard steps onto a kerb, an apron or a low platform but
    # not onto a desk; a pickup lands on a desk, crate or bed.
    DROP = {"soldier": (0.35, 0.25), "building": (0.35, 0.25), "pickup": (1.2, 0.8)}
    PICKUP_RISE = 0.5            # a pickup on open ground, like the shipped ones
    PICKUP_ON_TOP = 0.02         # ... and lying on furniture (median +0.03 over 52)

    def under_footprint(self, model, x, y, gamma=0.0, skip=None, spacing=1.5):
        """(what the lowest point stands on, its height, how much the ground varies)
        over a model's footprint, sampled every `spacing` metres."""
        s = self._sizes.get(model) or {}
        c, sn = math.cos(gamma or 0.0), math.sin(gamma or 0.0)
        low, high = None, None
        for r in s.get("body") or []:
            nx = max(1, int(math.ceil(r[2] / spacing)))
            ny = max(1, int(math.ceil(r[3] / spacing)))
            for i in range(nx + 1):
                for j in range(ny + 1):
                    mx, my = r[0] + r[2] * i / nx, r[1] + r[3] * j / ny
                    px, py = x + mx * c - my * sn, y + mx * sn + my * c
                    t = self.terrain.z(px, py) if self.terrain is not None else None
                    if t is None:
                        continue
                    src, z = self.height(px, py, t + 0.35, reach_up=0.25, skip=skip, trust_near=False)
                    if z is None:
                        continue
                    if low is None or z < low[1]:
                        low = (src, z)
                    if high is None or z > high:
                        high = z
        if low is None:
            return None, None, None
        return low[0], low[1], high - low[1]

    def rest(self, kind, x, y, near_z=None, model=None, skip=None, gamma=0.0):
        """(z to write, what it rests on) for a guard, pickup or model at (x, y).

        A guard's z is his feet: 66 shipped guards in levels 1-9 stand within
        7 mm of the terrain, and the engine does not drop one that is placed in
        the air. With near_z (a floor or height already chosen) the surface nearest
        below it wins; without, the thing is dropped from just above the ground.
        """
        explicit = near_z is not None
        self.last = {}
        if not explicit and kind == "building" and model and (self._sizes.get(model) or {}).get("body"):
            # a building rests on the lowest ground under its whole footprint: on a
            # slope the uphill side sinks in rather than the downhill side floating
            src, z, spread = self.under_footprint(model, x, y, gamma, skip)
            self.last = {"spread": spread}
        elif not explicit:
            t = self.terrain.z(x, y) if self.terrain is not None else None
            if t is None:
                return None, None
            lift, reach = self.DROP.get(kind, (0.35, 0.25))
            src, z = self.height(x, y, t + lift, reach_up=reach, skip=skip, trust_near=False)
        else:
            src, z = self.height(x, y, near_z, skip=skip)
        if z is None:
            return None, None
        if kind == "building" and model:
            # models are set down by their lowest point, ignoring a base plate of a few cm
            z0 = (self._sizes.get(model) or {}).get("z0", 0.0)
            z -= z0 if z0 < -0.1 else 0.0
        elif kind == "pickup":
            z += self.PICKUP_RISE if src in ("terrain", "node", "floor") else self.PICKUP_ON_TOP
        return z, src
