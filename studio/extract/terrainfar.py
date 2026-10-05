# The ground everywhere a level's cutscenes go, for playing them in the 3D view.
#
#   from studio.extract import terrainfar
#   terrainfar.grid(level) -> {x0, y0, cell, w, h, zmin, step, nodata, z: base64 uint16}
#
# The editor's own ground (studio/extract/terrain.py) covers where a mission is
# played: level 1's is 460 x 464 m round the yard. Its intro starts about a
# kilometre out, a helicopter over the hills, and its railway runs off the
# grid: played there, the sky showed under the helicopter and trees floated.
# This is a coarser grid of the game's own terrain (studio/build/terrain.py,
# about 15 000 points a second) over all of it: the play area, every camera,
# vehicle and track of the level's cutscenes, and a margin, at most MAX_SPAN
# across. Read once per level and kept in the level data (terrain/levelN.far.json).
import base64, json, math, struct

from studio import paths
from studio.build.terrain import Terrain
from studio.qvm import source as qvm_source

MARGIN = 300.0          # metres round everything the cutscenes show
MAX_SPAN = 6000.0       # metres: no cutscene goes further
MAX_POINTS = 180000     # the grid is coarser over a wider area
STEP = 0.05             # metres a unit
NODATA = 65535
VERSION = 1


def _extent(lv):
    D = paths.data()
    xs, ys = [], []
    fine = D / "terrain" / ("level%d.json" % lv)
    if fine.exists():
        f = json.load(fine.open())
        xs += [f["x0"], f["x0"] + (f["w"] - 1) * f["cell"]]
        ys += [f["y0"], f["y0"] + (f["h"] - 1) * f["cell"]]
    L = json.load((D / ("level%d.json" % lv)).open())
    m = L.get("motion") or {}
    for c in m.get("cutscenes") or []:
        for sc in c.get("scenes") or []:
            for s in sc.get("shots") or []:
                xs.append(s["x"])
                ys.append(s["y"])
    for v in m.get("vehicles") or []:
        if v.get("x") is not None:
            xs.append(v["x"])
            ys.append(v["y"])
        for p in v.get("rail") or []:
            xs.append(p[0])
            ys.append(p[1])
    if not xs:
        for o in L.get("objects") or []:
            xs.append(o["x"])
            ys.append(o["y"])
    x0, x1, y0, y1 = min(xs) - MARGIN, max(xs) + MARGIN, min(ys) - MARGIN, max(ys) + MARGIN
    # never wider than MAX_SPAN, round the middle of the play area
    cx = (xs[0] + xs[1]) / 2 if fine.exists() else (x0 + x1) / 2
    cy = (ys[0] + ys[1]) / 2 if fine.exists() else (y0 + y1) / 2
    h = MAX_SPAN / 2
    return max(x0, cx - h), min(x1, cx + h), max(y0, cy - h), min(y1, cy + h)


def grid(lv):
    out = paths.data() / "terrain" / ("level%d.far.json" % lv)
    if out.exists():
        try:
            g = json.load(out.open())
            if g.get("version") == VERSION:
                return g
        except (OSError, ValueError):
            pass
    x0, x1, y0, y1 = _extent(lv)
    cell = 4.0
    while ((x1 - x0) / cell + 1) * ((y1 - y0) / cell + 1) > MAX_POINTS:
        cell *= 1.25
    cell = round(cell, 2)
    w, h = int(math.ceil((x1 - x0) / cell)) + 1, int(math.ceil((y1 - y0) / cell)) + 1
    t = Terrain(paths.pristine() / "missions" / "location0" / ("level%d" % lv), qvm_source.level_qsc(lv))
    zs = []
    for j in range(h):
        y = y0 + j * cell
        for i in range(w):
            zs.append(t.z(x0 + i * cell, y))
    have = [z for z in zs if z is not None]
    zmin = min(have) if have else 0.0
    vals = [NODATA if z is None else max(0, min(NODATA - 1, int(round((z - zmin) / STEP)))) for z in zs]
    g = {"version": VERSION, "level": lv, "x0": round(x0, 3), "y0": round(y0, 3), "cell": cell, "w": w, "h": h,
         "zmin": round(zmin, 3), "step": STEP, "nodata": NODATA,
         "z": base64.b64encode(struct.pack("<%dH" % len(vals), *vals)).decode("ascii")}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(g), encoding="utf-8")
    return g


if __name__ == "__main__":
    import sys, time
    for lv in [int(a) for a in sys.argv[1:]] or range(1, 15):
        t0 = time.time()
        g = grid(lv)
        print("level %-2d %d x %d at %.1f m, %.0f x %.0f m, %.1fs" % (lv, g["w"], g["h"], g["cell"],
              (g["w"] - 1) * g["cell"], (g["h"] - 1) * g["cell"], time.time() - t0))
