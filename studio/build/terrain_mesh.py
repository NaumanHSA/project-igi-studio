# The terrain mesh itself: terrain.ctr and terrain.cmd, read, written, and
# rebuilt from a height grid where a mission's ground needs more than the
# ±4 m a height map can move it (studio/build/terrain.py reads heights from it,
# studio/build/flatten.py writes the height maps on top).
#
#   tree = Tree.load(level_dir / "terrain")         tree.save(folder)
#   H = grid_heights(tree, gi0, gi1, gj0, gj1)       {(gi, gj): z3} every 4 m
#   tree2, report = rebuild(tree, heights, changed)  copy-on-write, see below
#
# What the files hold (decoded from the game's data, 2026-09-21):
#
#   terrain.ctr  32-byte nodes: 8 x i16 child index, 8 x i8 child transform
#                (-1 where there is no child), u8 child mask, 3 pad bytes (the
#                same in every node of a level), u32 offset of the node's mesh in
#                .cmd. Node 0 is unused, node 1 is the root, a cube +-2^30 raw
#                wide. Leaves are at level 16 (8 m cubes). Nodes and meshes are
#                shared, the children rotated or mirrored by their transform, so
#                the tree is a graph: nothing in it is ever edited in place.
#   terrain.cmd  meshes back to back: u16 triangles, u16 4 x triangles, u16
#                fixed vertices, u16 sliding vertices, then u32 per triangle
#                (indices at bits 16, 0, 8 in drawing order; top byte 0xE0, 0xF0
#                at the end of a strip) and u32 per vertex (x, y, z in 6 bits at
#                bits 26, 20, 14, 0..48 across the cube; texture projection at
#                bits 8-9 and 6-7 for steep faces; bits 0-5 the fixed vertex a
#                sliding one merges into as the cube is seen from further away).
#
# Every cube at every level is the same thing: a 3 x 3 grid over its square
# (corners fixed, edge middles and centre sliding onto a corner), 8 triangles on
# the anti-diagonal, cut where the ground leaves the cube through its floor or
# ceiling (the cut points are fixed). A grid point has the same height at every
# level it appears on, so the terrain is one grid of heights, a sample every
# 4 m; a point first seen at level L sits on that level's height step,
# 2^(27-L)/3 raw (0.17 m at the leaves, 2.7 m for every 64 m point).
#
# Heights here are z3: three times the raw height (raw = metres x 4096), which
# every vertex of every level is a whole number of.
#
# Nor is a grid point ever exactly on a cube's floor or ceiling, or its middle
# height, at any level: inside its cube a point is only ever 4, 8, 10, 14, 16,
# 20, 28, 32, 34, 38, 40 or 44 of the 48 steps up (every level, levels 1, 7,
# 11). A point on a floor is in the cube under it and the one over it at once,
# with nothing of the ground on one side of it, so the cubes beside disagree on
# what their shared side looks like. settle keeps new heights off the floors
# (every 8 m; every level's floors and middles are among them) - not to the
# game's full rule, which would move a point every 256 m by up to 40 m.
#
# Not quite everywhere: here and there the ground folds over itself (a cliff
# that hangs over, level 7 has about one every 100 m of cliff), and a grid
# point there has two heights, 20-30 m apart, in the cubes above each other.
# Such a cube cannot be built again from one height per point - see _folds.
import collections, pathlib, struct

ROOT_HALF = 1 << 30
LEAF = 16
GRID = 1 << 14                 # raw units between grid points: 4 m
MIN_LEVEL = 7                  # the coarsest level the game draws; above it meshes are kept as shipped
NODE_LIMIT = 32767             # child indices are i16
FLOOR3 = 3 * (1 << 15)         # a leaf's height (8 m) in z3: every cube's floor is on a multiple

CUBE_IDX_TABLE = [
    0, 1, 2, 3, 4, 5, 6, 7,
    2, 0, 3, 1, 6, 4, 7, 5,
    3, 2, 1, 0, 7, 6, 5, 4,
    1, 3, 0, 2, 5, 7, 4, 6,
    1, 0, 3, 2, 5, 4, 7, 6,
    3, 1, 2, 0, 7, 5, 6, 4,
    2, 3, 0, 1, 6, 7, 4, 5,
    0, 2, 1, 3, 4, 6, 5, 7,
]
CUBE_TRANS_TABLE = [
    0, 1, 2, 3, 4, 5, 6, 7,
    1, 2, 3, 0, 5, 6, 7, 4,
    2, 3, 0, 1, 6, 7, 4, 5,
    3, 0, 1, 2, 7, 4, 5, 6,
    4, 7, 6, 5, 0, 3, 2, 1,
    5, 4, 7, 6, 1, 0, 3, 2,
    6, 5, 4, 7, 2, 1, 0, 3,
    7, 6, 5, 4, 3, 2, 1, 0,
]
CHILD_ACCESS_ORDER = (4, 0, 5, 1, 6, 2, 7, 3)
OCTANTS = [(x, y, z) for z in (-1, 1) for y in (-1, 1) for x in (-1, 1)]   # octant k: x + 2y + 4z

# the plain 3 x 3 cube, exactly as the game's own: fixed corners, then the
# edge middles and the centre, each sliding onto the corner named
GRID9 = [(0, 0), (48, 0), (0, 48), (48, 48), (0, 24), (24, 0), (48, 24), (24, 48), (24, 24)]
TRIS8 = [(0, 5, 4), (5, 8, 4), (5, 1, 8), (1, 6, 8), (3, 7, 6), (7, 8, 6), (7, 2, 8), (2, 4, 8)]
STRIP8 = (0xE0, 0xE0, 0xE0, 0xF0, 0xE0, 0xE0, 0xE0, 0xF0)
SLIDE9 = {4: 0, 5: 0, 6: 1, 7: 2, 8: 0}


def step3(level):
    """A level's height step, in z3."""
    return 1 << (27 - level)


