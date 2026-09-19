# Extracts real model footprints and the map computer's own building labels.
#
#   python studio/extract/models.py [--game <game>] [--levels 1,2,...]
#
# Two things the plan view needs and could not get from objects.qsc alone:
#
# 1. FOOTPRINTS. Models live packed inside models/levelN.res (an ILFF archive of
#    NAME/BODY pairs). Each BODY is itself an ILFF holding the .mef, whose XTVC
#    chunk is the collision hull. Its bounding box, divided by 4096 like every
#    other coordinate, gives the model's real size in metres - so a building can
#    be drawn at true scale instead of as a fixed-size pin.
#    (project-igi-editor's header says 1/40.96; that is not the scale that makes
#    these agree with the world, 4096 is: a crate comes out 0.90 x 1.14 x 0.50 m.)
#
# 2. LABELS. ComputerHilight tasks bind a building task id to a title/info
#    resource key, and language/english/messages.res maps those keys to the text
#    the in-game map computer prints - "Security Building", "Large Warehouse".
import json, os, pathlib, re, struct, sys
from studio import paths
from studio.qvm import source as qvm_source
# This module is a script: it does its work as it is read, the way it always
# has. Run it (python -m studio.extract.models), do not import it. The guard below
# turns an accidental import into a clear error instead of a surprise.
if __name__ != "__main__":
    raise ImportError("studio.extract.models is a script: run it, do not import it")

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = paths.data()
argv = sys.argv
GAME = pathlib.Path(argv[argv.index("--game") + 1] if "--game" in argv else str(paths.require_game()))
LEVELS = ([int(x) for x in argv[argv.index("--levels") + 1].split(",")]
          if "--levels" in argv else list(range(1, 15)))
SCALE = 4096.0


