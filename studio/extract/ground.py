# What the ground is made of, from the level's own texture masks: grass, dirt,
# rock, snow - for the editor to draw the real ground patterns under the relief.
#
#   python studio/extract/ground.py [--levels 1,3] [--game <the pristine install>]
#       -> editor/data/ground/levelN.json   {materials, tiles: [base64 64x64 grey], mean: [...]}
#       -> editor/data/ground/levelN.bin    zlib: uint8 material per terrain cell (terrain/levelN grid)
#
# What the level files hold (worked out here; the game's own renderer is not ported):
#   terrain/terrain.tex   "LOOP" v9: at +32 the texture count, +40/+44 width and height,
#                         then per texture a 32-byte entry: the offset of its pixels, their
#                         format, and height << 16 | bytes per row. Format 2 is ARGB1555 at
#                         128 x 128, as the game shipped; format 3 is B, G, R, A, as texture
#                         packs replace them (512 x 512). Levels carry 18 or 12 textures: 3
#                         per material.
#   terrain/terrain.bit   256 headers of 12 bytes (saved pointer, 0, size), then each
#                         mask as size*size BITS (size^2 / 8 bytes), least significant
#                         bit first, row by row from the cube's south-west corner.
#   TextureModifier task  (Position, Level, Material Index, Bitmap ID, Size, isEdit): paints
#                         the material over the octree cube of that level holding the
#                         position wherever its mask bit is set; later tasks paint over
#                         earlier ones. Unpainted ground is material 0.
# The mask orientation was checked on level 3: cells its "Rock around base" mask paints
# are 11.8 degrees steeper on average than the rest (no other orientation shows it).
#   terrain/terrain.qvm   CreateTerrainMaterial(material, 1, then 32 entries of
#                         TRUE, 2, 0, 1, set A, 1, set B): the texture SETS a material
#                         is drawn with - set s is textures 3s..3s+2 of terrain.tex. On
#                         level 3 material 0 goes from set 0 through 1 to 2 over its
#                         entries (probably its slope), materials 1-3 use sets 3-5.
# A material's colour is the average of the sets its entries use, each set the
# average of its three textures; its grey tile is the first texture of the set it
# uses most. Which texture of a set the game shows where is not known.
import array, base64, json, math, os, pathlib, re, struct, sys, zlib
from studio import paths
from studio.qvm import source as qvm_source

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = paths.data()
SCALE = 4096.0
TILE = 64
R_MOD = re.compile(r'Task_New\(-?\d+, "TextureModifier", "[^"]*", (-?[\d.]+), (-?[\d.]+), (-?[\d.]+), (\d+), (\d+), (\d+), (\d+)')
R_NAME = re.compile(r'Task_New\(-?\d+, "TextureModifier", "([^"]*)", -?[\d.]+, -?[\d.]+, -?[\d.]+, \d+, (\d+),')
WORDS = ("grass", "dirt", "rock", "snow", "sand", "mud", "field", "concrete", "gravel", "asphalt", "road", "ice", "earth")


def material_names(text, materials):
    """What each material is called, from the level's own TextureModifier names
    ("Grass in base", "Rock around base"): for the Paint tool's palette."""
    seen = {}
    for m in R_NAME.finditer(text):
        low = m.group(1).lower()
        w = next((w for w in WORDS if w in low), None)
        if w:
            seen.setdefault(int(m.group(2)), []).append(w)
    out = []
    for i in range(materials):
        ws = seen.get(i)
        name = max(set(ws), key=ws.count).capitalize() if ws else ("Ground" if i == 0 else "Ground %d" % i)
        out.append({"Field": "Fields"}.get(name, name))
    return out


def read_masks(path):
    b = path.read_bytes()
    heads = [struct.unpack_from("<III", b, i * 12) for i in range(256)]
    items, off = {}, 3072
    for i, h in enumerate(heads):
        if h[2]:
            n = h[2] * h[2] // 8
            items[i] = (h[2], b[off:off + n])
            off += n
    return items


_ARGB1555 = None