def half(level):
    return ROOT_HALF >> level


# ---------------------------------------------------------------- meshes
class Mesh:
    """verts: [x, y, z, flags, slide] with flags = tex1 << 2 | tex2 (bits 8-9, 6-7),
    fixed ones first (nfixed of them); tris: [a, b, c, top] in drawing order."""
    __slots__ = ("verts", "nfixed", "tris")

    def __init__(self, verts, nfixed, tris):
        self.verts, self.nfixed, self.tris = verts, nfixed, tris

    @staticmethod
    def decode(cmd, off):
        ntri, voff, nfix, nslide = struct.unpack_from("<4H", cmd, off)
        tw = struct.unpack_from("<%dI" % ntri, cmd, off + 8)
        vw = struct.unpack_from("<%dI" % (nfix + nslide), cmd, off + 8 + 4 * ntri)
        verts = [[(v >> 26) & 63, (v >> 20) & 63, (v >> 14) & 63, (v >> 6) & 15, v & 63] for v in vw]
        tris = [[(t >> 16) & 255, t & 255, (t >> 8) & 255, t >> 24] for t in tw]
        return Mesh(verts, nfix, tris)

    def encode(self):
        out = bytearray(struct.pack("<4H", len(self.tris), 4 * len(self.tris), self.nfixed,
                                    len(self.verts) - self.nfixed))
        for a, b, c, top in self.tris:
            out += struct.pack("<I", (top << 24) | (a << 16) | (c << 8) | b)
        for x, y, z, fl, sl in self.verts:
            out += struct.pack("<I", (x << 26) | (y << 20) | (z << 14) | (fl << 6) | sl)
        return bytes(out)

    @staticmethod
    def size_at(cmd, off):
        ntri, _, nfix, nslide = struct.unpack_from("<4H", cmd, off)
        return 8 + 4 * (ntri + nfix + nslide)


def _world_xy(x, y, trans):
    """A vertex's place in the cube as the game draws it under a transform
    (x, y from the cube's centre, in steps of 1/24 of its half width)."""
    vx, vy = x - 24, y - 24
    if trans & 4:
        vx = 24 - x
    if trans & 1:
        if trans & 2:
            vx = -vx
        else:
            vy = 24 - y
        vx, vy = vy, vx
    elif trans & 2:
        vx = -vx
        vy = 24 - y
    return vx, vy


def oriented(mesh, trans):
    """The mesh as it looks under a transform, written for the identity one."""
    if trans == 0:
        return Mesh([list(v) for v in mesh.verts], mesh.nfixed, [list(t) for t in mesh.tris])
    verts = []
    for x, y, z, fl, sl in mesh.verts:
        vx, vy = _world_xy(x, y, trans)
        t1, t2 = fl >> 2, fl & 3
        # the projection flag's low bit is read against the transform's
        if trans & 1:
            t1 = (3 - t1) if t1 else 0
            t2 = (3 - t2) if t2 else 0
        verts.append([vx + 24, vy + 24, z, (t1 << 2) | t2, sl])
    tris = []
    for a, b, c, top in mesh.tris:
        # a mirrored cube is drawn the other way round (terrain.py's ids), so its
        # faces still face up
        tris.append([c, b, a, top] if trans & 4 else [a, b, c, top])
    return Mesh(verts, mesh.nfixed, tris)


# ---------------------------------------------------------------- the tree
class Tree:
    def __init__(self, ctr, cmd):
        self.nodes = []
        for i in range(0, len(ctr) - 31, 32):
            f = struct.unpack_from("<8h8bB3sI", ctr, i)
            self.nodes.append([list(f[0:8]), list(f[8:16]), f[16], f[17], f[18]])
        self.cmd = bytearray(cmd)
        self.pad = collections.Counter(n[3] for n in self.nodes[1:]).most_common(1)[0][0] if len(self.nodes) > 1 else b"\0\0\0"

    @classmethod
    def load(cls, folder):
        folder = pathlib.Path(folder)
        return cls((folder / "terrain.ctr").read_bytes(), (folder / "terrain.cmd").read_bytes())

    def ctr_bytes(self):
        out = bytearray()
        for ch, tr, mask, pad, off in self.nodes:
            out += struct.pack("<8h8bB3sI", *ch, *tr, mask, pad, off)
        return bytes(out)

    def save(self, folder):
        folder = pathlib.Path(folder)
        (folder / "terrain.ctr").write_bytes(self.ctr_bytes())
        (folder / "terrain.cmd").write_bytes(bytes(self.cmd))

    def mesh(self, ni):
        return Mesh.decode(self.cmd, self.nodes[ni][4])

    def children(self, ni, trans):
        """[(octant, child node, child's transform)] as the game walks them."""
        nd = self.nodes[ni]
        order = CUBE_IDX_TABLE[trans * 8:trans * 8 + 8]
        tl = CUBE_TRANS_TABLE[trans * 8:trans * 8 + 8]
        out = []
        for access in range(8):
            slot = order[access]
            if nd[2] & (1 << slot):
                out.append((access, nd[0][slot], tl[nd[1][slot]]))
        return out


def cube_centre(parent, level, octant):
    """The centre of a child cube (level is the child's)."""
    h = half(level)
    ox, oy, oz = OCTANTS[octant]
    return (parent[0] + ox * h, parent[1] + oy * h, parent[2] + oz * h)


# ---------------------------------------------------------------- the height grid
def _walk_leaves(tree, x0, x1, y0, y1, fn):
    """fn(node, centre, trans) for every leaf whose square touches the box (raw)."""
    stack = [(1, (0, 0, 0), 0, 0)]
    while stack:
        ni, c, level, trans = stack.pop()
        h = half(level)
        if c[0] + h < x0 or c[0] - h > x1 or c[1] + h < y0 or c[1] - h > y1:
            continue
        if level == LEAF:
            fn(ni, c, trans)
            continue
        for octant, child, ct in tree.children(ni, trans):
            stack.append((child, cube_centre(c, level + 1, octant), level + 1, ct))


