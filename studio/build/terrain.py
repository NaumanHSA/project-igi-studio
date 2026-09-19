# Exact ground height from a level's terrain files.
#
#   python studio/build/terrain.py --level 15 --at 5985,-13640 [--game <game>]
#
#   from terrain import Terrain
#   t = Terrain(game / "missions" / "location0" / "level15", objects_qsc_path)
#   t.z(5985.0, -13640.0)      -> ground height in game units, or None
#
# Ported from project-igi-editor (source/level/terrain_query.cpp, terrain_io.cpp).
# The terrain is an octree of cubes whose root spans +-2^30 raw units:
#   terrain.ctr   32-byte nodes: 8 child indices (i16), 8 child transforms (i8),
#                 a child mask (u8), 3 pad, u32 offset of the node's mesh in .cmd.
#                 Node 0 is unused; node 1 is the root.
#   terrain.cmd   meshes: u16 triangles, u16 vertex offset, u16 parent vertices,
#                 u16 child vertices, then u32 packed triangles and u32 packed
#                 vertices (6 bits each for x, y, z around the cube centre).
#   terrain.hmp   256 item headers (12 bytes, size at +8), then each heightmap as
#                 (size+1)^2 bytes. A "HeightMap" task in objects.qsc lays one
#                 over the octree cube of its lod level that holds its position,
#                 raising or lowering the leaf meshes by (value - 64) * 256.
# Leaf meshes live at level 16 (cubes 8 m wide). Each child can be rotated or
# mirrored; the transform tables below compose those down the tree.
import math, pathlib, re, struct, sys
from studio import paths
from studio.qvm import source as qvm_source

SCALE = 4096.0
ROOT_HALF = 1 << 30
LEAF_LEVEL = 16

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
DIM_TABLE = [(x * ROOT_HALF, y * ROOT_HALF, z * ROOT_HALF)
             for z in (-1, 1) for y in (-1, 1) for x in (-1, 1)]
R_HMP = re.compile(r'Task_New\(-?\d+, "HeightMap", "[^"]*", (-?[\d.eE+-]+), (-?[\d.eE+-]+), (-?[\d.eE+-]+), '
                   r'(\d+), (\d+), (?:TRUE|FALSE), (\d+)')


