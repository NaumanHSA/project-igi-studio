# Textured models for the editor's 3D close-up: a model's
# render mesh with its uvs and the texture each group is drawn with, and the
# textures themselves as PNG. studio/server/app.py serves them (api/model3d,
# api/texture); the close-up falls back to plain shading without them.
#
# What the game files say (worked out 2026-09-18):
#   - A level's <level>.dat is machine-written text: after the header, the model
#     count, then per model its name, a count k and k texture names. Render
#     group i of the model's DNER chunk (group header field 8) is drawn with
#     texture i of that list - 8 groups and 8 textures for the barracks, 3 and 3
#     for the oilskin crate, 9 and 9 for a guard. The location's shared models
#     have their lists in missions/location0/common/location0.dat.
#   - Every XTRV vertex has its uv at byte 24 (after position and normal),
#     whatever the stride.
#   - A texture is "LOOP" version 11: width, height at +22/+24 (u16), bytes per
#     pixel at +30 (2: ARGB1555; 4, "_argb8888": B, G, R, A), pixels from +32,
#     row 0 first. The oilskin crate's tarp decodes as the green cloth the game
#     shows only as ARGB1555.
#
# Archives are indexed once (the offset of every model and texture, not their
# bytes: the textures alone are 2.9 GB over the fourteen levels); decoded
# textures are cached as PNG under cache/tex.
import array, base64, json, math, pathlib, struct, sys, threading, zlib

from studio.extract import meshes as BM
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = paths.cache() / "tex"
SCALE = 4096.0


