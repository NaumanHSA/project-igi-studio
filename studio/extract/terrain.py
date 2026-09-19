# The real terrain of every level, as a height grid the editor can draw and query.
#
#   python studio/extract/terrain.py [--levels 1,3] [--cell 2] [--game <game>]
#       -> editor/data/terrain/levelN.json   grid: x0, y0, cell, w, h, zmin, step
#       -> editor/data/terrain/levelN.bin    w*h little-endian uint16, zlib-deflated
#
# Heights come from studio/build/terrain.py - the game's own octree meshes and
# HeightMap overlays, exact to the millimetre where they were checked against
# navmesh nodes. Each sample is stored in centimetres above the level's lowest
# point (65535 = no terrain there). The grid covers where the level's objects,
# guards and navmesh are, plus a margin, not the whole horizon.
import json, math, multiprocessing, os, pathlib, struct, sys, time, zlib

from studio.build import terrain as T
from studio import paths
from studio.qvm import source as qvm_source

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = paths.data()
MARGIN = 150.0
NODATA = 65535


MAX_SPAN = 2000.0    # metres: no level is played over more than this


def extent(lv):
    """Where the level is played: its buildings, guards, pickups, player and
    navmesh, trimmed of stragglers (a helicopter's flight path kilometres out)
    and never more than MAX_SPAN across, centred on the middle of it all."""
    L = json.load((DATA / ("level%d.json" % lv)).open())
    xs, ys = [], []
    for o in L["objects"]:
        if not o.get("cutscene") and o["type"] in ("building", "soldier", "player", "pickup", "door", "terminal"):
            xs.append(o["x"])
            ys.append(o["y"])
    gp = DATA / ("graphs%d.json" % lv)
    if gp.exists():
        for g in json.load(gp.open()).values():
            for n in g.get("nodes", []):
                xs.append(n["x"])
                ys.append(n["y"])
    xs.sort()
    ys.sort()
    cut = len(xs) * 2 // 100        # two percent at each end
    x0, x1, y0, y1 = xs[cut] - MARGIN, xs[-1 - cut] + MARGIN, ys[cut] - MARGIN, ys[-1 - cut] + MARGIN
    # ...but every building, guard and the player start, untrimmed: the start
    # is often at the edge of the action
    for o in L["objects"]:
        if not o.get("cutscene") and o["type"] in ("building", "soldier", "player"):
            x0, x1 = min(x0, o["x"] - MARGIN), max(x1, o["x"] + MARGIN)
            y0, y1 = min(y0, o["y"] - MARGIN), max(y1, o["y"] + MARGIN)
    mx, my = xs[len(xs) // 2], ys[len(ys) // 2]
    half = MAX_SPAN / 2
    return max(x0, mx - half), min(x1, mx + half), max(y0, my - half), min(y1, my + half)


def sample(args):
    lv, game, cell = args
    t0 = time.time()
    tr = T.Terrain(pathlib.Path(game) / "missions" / "location0" / ("level%d" % lv), qvm_source.level_qsc(lv, game))
    x0, x1, y0, y1 = extent(lv)
    w, h = int(math.ceil((x1 - x0) / cell)) + 1, int(math.ceil((y1 - y0) / cell)) + 1
    zs = []
    for j in range(h):
        y = y0 + j * cell
        for i in range(w):
            zs.append(tr.z(x0 + i * cell, y))
    good = [z for z in zs if z is not None]
    if not good:
        return lv, None
    zmin, zmax = min(good), max(good)
    step = max(0.01, (zmax - zmin) / 65000.0)     # centimetres unless the range is huge
    q = bytearray(w * h * 2)
    for k, z in enumerate(zs):
        struct.pack_into("<H", q, 2 * k, NODATA if z is None else int(round((z - zmin) / step)))
    out = DATA / "terrain"
    out.mkdir(parents=True, exist_ok=True)
    (out / ("level%d.bin" % lv)).write_bytes(zlib.compress(bytes(q), 9))
    meta = {"level": lv, "x0": round(x0, 3), "y0": round(y0, 3), "cell": cell, "w": w, "h": h,
            "zmin": round(zmin, 3), "zmax": round(zmax, 3), "step": step, "nodata": NODATA,
            "holes": len(zs) - len(good)}
    (out / ("level%d.json" % lv)).write_text(json.dumps(meta))
    return lv, dict(meta, seconds=round(time.time() - t0, 1),
                    kb=round((out / ("level%d.bin" % lv)).stat().st_size / 1024))


def main(argv):
    levels = [int(x) for x in argv[argv.index("--levels") + 1].split(",")] if "--levels" in argv else list(range(1, 15))
    cell = float(argv[argv.index("--cell") + 1]) if "--cell" in argv else 2.0
    game = argv[argv.index("--game") + 1] if "--game" in argv else str(paths.require_game())
    with multiprocessing.Pool(min(len(levels), os.cpu_count() or 2)) as pool:
        for lv, meta in pool.imap_unordered(sample, [(lv, game, cell) for lv in levels]):
            if meta is None:
                print("level %2d: no terrain" % lv)
            else:
                print("level %2d: %4d x %4d cells of %.0f m, height %.1f .. %.1f, %d holes, %d KB, %.0fs" % (
                    lv, meta["w"], meta["h"], cell, meta["zmin"], meta["zmax"], meta["holes"], meta["kb"], meta["seconds"]))


if __name__ == "__main__":
    main(sys.argv[1:])