def grid_heights(tree, gi0, gi1, gj0, gj1):
    """{(gi, gj): z3} for the grid points in a box (grid units, inclusive), from
    the leaves. A point with no terrain over it is missing; one where the
    ground folds over itself has the upper height, the one the game stands
    things on (see _folds)."""
    out = {}
    s = step3(LEAF)

    def leaf(ni, c, trans):
        m = tree.mesh(ni)
        bz = 3 * (c[2] - half(LEAF))
        gc, gcy = c[0] // GRID, c[1] // GRID
        for x, y, z, fl, sl in m.verts:
            vx, vy = _world_xy(x, y, trans)
            if vx % 24 or vy % 24:
                continue
            key = (gc + vx // 24, gcy + vy // 24)
            if gi0 <= key[0] <= gi1 and gj0 <= key[1] <= gj1:
                out[key] = max(out.get(key, bz + z * s), bz + z * s)
    _walk_leaves(tree, gi0 * GRID - 1, gi1 * GRID + 1, gj0 * GRID - 1, gj1 * GRID + 1, leaf)
    return out


def grid_level(gi, gj):
    """The coarsest level a grid point is a grid point of (its heights's step)."""
    v = 16
    while v > 0 and gi % 2 == 0 and gj % 2 == 0 and (gi or gj):
        gi //= 2
        gj //= 2
        v -= 1
    return v if (gi or gj) else 0


# ---------------------------------------------------------------- one cube
# A cube's mesh has to stay small. The game keeps each cube it draws in a
# fixed pool of buffers - 700 of 1600 bytes, 50 of 3200, 16 of 8000 (as the
# project-igi-editor renderer has them) - and a vertex costs 52 to 116 bytes
# there, more with each ground material the cube shows. Its own meshes never
# pass 35 vertices and 17 triangles, and nearly all fit 1600 bytes. A mesh
# that needs a big buffer takes one of the few, and when they run out the
# cube is not drawn (a hole) or drawn from garbage (a spike). So: the ground
# is cut where it leaves the cube through its floor or ceiling and nowhere
# else; the game's own middle-height points are kept only on an unchanged
# piece of the square's edge, where the level's cube beside has them; and a
# steep face takes its texture from the side without doubling vertices,
# unless the mesh stays small.
SMALL = 24                      # vertices a mesh may have with doubled ones for steep faces


def _rdiv(n, d):
    """n / d to the nearest whole number, halves away from zero."""
    q, r = divmod(abs(n), d)
    if 2 * r >= d:
        q += 1
    return q if n >= 0 else -q


def _cut(p, q, zc):
    """Where the edge p-q crosses z = zc, rounded to the cube's steps. Worked
    from the edge's own endpoints in a fixed order, so every cube that has this
    edge (the one beside it, the one above) gets the same point."""
    if (p[0], p[1], p[2]) > (q[0], q[1], q[2]):
        p, q = q, p
    dz = q[2] - p[2]
    nx = p[0] * (q[2] - zc) + q[0] * (zc - p[2])
    ny = p[1] * (q[2] - zc) + q[1] * (zc - p[2])
    if dz < 0:
        nx, ny, dz = -nx, -ny, -dz
    out = [_rdiv(nx, dz), _rdiv(ny, dz)]
    # the cut is strictly between the edge's ends: rounding must not put it on
    # a grid line the edge only crosses (the cube's side among them), where the
    # cube beside would have no such point
    for axis in (0, 1):
        lo, hi = min(p[axis], q[axis]), max(p[axis], q[axis])
        if hi - lo >= 2:
            out[axis] = max(lo + 1, min(hi - 1, out[axis]))
    return (out[0], out[1], zc)


def _clip_slab(tri, own_edge=None):
    """A triangle cut to the cube's slab, 0 <= z <= 48: its corners inside and the
    points where its edges cross the floor or the ceiling, in order round it.
    tri: three (point, tag) with integer points, tagged ("grid", k) or ("cut", sliding).
    own_edge(k1, k2, p, q) -> [(t, point, sliding)] the level's own points along
    a piece of the square's edge that must meet the cube beside as before
    (its cut points, which replace ours, and its middle-height points)."""
    out = []
    for i in range(3):
        (p, tp), (q, tq) = tri[i], tri[(i + 1) % 3]
        if 0 <= p[2] <= 48:
            out.append((p, tp))
        on = []
        kept = own_edge(tp[1], tq[1], p, q) if own_edge and tp[0] == "grid" and tq[0] == "grid" else None
        if kept is not None:
            on = kept
        else:
            for zc in (0, 48):
                if (p[2] - zc) * (q[2] - zc) < 0:
                    on.append(((zc - p[2]) / (q[2] - p[2]), _cut(p, q, zc), False))
        for _, pt, slides in sorted(on, key=lambda e: e[0]):
            out.append((pt, ("cut", slides)))
    return out


def _normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    wx, wy, wz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return (uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx)


def _flags(a, b, c):
    """Texture projection for a face: 0 from above; a steep face takes the
    texture from its side (tex1 << 2 | tex2: 1 reads u along y, 2 along x)."""
    nx, ny, nz = _normal(a, b, c)
    if nz * nz * 3 >= nx * nx + ny * ny:            # flatter than 60 degrees
        return 0
    return 5 if abs(nx) >= abs(ny) else 10


# the eight pieces of a cube's square's edge, by the grid points at their ends
BORDER = {frozenset(e) for e in ((0, 5), (5, 1), (1, 6), (6, 3), (3, 7), (7, 2), (2, 4), (4, 0))}


def _own_edge(own, keep):
    """For a cube built again: along each piece of its square's edge that did
    not change (keep), the level's own points - its cut points through the
    floor and ceiling and its middle-height ones - in place of ours. The cube
    beside, which has the same edge, keeps them, so the two meet."""
    if own is None or not keep:
        return None
    # once each: the level's meshes write a point again for each texture
    # projection its faces use
    pts = list(dict.fromkeys(tuple(v[:3]) for v in own.verts if v[2] in (0, 24, 48)))
    slides = {tuple(v[:3]): i >= own.nfixed for i, v in enumerate(own.verts)}

    def along(k1, k2, p, q):
        if frozenset((k1, k2)) not in keep:
            return None
        (ax, ay), (bx, by) = GRID9[k1], GRID9[k2]
        span = abs(bx - ax) + abs(by - ay)
        out = []
        for x, y, z in pts:
            if (bx - ax) * (y - ay) != (by - ay) * (x - ax):
                continue
            if not (min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by)):
                continue
            if (x, y) in ((ax, ay), (bx, by)):
                continue
            t = (abs(x - p[0]) + abs(y - p[1])) / span      # from p, along the piece
            if z in (0, 48) and not ((p[2] - z) * (q[2] - z) < 0):
                continue                                    # a cut our edge does not make
            out.append((t, (x, y, z), slides.get((x, y, z), z == 24)))
        # a crossing the level's own cube did not have (it cannot, the ends are
        # the same) would be ours
        for zc in (0, 48):
            if (p[2] - zc) * (q[2] - zc) < 0 and not any(e[1][2] == zc for e in out):
                out.append(((zc - p[2]) / (q[2] - p[2]), _cut(p, q, zc), False))
        return out
    return along