def ilff_chunks(buf, start=20):
    off = start
    while off + 16 <= len(buf):
        tag = buf[off:off + 4]
        ln, al, sz = struct.unpack_from("<III", buf, off + 4)
        if al == 0 or ln < 0 or off + 16 + ln > len(buf):
            return
        yield tag, buf[off + 16:off + 16 + ln]
        off += 16 + ((ln + al - 1) // al) * al


def unpack_res(path):
    """NAME/BODY pairs out of an ILFF archive."""
    out, cur = {}, None
    b = path.read_bytes()
    for tag, pay in ilff_chunks(b):
        if tag == b"NAME":
            cur = pay.split(b"\0")[0].decode("latin1").split("/")[-1]
        elif tag == b"BODY" and cur:
            out[cur] = pay
    return out


def mef_mesh(mef):
    """Collision mesh as triangles, in metres.

    XTVC holds the vertices (stride 16, xyz floats first) and the ECFC that
    follows it holds faces as 4 x u16 - three indices plus a flag - indexing
    that XTVC, not XTRV. Together they are a real mesh, so a footprint can be
    rasterised from actual surfaces instead of guessed from a bounding box.
    """
    vs, tris = None, []
    for tag, pay in ilff_chunks(mef, 20):
        if tag[:4] == b"XTVC":
            vs = [tuple(v / SCALE for v in struct.unpack_from("<fff", pay, i))
                  for i in range(0, len(pay) - 11, 16)]
        elif tag[:4] == b"ECFC" and vs:
            for k in range(len(pay) // 8):
                i0, i1, i2, _ = struct.unpack_from("<4H", pay, k * 8)
                if max(i0, i1, i2) < len(vs):
                    tris.append((vs[i0], vs[i1], vs[i2]))
    return tris


def footprint(mef, max_cells=22):
    """Two-tier plan footprint: the raised structure, and the ground it sits on.

    A building model often includes its concrete apron, which is why a bounding
    box reads far larger than the building. Splitting by height separates them,
    so the plan can draw the structure solid and the apron faint - the way the
    in-game map computer shows it.
    """
    tris = mef_mesh(mef)
    if len(tris) < 2:
        return None
    pts = [p for t in tris for p in t]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
    w, d, h = max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)
    if w < 1.2 and d < 1.2:
        return None
    cell = max(0.6, max(w, d) / max_cells)
    x0, y0, z0 = min(xs), min(ys), min(zs)
    nx, ny = int(w / cell) + 1, int(d / cell) + 1
    top = [[-1.0] * nx for _ in range(ny)]
    for t in tris:
        tx = [q[0] for q in t]; ty = [q[1] for q in t]
        th = max(q[2] for q in t) - z0
        for j in range(max(0, int((min(ty) - y0) / cell)), min(ny, int((max(ty) - y0) / cell) + 1)):
            for i in range(max(0, int((min(tx) - x0) / cell)), min(nx, int((max(tx) - x0) / cell) + 1)):
                px, py = x0 + (i + .5) * cell, y0 + (j + .5) * cell
                (ax, ay, _), (bx, by, _), (cx, cy, _) = t
                den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
                if abs(den) < 1e-9:
                    continue
                u = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den
                v = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den
                if u < -.1 or v < -.1 or 1 - u - v < -.1:
                    continue
                if th > top[j][i]:
                    top[j][i] = th

    cut = h * 0.55 if h > 3.5 else -1   # short things are all "structure"

    def rects(test):
        out = []
        for j in range(ny):
            i = 0
            while i < nx:
                if test(top[j][i]):
                    k = i
                    while k + 1 < nx and test(top[j][k + 1]):
                        k += 1
                    out.append([round(x0 + i * cell, 2), round(y0 + j * cell, 2),
                                round((k - i + 1) * cell, 2), round(cell, 2)])
                    i = k + 1
                else:
                    i += 1
        return out

    body = rects(lambda v: v >= cut and v >= 0)
    pad = rects(lambda v: 0 <= v < cut) if cut > 0 else []
    if not body and not pad:
        return None
    return {"w": round(w, 2), "d": round(d, 2), "h": round(h, 2),
            "cx": round((min(xs) + max(xs)) / 2, 2), "cy": round((min(ys) + max(ys)) / 2, 2),
            "z0": round(z0, 3),
            "body": body, "pad": pad}


def mef_bbox(mef):
    """Footprint from the collision hull, in game units."""
    pts = []
    for tag, pay in ilff_chunks(mef, 20):
        if tag[:4] == b"XTVC":
            for i in range(0, len(pay) - 11, 16):
                x, y, z = struct.unpack_from("<fff", pay, i)
                if all(abs(v) < 1e7 for v in (x, y, z)):
                    pts.append((x, y, z))
    if len(pts) < 3:
        return None
    xs, ys, zs = zip(*pts)
    return {"w": round((max(xs) - min(xs)) / SCALE, 2),
            "d": round((max(ys) - min(ys)) / SCALE, 2),
            "h": round((max(zs) - min(zs)) / SCALE, 2),
            "cx": round(((max(xs) + min(xs)) / 2) / SCALE, 2),
            "cy": round(((max(ys) + min(ys)) / 2) / SCALE, 2),
            "z0": round(min(zs) / SCALE, 3)}


# ---------------------------------------------------------------- footprints
# Which models each level actually packs matters: a soldier whose model is not
# in the level's archive spawns with no body at all. Its weapon still draws,
# because that comes from weapons/ - so you get a rifle floating in mid air.
sizes, archives, per_level = {}, [], {}
for lv in LEVELS:
    archives.append((lv, GAME / "missions" / "location0" / ("level%d" % lv) / "models" / ("level%d.res" % lv)))
archives.append((None, GAME / "missions" / "location0" / "common" / "models" / "location0.res"))

common = set()
for lv, a in archives:
    if not a.exists():
        continue
    got = set()
    for name, body in unpack_res(a).items():
        stem = name.replace(".mef", "")
        got.add(stem)
        if stem not in sizes:
            bb = footprint(body) or mef_bbox(body)
            if bb:
                sizes[stem] = bb
    if lv is None:
        common = got
    else:
        per_level[str(lv)] = sorted(got)
for lv in per_level:
    per_level[lv] = sorted(set(per_level[lv]) | common)
print("footprints: %d models from %d archive(s)" % (len(sizes), sum(1 for _, a in archives if a.exists())))

# ---------------------------------------------------------------- label text
def parse_messages(path):
    """messages.res: alternating NAME (key) and CSTR (text) chunks."""
    text, key = {}, None
    if not path.exists():
        return text
    for tag, pay in ilff_chunks(path.read_bytes()):
        s = pay.split(b"\0")[0].decode("latin1", "replace")
        if tag == b"NAME":
            key = s
        elif tag == b"CSTR" and key:
            text[key] = s
            key = None
    return text


strings = parse_messages(GAME / "language" / "english" / "messages.res")
print("map computer strings: %d" % len(strings))

# ------------------------------------------- ComputerHilight -> building label
R_HILIGHT = re.compile(
    r'Task_New\((-?\d+), "ComputerHilight", "([^"]*)", (-?[\d.]+), (-?[\d.]+), (-?[\d.]+), '
    r'"([^"]*)", "([^"]*)", "[^"]*", "[^"]*", "[^"]*", "([^"]*)", "([^"]*)"\)')

labels_by_level = {}
for lv in LEVELS:
    p = qvm_source.level_qsc(lv)
    if not p.exists():
        continue
    src = p.read_text(encoding="latin1")
    rows = {}
    for m in R_HILIGHT.finditer(src):
        _, _, x, y, z, _, taskid, title, info = m.groups()
        t = strings.get(title, "").rstrip(".")
        i = strings.get(info, "")
        if not t:
            continue
        rows[taskid.strip()] = {"title": t, "info": i,
                                "task": taskid.strip(),
                                "x": round(float(x) / SCALE, 2),
                                "y": round(float(y) / SCALE, 2)}
    if rows:
        labels_by_level[str(lv)] = rows

tot = sum(len(v) for v in labels_by_level.values())
print("building labels: %d across %d level(s)" % (tot, len(labels_by_level)))

OUT.mkdir(parents=True, exist_ok=True)
# keep model lists for custom slots (written by serve.py after an apply)
try:
    for k, v in json.load((OUT / "models.json").open()).get("byLevel", {}).items():
        per_level.setdefault(k, v)
except (OSError, ValueError):
    pass
json.dump({"sizes": sizes, "labels": labels_by_level, "byLevel": per_level},
          (OUT / "models.json").open("w"), separators=(",", ":"))
print("\nwrote %s  (%.0f KB)" % (OUT / "models.json", (OUT / "models.json").stat().st_size / 1024))

for k in ("400_20_1", "405_01_1", "219_01_1", "003_01_1"):
    if k in sizes:
        s = sizes[k]
        print("   %-10s %6.2f x %6.2f x %6.2f m" % (k, s["w"], s["d"], s["h"]))
if "1" in labels_by_level:
    print("\n   level 1 labels:", ", ".join(sorted({v["title"] for v in labels_by_level["1"].values()})))