def _bgra_rows(b, off, fmt, stride, w, h):
    """One texture's pixels as B, G, R, A, row after row with no padding."""
    global _ARGB1555
    if fmt == 3:
        return b"".join(b[off + y * stride:off + y * stride + w * 4] for y in range(h))
    if fmt == 2:
        if _ARGB1555 is None:
            _ARGB1555 = [bytes(((v & 31) * 255 // 31, (v >> 5 & 31) * 255 // 31, (v >> 10 & 31) * 255 // 31, 255))
                         for v in range(65536)]
        px = array.array("H")
        for y in range(h):
            px.frombytes(b[off + y * stride:off + y * stride + w * 2])
        return b"".join(_ARGB1555[v] for v in px)
    # a format no copy of the game has shown yet: a neutral grey, rather than no ground at all
    return bytes((128, 128, 128, 255)) * (w * h)


def read_textures(path):
    """The level's terrain textures, as B, G, R, A whatever the file keeps them as:
    (pixels, count, width, height, the offset of each texture in pixels)."""
    b = path.read_bytes()
    n, w, h = struct.unpack_from("<I", b, 32)[0], struct.unpack_from("<I", b, 40)[0], struct.unpack_from("<I", b, 44)[0]
    ents = [struct.unpack_from("<3I", b, 52 + 32 * i) for i in range(n)]
    if all(fmt == 3 and (geo & 0xFFFF) in (0, w * 4) for _o, fmt, geo in ents):
        return b, n, w, h, [off for off, _f, _g in ents]
    out, offs = [], []
    at = 0
    for off, fmt, geo in ents:
        rows = _bgra_rows(b, off, fmt, (geo & 0xFFFF) or w * (2 if fmt == 2 else 4), w, h)
        offs.append(at)
        out.append(rows)
        at += len(rows)
    return b"".join(out), n, w, h, offs


def material_sets(tdir, lv):
    """{material: {set: entries}} from the level's terrain script, or {}."""
    q = tdir / "terrain.qvm"
    if not q.exists():
        return {}
    try:
        from studio.qvm import compile as compile_qsc
        import tempfile
        src = compile_qsc.decompile_qvm(q, pathlib.Path(tempfile.mkdtemp(prefix="igi_terr%d_" % lv))).read_text(encoding="latin1")
    except Exception:
        return {}
    out = {}
    for m in re.finditer(r"CreateTerrainMaterial\((\d+),\s*\d+,(.*?)\);", src, re.S):
        use = out.setdefault(int(m.group(1)), {})
        for a, b in re.findall(r"TRUE,\s*\d+,\s*\d+,\s*\d+,\s*(\d+),\s*\d+,\s*(\d+)", m.group(2)):
            for st in (int(a), int(b)):
                use[st] = use.get(st, 0) + 1
    return out


def mean_rgb(b, off, w, h):
    """The texture's average colour, 0..1 (every 8th pixel of every 8th row)."""
    r = g = bl = n = 0
    for y in range(0, h, 8):
        base = off + y * w * 4
        for x in range(0, w * 4, 32):
            bl += b[base + x]
            g += b[base + x + 1]
            r += b[base + x + 2]
            n += 1
    return [round(r / n / 255.0, 4), round(g / n / 255.0, 4), round(bl / n / 255.0, 4)] if n else [0.5, 0.5, 0.5]


def grey_tile(b, off, w, h):
    """The texture shrunk to TILE x TILE shades of grey, row 0 at the top."""
    out = bytearray(TILE * TILE)
    for ty in range(TILE):
        y0 = ty * h // TILE
        y1 = max(y0 + 1, (ty + 1) * h // TILE)
        for tx in range(TILE):
            x0 = tx * w // TILE
            x1 = max(x0 + 1, (tx + 1) * w // TILE)
            s = 0
            for yy in range(y0, y1):
                base = off + yy * w * 4
                for xx in range(x0 * 4, x1 * 4, 4):
                    s += 0.114 * b[base + xx] + 0.587 * b[base + xx + 1] + 0.299 * b[base + xx + 2]
            out[ty * TILE + tx] = int(s / ((x1 - x0) * (y1 - y0)))
    return bytes(out)


def build(lv, game):
    meta_p = DATA / "terrain" / ("level%d.json" % lv)
    tdir = pathlib.Path(game) / "missions" / "location0" / ("level%d" % lv) / "terrain"
    if not (meta_p.exists() and (tdir / "terrain.bit").exists() and (tdir / "terrain.tex").exists()):
        return None
    qsc = qvm_source.level_qsc(lv, game)
    meta = json.load(meta_p.open())
    w, h, cell, x0, y0 = meta["w"], meta["h"], meta["cell"], meta["x0"], meta["y0"]
    masks = read_masks(tdir / "terrain.bit")
    qtext = qsc.read_text(encoding="latin1")
    mods = [tuple(float(v) for v in m.groups()[:3]) + tuple(int(v) for v in m.groups()[3:])
            for m in R_MOD.finditer(qtext)]
    grid = bytearray(w * h)
    used = {0}
    for x, y, _z, lod, mat, bid, size in mods:
        if bid not in masks:
            continue
        S, bits = masks[bid]
        cube = 1 << (31 - lod)
        mnx, mny = math.floor(x / cube) * cube / SCALE, math.floor(y / cube) * cube / SCALE
        px = cube / SCALE / S
        fill = bytes([mat & 255])
        used.add(mat)
        for jj in range(S):
            wy0 = mny + jj * px
            j0 = max(0, math.ceil((wy0 - y0) / cell))
            j1 = min(h - 1, math.ceil((wy0 + px - y0) / cell) - 1)
            if j0 > j1:
                continue
            for ii in range(S):
                k = jj * S + ii
                if not (bits[k >> 3] >> (k & 7)) & 1:
                    continue
                wx0 = mnx + ii * px
                i0 = max(0, math.ceil((wx0 - x0) / cell))
                i1 = min(w - 1, math.ceil((wx0 + px - x0) / cell) - 1)
                if i0 > i1:
                    continue
                for j in range(j0, j1 + 1):
                    grid[j * w + i0:j * w + i1 + 1] = fill * (i1 - i0 + 1)
    b, n, tw, th, offs = read_textures(tdir / "terrain.tex")
    materials = max(n // 3, max(used) + 1)
    sets = material_sets(tdir, lv)
    set_rgb = {}

    def rgb_of_set(st):
        if st not in set_rgb:
            cs = [mean_rgb(b, offs[q], tw, th) for q in range(st * 3, min(st * 3 + 3, n))]
            set_rgb[st] = [sum(c[i] for c in cs) / len(cs) for i in range(3)] if cs else None
        return set_rgb[st]
    tiles, means, rgbs = [], [], []
    EARTH = [0.37, 0.33, 0.22]      # a set the file does not have (level 3 names sets 6 and 7 with 18 textures)
    for m in range(materials):
        use = {st: k for st, k in (sets.get(m) or {m: 1}).items() if st * 3 < n}
        if not use:
            # its mask texture's shade, in a neutral earth colour
            t = min(m * 3, n - 1)
            g = grey_tile(b, offs[t], tw, th)
            tiles.append(base64.b64encode(g).decode())
            means.append(round(sum(g) / len(g) / 255.0, 4))
            rgbs.append(EARTH)
            continue
        top = max(use, key=lambda st: use[st])
        g = grey_tile(b, offs[top * 3], tw, th)
        tiles.append(base64.b64encode(g).decode())
        means.append(round(sum(g) / len(g) / 255.0, 4))
        tot = sum(use.values())
        cols = [(rgb_of_set(st), k) for st, k in use.items() if rgb_of_set(st)]
        rgbs.append([round(sum(c[i] * k for c, k in cols) / tot, 4) for i in range(3)])
    out = DATA / "ground"
    out.mkdir(parents=True, exist_ok=True)
    (out / ("level%d.bin" % lv)).write_bytes(zlib.compress(bytes(grid), 9))
    counts = [grid.count(m) for m in range(materials)]
    (out / ("level%d.json" % lv)).write_text(json.dumps({
        "level": lv, "w": w, "h": h, "materials": materials, "tile": TILE, "tiles": tiles, "mean": means,
        "rgb": rgbs, "names": material_names(qtext, materials),
        "cells": counts, "modifiers": len(mods)}))
    return {"modifiers": len(mods), "materials": materials,
            "share": ["%d:%.0f%%" % (m, 100.0 * c / len(grid)) for m, c in enumerate(counts) if c]}


def main(argv):
    levels = [int(x) for x in argv[argv.index("--levels") + 1].split(",")] if "--levels" in argv else list(range(1, 15))
    game = argv[argv.index("--game") + 1] if "--game" in argv else str(paths.pristine())
    for lv in levels:
        r = build(lv, game)
        print("level %2d: %s" % (lv, r if r else "no terrain or no texture masks"))


if __name__ == "__main__":
    main(sys.argv[1:])