def cube_mesh(z9, bottom3, level, own=None, keep=None):
    """The mesh of one cube: z9 the heights (z3) of its 3 x 3 grid in GRID9
    order, bottom3 the z3 of its floor. None when the ground misses it.
    own/keep: the level's own mesh of this cube (as drawn, identity transform)
    and the pieces of its edge that did not change - see _own_edge."""
    s = step3(level)
    lz = []
    for z in z9:
        q, r = divmod(z - bottom3, s)
        lz.append(q if 2 * r < s else q + 1)          # heights come snapped; this only guards
    if min(lz) > 48 or max(lz) < 0:
        return None
    own_edge = _own_edge(own, keep)
    pts = [((GRID9[k][0], GRID9[k][1], lz[k]), ("grid", k)) for k in range(9)]
    plain = min(lz) >= 0 and max(lz) <= 48
    if plain and own_edge is not None:
        # the level's own middle-height points on a kept piece need a place in it
        plain = not any(own_edge(a, b, pts[a][0], pts[b][0]) for a, b in (tuple(e) for e in keep))
    if plain:
        # the whole square in this cube: the game's own layout, triangle for triangle
        verts = [[GRID9[k][0], GRID9[k][1], lz[k], 0, SLIDE9.get(k, 0)] for k in range(9)]
        tris = [[a, b, c, STRIP8[i]] for i, (a, b, c) in enumerate(TRIS8)]
        return _with_flags(_adopt_slides(Mesh(verts, 4, tris), own, keep))
    polys = []
    for a, b, c in TRIS8:
        poly = _clip_slab([pts[a], pts[b], pts[c]], own_edge)
        if len(poly) >= 3:
            polys.append(poly)
    return _assemble(polys, own, keep) if polys else None


def _assemble(polys, own=None, keep=None):
    """Cut pieces into a mesh: fixed vertices (corners and cut points) first,
    sliding ones (the grid's middles and centre, and the level's own middle-
    height points kept on its edge) after, each onto a fixed one."""
    fixed, sliding, index, faces = [], [], {}, []
    for poly in polys:
        # a point twice in a row would make every fan from it flat
        poly = [e for i, e in enumerate(poly) if e[0] != poly[i - 1][0]] if len(poly) > 1 else poly
        if len(poly) < 3:
            continue
        ids = []
        for (x, y, z), tag in poly:
            key = (x, y, z)
            ent = index.get(key)
            if ent is None:
                slides = tag[1] >= 4 if tag[0] == "grid" else tag[1]
                lst = sliding if slides else fixed
                ent = index[key] = (not slides, len(lst))
                lst.append([x, y, z, 0, 0, tag])
            ids.append(ent)
        # a fan from a corner that leaves no face flat: a cut polygon can have
        # points in a row along an edge (a kept middle-height point), and a fan
        # from one of them would drop the face along it, leaving the point
        # hanging on the edge
        pos = [p for p, _ in poly]
        k = len(ids)
        for r in range(k):
            if all(_normal(pos[r], pos[(r + i) % k], pos[(r + i + 1) % k]) != (0, 0, 0) for i in range(1, k - 1)):
                break
        else:
            r = 0
        for i in range(1, k - 1):
            faces.append((ids[r], ids[(r + i) % k], ids[(r + i + 1) % k]))
    if not fixed:
        return None
    nfix = len(fixed)
    verts = [v[:5] for v in fixed] + [v[:5] for v in sliding]
    for j, v in enumerate(sliding):
        verts[nfix + j][4] = _slide_to(v, fixed)
    tris = []
    for f in faces:
        ia, ib, ic = [e[1] if e[0] else nfix + e[1] for e in f]
        if len({ia, ib, ic}) < 3 or _normal(verts[ia], verts[ib], verts[ic]) == (0, 0, 0):
            continue                                      # nothing left of it after rounding
        tris.append([ia, ib, ic, 0xF0])                   # each face a strip of its own
    if not tris:
        return None
    return _with_flags(_adopt_slides(Mesh(verts, nfix, tris), own, keep))