class Terrain:
    def __init__(self, level_dir, objects_qsc=None):
        d = pathlib.Path(level_dir) / "terrain"
        self.cmd = open(d / "terrain.cmd", "rb").read()
        ctr = open(d / "terrain.ctr", "rb").read()
        self.nodes = [struct.unpack_from("<8h8bB3xI", ctr, i) for i in range(0, len(ctr) - 31, 32)]
        self.hmaps = []
        hp = d / "terrain.hmp"
        if hp.exists() and objects_qsc:
            self._load_heightmaps(open(hp, "rb").read(), pathlib.Path(objects_qsc).read_text(encoding="latin1"))
        self._mesh_cache = {}

    # ------------------------------------------------------------ heightmaps
    def _load_heightmaps(self, b, qsc):
        items, off = {}, 256 * 12
        for i in range(256):
            size = struct.unpack_from("<I", b, i * 12 + 8)[0]
            if size:
                n = (size + 1) ** 2
                items[i] = (size, b[off:off + n])
                off += n
        for m in R_HMP.finditer(qsc):
            x, y, _, lod, size, bid = m.groups()
            lod, size, bid = int(lod), int(size), int(bid)
            if bid not in items:
                continue
            real_size, data = items[bid]
            cube = 1 << (31 - lod)                        # full width of a lod-level cube
            half_shift = 30 - lod
            hmp_half_shift = size.bit_length() - 2        # get_highest_bit(size) - 1
            self.hmaps.append({
                "id": bid, "size": real_size, "lod": lod,
                "min_x": math.floor(float(x) / cube) * cube,
                "min_y": math.floor(float(y) / cube) * cube,
                "cube": cube, "shift": size.bit_length() - 1,
                "scale": 1.0 / (1 << (half_shift - hmp_half_shift)),
                "data": data,
            })

    def _hmp_for(self, x, y):
        hit = None
        for h in self.hmaps:
            if h["min_x"] <= x < h["min_x"] + h["cube"] and h["min_y"] <= y < h["min_y"] + h["cube"]:
                hit = h            # the last one pushed is the one used
        return hit

    @staticmethod
    def _hmp_delta(h, vx, vy):
        xf = (vx - h["min_x"]) * h["scale"]
        yf = (vy - h["min_y"]) * h["scale"]
        ix, iy = int(xf), int(yf)
        fx, fy = xf - ix, yf - iy
        dim = 1 << h["shift"]
        row = dim + 1
        iy0 = iy * row
        iy1 = iy0 if iy >= dim else (iy + 1) * row
        ix1 = ix if ix >= dim else ix + 1
        data = h["data"]

        def at(i):
            return data[i] if 0 <= i < len(data) else 64
        h0, h1, h2, h3 = at(iy0 + ix), at(iy0 + ix1), at(iy1 + ix), at(iy1 + ix1)
        a = (h1 - h0) * fx + h0
        c = (h3 - h2) * fx + h2
        return ((c - a) * fy + a - 64.0) * 256.0

    # ------------------------------------------------------------ query
    def z_raw(self, x, y):
        """Ground height in raw units at raw (x, y), or None where there is no terrain."""
        # a point exactly on a shared triangle edge is inside neither triangle
        # (the test is strict, as in the game); nudge it a fraction of a millimetre
        for jx, jy in ((0.0, 0.0), (0.37, 0.21), (-0.29, 0.43), (0.19, -0.41)):
            r = self._walk(1, (0, 0, 0), 0, ROOT_HALF, 0, float(x) + jx, float(y) + jy, self._hmp_for(x, y))
            if r is not None:
                return r
        return None

    def z_raw_base(self, x, y):
        """Like z_raw, without any height map: the terrain as its meshes store it."""
        for jx, jy in ((0.0, 0.0), (0.37, 0.21), (-0.29, 0.43), (0.19, -0.41)):
            r = self._walk(1, (0, 0, 0), 0, ROOT_HALF, 0, float(x) + jx, float(y) + jy, None)
            if r is not None:
                return r
        return None

    def z(self, gx, gy):
        r = self.z_raw(gx * SCALE, gy * SCALE)
        return None if r is None else r / SCALE

    def _walk(self, ni, pos, level, dim, trans, x, y, hmp):
        node = self.nodes[ni]
        if level == LEAF_LEVEL:
            return self._leaf(node[17], pos, level, trans, x, y, hmp)
        mask = node[16]
        if not mask:
            return None
        order = CUBE_IDX_TABLE[trans * 8:trans * 8 + 8]
        tlines = CUBE_TRANS_TABLE[trans * 8:trans * 8 + 8]
        sub = level + 1
        sdim = dim >> 1
        for access in CHILD_ACCESS_ORDER:
            child = order[access]
            if not mask & (1 << child):
                continue
            dx, dy, dz = DIM_TABLE[access]
            sp = (pos[0] + (dx >> sub), pos[1] + (dy >> sub), pos[2] + (dz >> sub))
            if sp[0] - sdim <= x <= sp[0] + sdim and sp[1] - sdim <= y <= sp[1] + sdim:
                r = self._walk(node[child], sp, sub, sdim, tlines[node[8 + child]], x, y, hmp)
                if r is not None:
                    return r
        return None

    def _leaf(self, off, pos, level, trans, x, y, hmp):
        ntri, _, npar, nchild = struct.unpack_from("<4H", self.cmd, off)
        tris = struct.unpack_from("<%dI" % ntri, self.cmd, off + 8)
        verts = struct.unpack_from("<%dI" % (npar + nchild), self.cmd, off + 8 + 4 * ntri)
        scale = float(1 << (27 - level)) / 3.0
        vb = []
        for v in verts:
            sx, sy, sz = (v >> 26) & 0x3F, (v >> 20) & 0x3F, (v >> 14) & 0x3F
            vx, vy, vz = sx - 24, sy - 24, sz - 24
            if trans & 4:
                vx = 24 - sx
            if trans & 1:
                if trans & 2:
                    vx = -vx
                else:
                    vy = 24 - sy
                vx, vy = vy, vx
            elif trans & 2:
                vx = -vx
                vy = 24 - sy
            px = vx * scale + pos[0]
            py = vy * scale + pos[1]
            pz = vz * scale + pos[2]
            if hmp is not None:
                pz += self._hmp_delta(hmp, px, py)
            vb.append((px, py, pz))
        for t in tris:
            if trans & 4:
                ids = ((t >> 8) & 0xFF, t & 0xFF, (t >> 16) & 0xFF)
            else:
                ids = ((t >> 16) & 0xFF, t & 0xFF, (t >> 8) & 0xFF)
            if max(ids) >= len(vb):
                continue
            inside = True
            for k in range(3):
                a, c = vb[ids[k]], vb[ids[(k + 1) % 3]]
                if (c[0] - a[0]) * (y - a[1]) - (c[1] - a[1]) * (x - a[0]) <= 0.0:
                    inside = False
                    break
            if inside:
                a, b1, c = vb[ids[0]], vb[ids[1]], vb[ids[2]]
                ux, uy, uz = b1[0] - a[0], b1[1] - a[1], b1[2] - a[2]
                wx, wy, wz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
                nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
                if nz == 0:
                    continue
                d = -(nx * c[0] + ny * c[1] + nz * c[2])
                return -(nx * x + ny * y + d) / nz
        return None


if __name__ == "__main__":
    argv = sys.argv

    def arg(n, dflt=None):
        return argv[argv.index(n) + 1] if n in argv else dflt

    game = pathlib.Path(arg("--game") or paths.require_game())
    lv = arg("--level", "1")
    root = pathlib.Path(__file__).resolve().parents[2]
    qsc = qvm_source.level_qsc(int(lv), game)
    t = Terrain(game / "missions" / "location0" / ("level%s" % lv), qsc)
    x, y = (float(v) for v in arg("--at", "0,0").split(","))
    print(t.z(x, y))