def _scan(path):
    """{name: (offset, length)} of each BODY in an ILFF resource archive,
    walking the chunk headers only."""
    out = {}
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        off, cur = 20, None
        while off + 16 <= size:
            f.seek(off)
            hdr = f.read(16)
            tag = hdr[:4]
            ln, al, _ = struct.unpack_from("<III", hdr, 4)
            if al == 0:
                break
            if tag == b"NAME":
                cur = f.read(ln).split(b"\0")[0].decode("latin1").split("/")[-1]
            elif tag == b"BODY" and cur:
                out.setdefault(cur, (off + 16, ln))
            off += 16 + ((ln + al - 1) // al) * al
    return out


def _dat_lists(path):
    """{model: [texture, ...]} from a level's .dat."""
    out = {}
    try:
        lines = path.read_text(encoding="latin1").split("\n")
    except OSError:
        return out
    lines = [l.strip() for l in lines]
    try:
        i = next(k for k, l in enumerate(lines) if l.isdigit())
    except StopIteration:
        return out
    n, i = int(lines[i]), i + 1
    while i + 1 < len(lines) and len(out) < n:
        name, k = lines[i], lines[i + 1]
        if not k.isdigit():
            break
        k = int(k)
        out[name] = lines[i + 2:i + 2 + k]
        i += 2 + k
    return out


def _png(w, h, rgba):
    raw = b"".join(b"\0" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


class Library:
    def __init__(self, game):
        self.game = pathlib.Path(game)
        self.lock = threading.Lock()
        self._index = None

    # ------------------------------------------------------------ the archives
    def _level_dir(self, lv):
        return self.game / "missions" / "location0" / ("level%d" % lv)

    def index(self):
        with self.lock:
            if self._index is not None:
                return self._index
            common = self.game / "missions" / "location0" / "common"
            models, tex, lists = {}, {}, {}
            # per level first, then the location's shared archives
            for lv in list(range(1, 15)) + [None]:
                if lv is None:
                    mres, tres, dat = common / "models" / "location0.res", common / "textures" / "location0.res", \
                        common / "location0.dat"
                else:
                    d = self._level_dir(lv)
                    mres, tres, dat = d / "models" / ("level%d.res" % lv), d / "textures" / ("level%d.res" % lv), \
                        d / ("level%d.dat" % lv)
                key = lv or 0
                if mres.exists():
                    for name, (o, n) in _scan(mres).items():
                        models.setdefault(name, {})[key] = (mres, o, n)
                if tres.exists():
                    for name, (o, n) in _scan(tres).items():
                        tex.setdefault(name, {})[key] = (tres, o, n)
                for m, l in _dat_lists(dat).items():
                    lists.setdefault(m, {})[key] = l
            self._index = {"models": models, "tex": tex, "lists": lists}
            return self._index

    @staticmethod
    def _pick(by_level, lv):
        """The copy in this level's archive, else the shared one, else any."""
        if not by_level:
            return None
        for k in (lv, 0):
            if k in by_level:
                return by_level[k]
        return next(iter(by_level.values()))

    def _read(self, loc):
        path, off, n = loc
        with open(path, "rb") as f:
            f.seek(off)
            return f.read(n)

    def mef(self, name, lv):
        loc = self._pick(self.index()["models"].get(name + ".mef"), lv)
        return self._read(loc) if loc else None

    def textures_of(self, name, lv):
        return self._pick(self.index()["lists"].get(name), lv) or []

    # ------------------------------------------------------------ meshes
    def _groups(self, mef, bones=None):
        """(positions, uvs, [(texture index, [(a, b, c), ...])]) of one model's own
        render mesh; skinned onto bones when given. None without one."""
        ch = {}
        for tag, pay in BM.ilff(mef, 20):
            ch.setdefault(tag, []).append(pay)
        if b"D3DR" not in ch or b"XTRV" not in ch or b"DNER" not in ch:
            return None
        dd = ch[b"D3DR"][0]
        d = struct.unpack_from("<%di" % (len(dd) // 4), dd)
        xt = ch[b"XTRV"][0]
        if len(dd) == 56 and d[1] == 1:
            nv, hdr, at_vs, at_vc = d[4], 16, 10, 11
        elif len(dd) == 56:
            nv, hdr, at_vs, at_vc = d[5], 14, 9, 10          # characters
        elif len(dd) == 48:
            nv, hdr, at_vs, at_vc = d[3], 14, 9, 10
        else:
            return None
        if nv <= 0 or len(xt) % nv:
            return None
        st = len(xt) // nv
        pos, uv = [], []
        for i in range(nv):
            x, y, z = struct.unpack_from("<3f", xt, i * st)
            u, v = struct.unpack_from("<2f", xt, i * st + 24)
            if bones is not None:
                b = struct.unpack_from("<H", xt, i * st + st - 2)[0]
                if b >= len(bones):
                    return None
                pos.append(BM.place_on_bone(bones[b], x, y, z))
            else:
                pos.append((x / SCALE, y / SCALE, z / SCALE))
            uv.append((u, v))
        n = ch[b"DNER"][0]
        u16 = struct.unpack_from("<%dH" % (len(n) // 2), n)
        groups, p = [], 0
        while p + hdr <= len(u16):
            cnt, vs, vc, ti = u16[p + 6], u16[p + at_vs], u16[p + at_vc], u16[p + 8]
            idx = u16[p + hdr:p + hdr + cnt]
            if cnt % 3 or vs + vc > nv or (idx and max(idx) >= vc):
                return None
            groups.append((ti, [(vs + idx[k], vs + idx[k + 1], vs + idx[k + 2]) for k in range(0, cnt, 3)]))
            p += hdr + cnt
        if p != len(u16):
            return None
        if bones is not None:
            z0 = min(q[2] for q in pos)
            pos = [(x, y, z - z0) for x, y, z in pos]
        return pos, uv, groups

    def _assemble(self, name, lv, depth=0, seen=()):
        """[(positions, uvs, [(texture name, triangles)])] of a model and the parts
        it is built from (ATTA), each part in the model's own space."""
        mef = self.mef(name, lv)
        if mef is None or name in seen or depth > 4:
            return []
        out = []
        kind = BM.small_kind(name)
        bones = None
        if kind == "character":
            sk = self.game / "common" / "anims" / (BM.SKELETON_OF.get(name[:3], "001") + ".iff")
            try:
                bones = BM.posed(sk) or BM.skeleton(sk)      # at ease, as the map and previews show them
            except (OSError, KeyError, struct.error):
                return []
        mesh = self._groups(mef, bones)
        if mesh:
            texs = self.textures_of(name, lv)
            pos, uv, groups = mesh
            out.append((pos, uv, [(texs[ti] if ti < len(texs) else None, tris) for ti, tris in groups]))
        for part, (tx, ty, tz), m in BM.attachments(mef):
            if BM.is_effect(part):
                continue                # a muzzle flash, seen only while firing
            for pos, uv, groups in self._assemble(part, lv, depth + 1, seen + (name,)):
                pos = [(m[0] * x + m[3] * y + m[6] * z + tx, m[1] * x + m[4] * y + m[7] * z + ty,
                        m[2] * x + m[5] * y + m[8] * z + tz) for x, y, z in pos]
                out.append((pos, uv, groups))
        return out

    def model(self, name, lv):
        """What the close-up draws: positions, uvs and indices (base64 little-endian
        float32 / float32 / uint32) and [first index, index count, texture] groups."""
        parts = self._assemble(name, lv)
        if not parts:
            return None
        P, U, I, G = array.array("f"), array.array("f"), array.array("I"), []
        by_tex = {}
        base = 0
        for pos, uv, groups in parts:
            for x, y, z in pos:
                P.extend((x, y, z))
            for u, v in uv:
                U.extend((u, v))
            for tex, tris in groups:
                by_tex.setdefault(tex, []).extend((base + a, base + b, base + c) for a, b, c in tris)
            base += len(pos)
        for tex, tris in by_tex.items():
            # whether its texture has see-through pixels (fences, foliage, grilles)
            t = self.texture(tex, lv) if tex else None
            G.append([len(I), len(tris) * 3, tex if t else None, bool(t and t[1])])
            for t in tris:
                I.extend(t)
        if sys.byteorder != "little":
            for a in (P, U, I):
                a.byteswap()
        return {"name": name, "verts": base, "groups": G,
                "pos": base64.b64encode(P.tobytes()).decode(), "uv": base64.b64encode(U.tobytes()).decode(),
                "idx": base64.b64encode(I.tobytes()).decode()}

    # ------------------------------------------------------------ textures
    def texture(self, name, lv, size=512):
        """(PNG bytes, has transparent pixels) of a texture, at most size px on
        its longer side, or None."""
        size = max(16, min(2048, int(size)))
        CACHE.mkdir(parents=True, exist_ok=True)
        key = "%s_%d" % (name.replace("/", "_"), size)
        f, meta = CACHE / (key + ".png"), CACHE / (key + ".json")
        if f.exists() and meta.exists():
            return f.read_bytes(), json.loads(meta.read_text()).get("alpha", False)
        idx = self.index()["tex"]
        loc = self._pick(idx.get(name + ".tex"), lv)
        if loc is None:
            # "_argb8888" and similar: the list names the stem
            cand = [k for k in idx if k.startswith(name + "_") and k.endswith(".tex")]
            loc = self._pick(idx.get(cand[0]), lv) if cand else None
        if loc is None:
            return None
        b = self._read(loc)
        if len(b) < 32 or b[:4] != b"LOOP":
            return None
        w, h = struct.unpack_from("<2H", b, 22)
        bpp = struct.unpack_from("<H", b, 30)[0]
        if bpp not in (2, 4) or not w or not h or len(b) < 32 + w * h * bpp:
            return None
        step = 1
        while max(w, h) // step > size:
            step *= 2
        W, H = max(1, w // step), max(1, h // step)
        out = bytearray(W * H * 4)
        clear = solid = 0
        if bpp == 2:
            px = array.array("H")
            px.frombytes(b[32:32 + w * h * 2])
            if sys.byteorder != "little":
                px.byteswap()
            o = 0
            for y in range(H):
                row = y * step * w
                for x in range(W):
                    v = px[row + x * step]
                    out[o] = ((v >> 10) & 31) * 255 // 31
                    out[o + 1] = ((v >> 5) & 31) * 255 // 31
                    out[o + 2] = (v & 31) * 255 // 31
                    if v & 0x8000:
                        out[o + 3] = 255
                        solid += 1
                    else:
                        clear += 1
                    o += 4
            if not solid:                     # no alpha bits at all: an opaque texture
                for i in range(3, len(out), 4):
                    out[i] = 255
                clear = 0
        else:
            o = 0
            for y in range(H):
                row = 32 + y * step * w * 4
                for x in range(W):
                    q = row + x * step * 4
                    out[o], out[o + 1], out[o + 2], out[o + 3] = b[q + 2], b[q + 1], b[q], b[q + 3]
                    if b[q + 3] < 128:
                        clear += 1
                    o += 4
        alpha = clear > 0
        png = _png(W, H, out)
        f.write_bytes(png)
        meta.write_text(json.dumps({"w": w, "h": h, "alpha": alpha}))
        return png, alpha


_LIB = {}


def library(game):
    game = str(game)
    if game not in _LIB:
        _LIB[game] = Library(game)
    return _LIB[game]


if __name__ == "__main__":
    import time
    lib = library(sys.argv[1] if len(sys.argv) > 1 else str(paths.pristine()))
    t = time.time()
    ix = lib.index()
    print("indexed %d models, %d textures, %d lists in %.1f s" % (len(ix["models"]), len(ix["tex"]), len(ix["lists"]),
                                                                  time.time() - t))
    for name in sys.argv[2:] or ["418_01_1", "342_01_1", "003_01_1", "105_01_1"]:
        t = time.time()
        m = lib.model(name, 3)
        print(name, m and (m["verts"], [(g[1], g[2]) for g in m["groups"]]), "%.2f s" % (time.time() - t))
        for g in (m or {}).get("groups", []):
            if g[2]:
                t = time.time()
                r = lib.texture(g[2], 3)
                print("   ", g[2], r and (len(r[0]), r[1]), "%.2f s" % (time.time() - t))