def _adopt_slides(m, own, keep=None):
    """Where the level's own cube had the same sliding point, it slides onto the
    same fixed one as before - inside the square, and on the pieces of its edge
    that did not change (keep), where the cube beside expects it: the game's
    cubes are stored turned every way, so which corner a middle slides onto
    varies. On a changed edge both cubes use _slide_to's rule instead."""
    if own is None:
        return m
    was = {tuple(v[:3]): tuple(own.verts[v[4]][:3]) for v in own.verts[own.nfixed:]}
    at = {tuple(v[:3]): i for i, v in enumerate(m.verts[:m.nfixed])}
    for v in m.verts[m.nfixed:]:
        on_edge = v[0] in (0, 48) or v[1] in (0, 48)
        if on_edge and not _on_kept(v, keep):
            continue
        t = at.get(was.get(tuple(v[:3])))
        if t is not None:
            v[4] = t
    return m


def _on_kept(v, keep):
    """Does a point on the edge of the square lie on one of the kept pieces?"""
    for e in keep or ():
        k1, k2 = tuple(e)
        (ax, ay), (bx, by) = GRID9[k1], GRID9[k2]
        if (bx - ax) * (v[1] - ay) == (by - ay) * (v[0] - ax) and \
                min(ax, bx) <= v[0] <= max(ax, bx) and min(ay, by) <= v[1] <= max(ay, by):
            return True
    return False


def _slide_to(v, fixed):
    """The fixed vertex a sliding one merges into. One on the edge of the
    cube's square: the nearest along that edge, a tie to the lower one - the
    game's own rule for a plain cube (SLIDE9), and decided by where the points
    are, so the cube beside, which has the same points on that edge, picks the
    same one. One inside the square: the nearest counting height too, so
    merging never pulls a face across the cube."""
    x, y, z = v[0], v[1], v[2]
    side = (0, x) if x in (0, 48) else (1, y) if y in (0, 48) else None
    if side is not None:
        best, bd = None, None
        for i, f in enumerate(fixed):
            if f[side[0]] != side[1]:
                continue
            along = f[1] if side[0] == 0 else f[0]
            d = ((f[0] - x) ** 2 + (f[1] - y) ** 2, along, f[2])
            if bd is None or d < bd:
                best, bd = i, d
        if best is not None:
            return best
    best, bd = 0, None
    for i, f in enumerate(fixed):
        d = ((f[0] - x) ** 2 + (f[1] - y) ** 2 + (f[2] - z) ** 2, f[0], f[1], f[2])
        if bd is None or d < bd:
            best, bd = i, d
    return best


def _with_flags(m):
    """Steep faces take their texture from the side. A vertex shared by faces
    that want different projections is written once for each - while the mesh
    stays small; past that, each vertex takes the projection most of its faces
    want (see SMALL)."""
    want = [_flags(m.verts[a], m.verts[b], m.verts[c]) for a, b, c, _ in m.tris]
    if not any(want):
        return m
    uses = collections.defaultdict(list)             # vertex -> the projections its faces want
    for (a, b, c, _), fl in zip(m.tris, want):
        for i in (a, b, c):
            uses[i].append(fl)
    extra = sum(len(set(u)) - 1 for u in uses.values())
    if len(m.verts) + extra > SMALL:
        verts = [list(v) for v in m.verts]
        for i, u in uses.items():
            c = collections.Counter(u).most_common()
            verts[i][3] = max(c, key=lambda e: (e[1], e[0] != 0))[0]
        return Mesh(verts, m.nfixed, [list(t) for t in m.tris])
    order = {i: list(dict.fromkeys(u)) for i, u in uses.items()}
    fixed_out, slide_out, where = [], [], {}
    for i, v in enumerate(m.verts):
        for fl in order.get(i) or [0]:
            lst = fixed_out if i < m.nfixed else slide_out
            where[(i, fl)] = (i < m.nfixed, len(lst))
            lst.append([v[0], v[1], v[2], fl, v[4], i])
    nfix = len(fixed_out)

    def at(i, fl):
        f, k = where[(i, fl)] if (i, fl) in where else where[(i, (order.get(i) or [0])[0])]
        return k if f else nfix + k
    verts = [v[:5] for v in fixed_out] + [v[:5] for v in slide_out]
    for j, v in enumerate(slide_out):
        # onto the copy of its fixed vertex with the same projection, or its first
        verts[nfix + j][4] = at(v[4], v[3])
    tris = [[at(a, fl), at(b, fl), at(c, fl), top] for (a, b, c, top), fl in zip(m.tris, want)]
    return Mesh(verts, nfix, tris)


def buffer_bytes(m, materials=1):
    """What the game's renderer keeps for this mesh while it draws it (the
    project-igi-editor port: cube data, vertex positions, and a texture set of
    uv's per ground material, twice, plus the light map's)."""
    nfix = m.nfixed
    nslide = len(m.verts) - nfix
    per = 12 * nfix + 20 * nslide + 4
    return 32 + 16 * len(m.verts) + 16 + (2 * materials + 1) * per


# ---------------------------------------------------------------- heights anywhere
class Heights:
    """The level's own grid heights: a block read at once, any other point walked
    to when it is asked for (the far corners of big cubes)."""

    def __init__(self, tree, box=None):
        self.tree, self.h = tree, {}
        if box:
            self.h.update(grid_heights(tree, *box))

    def __call__(self, gi, gj):
        key = (gi, gj)
        if key not in self.h:
            self.h[key] = point_height(self.tree, gi, gj)
        return self.h[key]


def point_height(tree, gi, gj):
    """One grid point's height (z3), from the leaves round it, or None (the
    upper one where the ground folds over itself, as grid_heights)."""
    x, y = gi * GRID, gj * GRID
    s = step3(LEAF)
    best = None
    stack = [(1, (0, 0, 0), 0, 0)]
    while stack:
        ni, c, level, trans = stack.pop()
        h = half(level)
        if not (c[0] - h <= x <= c[0] + h and c[1] - h <= y <= c[1] + h):
            continue
        if level == LEAF:
            for vx0, vy0, z, fl, sl in tree.mesh(ni).verts:
                vx, vy = _world_xy(vx0, vy0, trans)
                if vx % 24 == 0 and vy % 24 == 0 and c[0] + (vx // 24) * h == x and c[1] + (vy // 24) * h == y:
                    z3 = 3 * (c[2] - h) + z * s
                    best = z3 if best is None else max(best, z3)
            continue
        for octant, child, ct in tree.children(ni, trans):
            stack.append((child, cube_centre(c, level + 1, octant), level + 1, ct))
    return best


def settle(targets, own):
    """Grid heights the game can hold. targets {(gi, gj): z3 wanted} for the
    points that change, own(gi, gj) the level's height. A point first seen at
    level L has to sit on that level's step; coarse ones are put there first,
    and what that moved them by is spread over the finer points round them, so
    a big step leaves a gentle tilt instead of a spike. A point only the levels
    the game does not draw have keeps its own height. No point is left on the
    floor of a leaf (FLOOR3), and so of any cube at all: it goes one step
    towards where it was asked to be.
    Returns {(gi, gj): z3} of the points that end up different."""
    by_level = collections.defaultdict(list)
    for p in targets:
        by_level[grid_level(*p)].append(p)
    done, moved = {}, {}

    def residual(q):
        return done[q] - targets[q] if q in done else 0
    for level in sorted(by_level):
        if level < MIN_LEVEL:
            continue
        s = step3(level)
        d = 1 << (LEAF - level)
        for p in by_level[level]:
            gi, gj = p
            xs = [gi] if gi % (2 * d) == 0 else [gi - d, gi + d]
            ys = [gj] if gj % (2 * d) == 0 else [gj - d, gj + d]
            parents = [(i, j) for i in xs for j in ys if (i, j) != p]
            r = sum(residual(q) for q in parents) / len(parents) if parents else 0
            want = targets[p] + r
            q, rem = divmod(int(round(want)), s)
            z = (q + (1 if 2 * rem >= s else 0)) * s
            if z % FLOOR3 == 0:
                z += s if want > z else -s
            done[p] = z
            if z != own(gi, gj):
                moved[p] = z
    return moved


class _Pyramid:
    """Min and max of scattered grid heights over a square, roughly: a square is
    looked up in whole blocks, so it may take in a little more round it."""

    def __init__(self, pts):
        self.lv = [{p: (z, z) for p, z in pts.items()}]
        while len(self.lv[-1]) > 1 and len(self.lv) < 31:
            nxt = {}
            for (i, j), (lo, hi) in self.lv[-1].items():
                key = (i >> 1, j >> 1)
                got = nxt.get(key)
                nxt[key] = (lo, hi) if got is None else (min(got[0], lo), max(got[1], hi))
            self.lv.append(nxt)

    def span(self, i0, i1, j0, j1):
        k = 0
        while k + 1 < len(self.lv) and (1 << k) < max(i1 - i0, j1 - j0) // 2 + 1:
            k += 1
        blk = self.lv[k]
        lo = hi = None
        for bi in range(i0 >> k, (i1 >> k) + 1):
            for bj in range(j0 >> k, (j1 >> k) + 1):
                got = blk.get((bi, bj))
                if got:
                    lo = got[0] if lo is None else min(lo, got[0])
                    hi = got[1] if hi is None else max(hi, got[1])
        return lo, hi


# ---------------------------------------------------------------- rebuilding part of the tree
class TooManyNodes(ValueError):
    """The rebuilt terrain would not fit the game's node indices."""

    def __init__(self, nodes):
        ValueError.__init__(self, "the terrain would need %d nodes; the game takes %d" % (nodes, NODE_LIMIT))
        self.nodes = nodes


EMPTY_MESH = Mesh([[24, 24, 24, 0, 0]], 1, [[0, 0, 0, 0xF0]])


def _columns_of(level, p):
    """The squares of the cubes at a level (by their low corner, grid units)
    that have the grid point p among their nine."""
    g = 1 << (LEAF - level)                      # between two of the nine
    out = []
    for i0 in {(p[0] // (2 * g)) * 2 * g, ((p[0] - 1) // (2 * g)) * 2 * g}:
        for j0 in {(p[1] // (2 * g)) * 2 * g, ((p[1] - 1) // (2 * g)) * 2 * g}:
            out.append((i0, j0))
    return out


def _folds(tree, changed, heights):
    """(added, found): the grid points to build again along with `changed`, as
    {(gi, gj): z3}, because the ground folds over itself there; and every
    point with two heights among the cubes built again (the added ones and
    those in `changed`), where the level's ground and the new one part ways.

    A cube built again gets one height at each of its nine points. Where the
    level's own ground has two there (one in a cube above the other), the fold
    goes, and a cube beside that is not built again would keep its half of it:
    its side would end in the air, and the sky shows through. So every point
    with two heights among the nine of a cube that is built again is itself
    counted as changed, at the height the rest of the rebuild reads for it:
    then every cube round it is built again too, from the same heights, and
    they meet. That can reach new cubes with folds of their own; it goes on
    until it reaches none."""
    cols = {}                                    # (level, i0, j0) -> {point: {z3}}

    def walk(x0, x1, y0, y1, only=None):
        stack = [(1, (0, 0, 0), 0, 0)]
        while stack:
            ni, c, level, trans = stack.pop()
            h = half(level)
            if c[0] + h <= x0 or c[0] - h >= x1 or c[1] + h <= y0 or c[1] - h >= y1:
                continue
            if level >= MIN_LEVEL and (only is None or level == only):
                g = h // GRID
                key = (level, c[0] // GRID - g, c[1] // GRID - g)
                col = cols.setdefault(key, {})
                bz = 3 * (c[2] - h)
                for x, y, z, fl, sl in oriented(tree.mesh(ni), trans).verts:
                    if x % 24 == 0 and y % 24 == 0:
                        p = (key[1] + (x // 24) * g, key[2] + (y // 24) * g)
                        col.setdefault(p, set()).add(bz + z * step3(level))
            if level < LEAF and (only is None or level < only):
                for octant, child, ct in tree.children(ni, trans):
                    stack.append((child, cube_centre(c, level + 1, octant), level + 1, ct))

    def column(level, i0, j0):
        key = (level, i0, j0)
        if key not in cols:
            g = 1 << (LEAF - level)
            cols[key] = {}
            walk((i0 + 1) * GRID, (i0 + 2 * g - 1) * GRID, (j0 + 1) * GRID, (j0 + 2 * g - 1) * GRID, level)
        return cols[key]
    # every cube over the change in one walk (a cube's square is walked whole,
    # all the way up and down); the few beyond it are walked when asked for
    gis, gjs = [p[0] for p in changed], [p[1] for p in changed]
    walk((min(gis) - 2) * GRID, (max(gis) + 2) * GRID, (min(gjs) - 2) * GRID, (max(gjs) + 2) * GRID)
    added, found, seen = {}, set(), set()
    todo = list(changed)
    while todo:
        q = todo.pop()
        for level in range(max(MIN_LEVEL, grid_level(*q)), LEAF + 1):
            for i0, j0 in _columns_of(level, q):
                if (level, i0, j0) in seen:
                    continue
                seen.add((level, i0, j0))
                for p, zs in column(level, i0, j0).items():
                    if len(zs) < 2:
                        continue
                    found.add(p)
                    if p in changed or p in added:
                        continue
                    z = heights(*p)
                    if z is not None:
                        added[p] = z
                        todo.append(p)
    return added, found


def rebuild(tree, heights, changed, log=print):
    """A new tree: every cube whose square holds a changed grid point is built
    again (all the way down) from the grid - changed points from `changed`, the
    rest from heights(gi, gj), the level's own; every other node is the level's
    own, reached as before. Nodes are added, never edited, and those nothing
    reaches any more are dropped.

    changed: {(gi, gj): z3} of the points that are not the level's own (settle's).
    The report's "folds" are the points where the level's ground folded over
    itself and the new one does not (_folds): the level's heights there say
    nothing about the new ground."""
    if not changed:
        return tree, {"nodes": len(tree.nodes), "new": 0}
    added, folds = _folds(tree, changed, heights)
    if added:
        changed = dict(changed)
        changed.update(added)

    def get(gi, gj):
        z = changed.get((gi, gj))
        return z if z is not None else heights(gi, gj)
    # where the ground can be now: the changed points and the ones round them
    ring = dict(changed)
    for (i, j) in changed:
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                q = (i + di, j + dj)
                if q not in ring:
                    z = heights(*q)
                    if z is not None:
                        ring[q] = z
    live_z = _Pyramid(ring)
    touched = _Pyramid(changed)
    new_nodes = [n[:] for n in tree.nodes]
    new_cmd = bytearray(tree.cmd)
    mesh_at, node_key = {}, {}
    stats = collections.Counter()

    def add_mesh(m):
        b = m.encode()
        off = mesh_at.get(b)
        if off is None:
            off = len(new_cmd)
            new_cmd.extend(b)
            mesh_at[b] = off
        return off

    def add_node(children, off):
        """children: {octant: (index, transform byte)}."""
        ch, tr, mask = [0] * 8, [-1] * 8, 0
        for k, (ni, tb) in children.items():
            ch[k], tr[k], mask = ni, tb, mask | (1 << k)
        key = (tuple(ch), tuple(tr), mask, off)
        got = node_key.get(key)
        if got is not None:
            stats["shared"] += 1
            return got
        new_nodes.append([ch, tr, mask, tree.pad, off])
        node_key[key] = len(new_nodes) - 1
        stats["new"] += 1
        return len(new_nodes) - 1

    def square(level, c):
        h = half(level) // GRID
        ci, cj = c[0] // GRID, c[1] // GRID
        return ci - h, ci + h, cj - h, cj + h

    def touches(level, c):
        i0, i1, j0, j1 = square(level, c)
        if touched.span(i0, i1, j0, j1)[0] is None:
            return False
        if i1 - i0 <= 64:                               # small enough to be exact about
            return any((i, j) in changed for i in range(i0, i1 + 1) for j in range(j0, j1 + 1))
        return True

    def reaches(level, c):
        """Can the ground as it now is pass through this cube?"""
        lo, hi = live_z.span(*square(level, c))
        if lo is None:
            return False
        h3 = 3 * half(level)
        return lo <= 3 * c[2] + h3 and hi >= 3 * c[2] - h3

    def nine(level, c):
        i0, i1, j0, j1 = square(level, c)
        h = (i1 - i0) // 2
        return [(i0 + (gx // 24) * h, j0 + (gy // 24) * h) for gx, gy in GRID9]

    def build(level, c, orig):
        """(node, transform byte) for the cube at centre c, or None. orig: the
        level's own node there and its transform, or None."""
        if not touches(level, c):
            return orig
        if orig is None and not reaches(level, c):
            return None
        stats["cubes"] += 1
        mesh = None
        pts = nine(level, c)
        if level < MIN_LEVEL or not any(p in changed for p in pts):
            if orig is not None:
                mesh = oriented(tree.mesh(orig[0]), orig[1])
        else:
            z9 = [get(*p) for p in pts]
            if all(z is not None for z in z9):
                own_m = oriented(tree.mesh(orig[0]), orig[1]) if orig is not None else None
                keep = {e for e in BORDER if not any(pts[k] in changed for k in e)}
                mesh = cube_mesh(z9, 3 * (c[2] - half(level)), level, own_m, keep)
        children = {}
        if level < LEAF:
            own = {}
            if orig is not None:
                for octant, child, ct in tree.children(orig[0], orig[1]):
                    own[octant] = (child, ct)
            for octant in range(8):
                got = build(level + 1, cube_centre(c, level + 1, octant), own.get(octant))
                if got is not None:
                    children[octant] = got
        if mesh is None and not children:
            return None
        if mesh is None:
            # a cube only its children reach into still has a mesh: one flat
            # triangle of nothing (no cube of the game's own is without one)
            mesh = EMPTY_MESH
            stats["empty"] += 1
        return (add_node(children, add_mesh(mesh)), 0)

    root = build(0, (0, 0, 0), (1, 0))
    if root is None or root[0] == 1:
        return tree, {"nodes": len(tree.nodes), "new": 0}
    out = _compact(tree, new_nodes, new_cmd, root[0])
    report = {"nodes": len(out.nodes), "was": len(tree.nodes), "new": stats["new"], "shared": stats["shared"],
              "cubes": stats["cubes"], "empty": stats["empty"], "cmd": len(out.cmd), "folds": sorted(folds)}
    if len(out.nodes) > NODE_LIMIT:
        raise TooManyNodes(len(out.nodes))
    return out, report


def _compact(tree, nodes, cmd, root):
    """The nodes the new root reaches, renumbered with the root as node 1, and
    only their meshes."""
    order, seen, stack = [], set(), [root]
    while stack:
        ni = stack.pop()
        if ni in seen:
            continue
        seen.add(ni)
        order.append(ni)
        nd = nodes[ni]
        for k in range(8):
            if nd[2] & (1 << k):
                stack.append(nd[0][k])
    order.sort(key=lambda ni: (ni != root, ni))
    num = {ni: i + 1 for i, ni in enumerate(order)}
    out = Tree(b"", b"")
    out.pad = tree.pad
    out.nodes = [[[0] * 8, [0] * 8, 0, bytes(3), 0]]
    cmd_out, moved = bytearray(), {}
    for ni in order:
        ch, tr, mask, pad, off = nodes[ni]
        if off not in moved:
            moved[off] = len(cmd_out)
            cmd_out += cmd[off:off + Mesh.size_at(cmd, off)]
        out.nodes.append([[num[ch[k]] if mask & (1 << k) else ch[k] for k in range(8)], list(tr), mask, pad, moved[off]])
    out.cmd = cmd_out
    return out


# ---------------------------------------------------------------- checking
def seams(tree, gi0, gi1, gj0, gj1, min_level=MIN_LEVEL):
    """Where the cubes inside a box (grid units) do not meet: for every two
    side by side at the same level and height, the points on their shared side
    (place, fixed or sliding, and where a sliding one goes) - with no cube
    beside at all, the side has to have none ("open"); for every two stacked,
    the points on the plane between them. {"sides", "open", "stacked",
    "cubes"}: counts. A rebuilt area should have no more of these than the
    level's own terrain round it."""
    cubes = {}
    stack = [(1, (0, 0, 0), 0, 0)]
    while stack:
        ni, c, level, trans = stack.pop()
        h = half(level)
        hg = h // GRID
        ci, cj = c[0] // GRID, c[1] // GRID
        if ci + hg < gi0 or ci - hg > gi1 or cj + hg < gj0 or cj - hg > gj1:
            continue
        if level >= min_level and gi0 <= ci - hg and ci + hg <= gi1 and gj0 <= cj - hg and cj + hg <= gj1:
            cubes[(level, c[0] // h, c[1] // h, c[2] // h)] = oriented(tree.mesh(ni), trans)
        if level < LEAF:
            for octant, child, ct in tree.children(ni, trans):
                stack.append((child, cube_centre(c, level + 1, octant), level + 1, ct))

    def edge_points(m, test):
        """The vertices at the ends of faces' edges that lie along a side or a
        plane (a face that only touches it at a corner leaves nothing there)."""
        got = set()
        for a, b, c, _ in m.tris:
            for p, q in ((a, b), (b, c), (c, a)):
                if p != q and test(m.verts[p]) and test(m.verts[q]):
                    got.update((p, q))
        return got

    # an edge along a side that is also in the floor or ceiling belongs to the
    # cube beside and the one above or below at once: the ground is continuous
    # through the corner, and it is left out of both comparisons
    def side(m, axis, val):
        out = set()
        for t in m.tris:
            for p, q in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                vp, vq = m.verts[p], m.verts[q]
                if p == q or vp[axis] != val or vq[axis] != val or (vp[2] == vq[2] and vp[2] in (0, 48)):
                    continue
                for i in (p, q):
                    v = m.verts[i]
                    fixed = i < m.nfixed
                    tgt = m.verts[v[4]]
                    out.add((v[1 - axis], v[2], fixed, None if fixed or tgt[axis] != val else (tgt[1 - axis], tgt[2])))
        return out

    def plane(m, z):
        return {(m.verts[i][0], m.verts[i][1], i < m.nfixed)
                for i in edge_points(m, lambda v: v[2] == z and v[0] not in (0, 48) and v[1] not in (0, 48))}

    def inside(level, a, b):
        hg = half(level) // GRID
        return gi0 <= (a - 1) * hg and (a + 1) * hg <= gi1 and gj0 <= (b - 1) * hg and (b + 1) * hg <= gj1
    bad = collections.Counter()
    for (level, a, b, k), m in cubes.items():
        for axis, nb in ((0, (level, a + 2, b, k)), (1, (level, a, b + 2, k))):
            n = cubes.get(nb)
            if n is not None:
                if side(m, axis, 48) != side(n, axis, 0):
                    bad["sides"] += 1
            elif inside(*nb[:3]) and side(m, axis, 48):
                bad["open"] += 1
        for axis, nb in ((0, (level, a - 2, b, k)), (1, (level, a, b - 2, k))):
            if nb not in cubes and inside(*nb[:3]) and side(m, axis, 0):
                bad["open"] += 1
        up = cubes.get((level, a, b, k + 2))
        if up is not None and plane(m, 48) != plane(up, 0):
            bad["stacked"] += 1
    bad["cubes"] = len(cubes)
    return dict(bad)
