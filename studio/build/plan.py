# Turns a Project IGI Studio plan into a compilable IGI 1 level script.
#
#   python -m studio build --plan my-mission.json [--out missions/plan]
#   python -m studio build --plan - < plan.json              (read stdin)
#
# Input is the JSON the editor's "Copy plan" button produces, or a document
# read out of the artifact database. Coordinates are GAME units; this converts
# with qsc = game * 4096.
#
# Everything the engine silently refuses is checked BEFORE anything is written:
#   * task ids must be <= 4095 - above that the engine stores -1, and the
#     duplicates collide ("Symbol HumanSoldier_-1.isDead already registered")
#   * a patrol may only walk to nodes some shipped patrol walks to
#   * consecutive walk targets must be a route the shipped data proves resolves
#   * every HumanAI needs a matching MISSION:AI/<id>.qsc
import base64, binascii, collections, heapq, json, math, os, pathlib, re, struct, sys
from studio import paths
from studio.qvm import source as qvm_source
from studio.build.objects import set_soldier_team
# This module is a script: it does its work as it is read, the way it always
# has. Run it (python -m studio.build.plan), do not import it. The guard below
# turns an accidental import into a clear error instead of a surprise.
if __name__ != "__main__":
    raise ImportError("studio.build.plan is a script: run it, do not import it")

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = paths.data()
SCALE = 4096.0
MAX_TASK_ID = 4095
EOL = "\r\n"

argv = sys.argv


def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


PLAN_PATH = arg("--plan")
OUT = ROOT / arg("--out") if arg("--out") else paths.work() / "plan"
if not PLAN_PATH:
    sys.exit("usage: apply_plan.py --plan <file.json|-> [--out missions/plan]")

plan = (json.load(sys.stdin) if PLAN_PATH == "-"
        else json.load(open(PLAN_PATH, encoding="utf-8-sig")))
# A mission is built from its base - a built-in level as shipped, or that level's
# empty map - plus the whole plan. (Older plans name "level" and "mode" instead.)
BASE = plan.get("base") or {}
LV = int(BASE.get("level") or plan.get("level", 1))
EMPTY = BASE.get("kind") == "empty"
MODE = plan.get("mode", "modify")
NAME = plan.get("name", "Untitled")
PLACE = plan.get("placements", [])

meta_path = DATA / ("level%d.json" % LV)
if not meta_path.exists():
    sys.exit("no extracted data for level %d - run studio/extract/levels.py first" % LV)
meta = json.load(meta_path.open())
try:
    src_path = qvm_source.level_qsc(LV, arg("--game"))
except FileNotFoundError as e:
    sys.exit(str(e))
src = src_path.read_text(encoding="latin1")
if EMPTY:
    from studio.build import empty_map
    src = empty_map.build_empty(src)
    # all that is left of the level is its player (and its terrain and navmesh)
    meta["objects"] = [o for o in meta.get("objects", []) if o.get("type") == "player"]

errors, warnings = [], []
report = []                     # what the build did, printed with the plan at the end

# ---------------------------------------------------------------- id allocation
used = set(meta.get("usedIds", []))
free_iter = (i for i in range(3000, MAX_TASK_ID + 1) if i not in used)


def take_id():
    for i in free_iter:
        used.add(i)
        return i
    errors.append("ran out of free task ids below %d" % MAX_TASK_ID)
    return None


# ---------------------------------------------------------------- validation
def graph_facts(gid):
    return (meta.get("graphs") or {}).get(str(gid)) or {"walkable": [], "edges": []}


soldiers = [p for p in PLACE if p.get("type") == "soldier"]
pickups = [p for p in PLACE if p.get("type") == "pickup"]
objects = [p for p in PLACE if p.get("type") == "building"]
cameras = [p for p in PLACE if p.get("type") == "camera"]
alarm_kit = [p for p in PLACE if p.get("type") in ("switch", "siren", "alarmlight", "alarmctl")]
ALARM_IDS = {}                  # plan key ("own:<uid>") -> AlarmControl task id
ALARM_TRIGGER = {}              # plan key -> the terms that raise it
ALARM_SILENCE = {}              # plan key -> the buttons that also switch it off


def alarm_ctl_id(key):
    """The AlarmControl task id a plan key names, the mission's own or the level's."""
    if not key:
        return None
    if key in ALARM_IDS:
        return ALARM_IDS[key]
    if key.startswith("lv:") and key[3:].isdigit() and not EMPTY:   # an empty map has none of the level's
        return int(key[3:])
    return None


def alarm_expr_of(key):
    cid = alarm_ctl_id(key)
    return ("AlarmControl_%d.isAlarm" % cid) if cid is not None else None

b = meta["bounds"]
for p in PLACE:
    if not (b["minX"] - 200 <= p["x"] <= b["maxX"] + 200
            and b["minY"] - 200 <= p["y"] <= b["maxY"] + 200):
        warnings.append("%s sits outside the level extent (%.0f, %.0f)"
                        % (p.get("name", "?"), p["x"], p["y"]))

# Routing comes from the graph's own adjacency table, not from guessing at what
# shipped patrols happen to do. Each entry is {int32 next-hop, float32 cost};
# next == -1 means no route, which is what the engine reports as
# "Error in graph NNNN routenet, Node #A to #B". Roughly 99% of node pairs are
# mutually reachable, so only the exceptions are stored.
_graphs = {}
if _gpath_meta := (DATA / ("graphs%d.json" % LV)):
    if _gpath_meta.exists():
        _graphs = json.load(_gpath_meta.open())


def routing(gid):
    g = _graphs.get(str(gid)) or {}
    return ({n["id"] for n in g.get("nodes", [])},
            set(g.get("isolated", [])),
            {tuple(p) for p in g.get("noRoute", [])})


# ---------------------------------------------------------------- models
from studio.build import graphs as GE
from studio.build import navtemplates as NT

REMOVED_IDS = set(plan.get("removals", []) or [])
_game_arg = arg("--game")
if not _game_arg and arg("--game-ai"):
    _game_arg = str(pathlib.Path(arg("--game-ai")).resolve().parents[3])
# reading only: the reference copy when there is one, so a build still works
# when the game is not there. Installing is studio/build/install.py, and that
# writes to the game itself.
GAME = paths.levels(_game_arg)
BASE_GRAPHS = GAME / "missions" / "location0" / ("level%d" % LV) / "graphs"


# A soldier whose model is not packed in the level's archive spawns with no
# body - the weapon still draws, giving a rifle floating in mid air. Catch it
# here rather than in game.
_models_path = DATA / "models.json"
_by_level = {}
if _models_path.exists():
    _by_level = json.load(_models_path.open()).get("byLevel", {})
_have_models = set(_by_level.get(str(LV)) or _by_level.get("1") or [])
# What the target slot really packs right now (earlier imports included), read
# from its own model list rather than from what the editor was told.
from studio.build import models as MI
from studio.build import textures as TEX
SLOT_DIR = pathlib.Path(arg("--slot-dir")) if arg("--slot-dir") else     (pathlib.Path(arg("--game-ai")).parent if arg("--game-ai") else None)
if SLOT_DIR is not None and MI.level_files(SLOT_DIR):
    try:
        _have_models = {n for n, _ in MI.read_dat(MI.level_files(SLOT_DIR)["dat"])["models"]}
    except (StopIteration, ValueError, OSError):
        pass
_anywhere = set()
for _lv, _names in _by_level.items():
    _anywhere.update(_names)
IMPORTS = set()
CAM_MODELS = ("313_01_1", "313_02_1", "313_03_1")     # holder, camera, destroyed camera
# the rest of the alarm hardware: button, siren, flashing light (on and off)
# 234_01_1 is the button every shipped alarm uses; 202_01_1 is the gate panel
ALARM_MODELS = {"switch": ("234_01_1",), "siren": ("310_01_1",), "alarmlight": ("344_03_1", "344_01_1"),
                "alarmctl": ()}


_base_models = set(_by_level.get(str(LV)) or [])


def need_model(m, who):
    """A model the slot does not pack gets imported from a level that does -
    placed without it, a soldier spawns invisible and a building loads as nothing.
    One the level does not ship itself goes to the importer even when an earlier
    Apply brought it in: the importer checks its family and the parts it is built
    from are all there, and does nothing when they are (a watchtower imported
    without its stairs, 314_01_1, killed the level)."""
    if not m or not _have_models:
        return
    if m in _have_models and (not _base_models or m in _base_models):
        return
    if m in _anywhere:
        IMPORTS.add(m)
    elif m not in _have_models:
        errors.append("%s uses model %s, which no level ships" % (who, m))


for s in soldiers:
    need_model(s.get("model"), s.get("name"))
for o in objects:
    need_model(o.get("model"), o.get("name"))
for _cam in cameras:
    for _cm in CAM_MODELS:
        need_model(_cm, _cam.get("name") or "camera")
for _kit in alarm_kit:
    for _km in (("202_01_1",) if _kit.get("gate") else ALARM_MODELS.get(_kit["type"], ())):
        need_model(_km, _kit.get("name") or _kit["type"])
EDITS = [e for e in plan.get("edits", []) or [] if e.get("ref")]
for e in EDITS:
    if e.get("model"):
        need_model(e["model"], "edited %s" % e["ref"].split("@")[0])

for _kit in alarm_kit:
    if _kit["type"] == "alarmctl":
        _kit["_tid"], _kit["_var"] = take_id(), take_id()
        ALARM_IDS["own:%s" % _kit.get("uid")] = _kit["_tid"]

# ---------------------------------------------------------------- ground snap
# The F11 overlay reports the player's EYE height, about 1.65 units above the
# surface they are standing on. Soldiers snap themselves, but a pickup placed at
# a raw overlay reading hangs in the air at head height. Shipped ground pickups
# sit +0.50 above the nearest navmesh node, so that is what we aim for.
PICKUP_RISE = 0.5
# ...but on a desk, a crate or a bed the shipped ones lie right on the top
# (median +0.03 over 52 of them in levels 1-6)
PICKUP_ON_TOP = 0.02
NO_SNAP = "--no-snap" in argv
_nodes = []
_gpath = DATA / ("graphs%d.json" % LV)
if _gpath.exists():
    for _g in json.load(_gpath.open()).values():
        _nodes.extend(_g.get("nodes", []))


def ground_z(x, y, fallback):
    """Height of the walkable surface under a point.

    Navmesh nodes are the most reliable ground samples we have. A single nearest
    node is brittle - one node on a roof or a gantry drags an object into the
    air - so blend the closest few by inverse distance and reject the sample if
    they disagree, rather than guessing.
    """
    if NO_SNAP or not _nodes:
        return fallback
    near = sorted((((n["x"] - x) ** 2 + (n["y"] - y) ** 2, n) for n in _nodes), key=lambda p: p[0])[:5]
    near = [(d, n) for d, n in near if d <= 40 ** 2]
    if not near:
        return fallback
    zs = [n["z"] for _, n in near]
    if max(zs) - min(zs) > 3.0:          # a roof and the ground both nearby
        return min(zs)                   # prefer the lower surface
    wsum = tot = 0.0
    for d, n in near:
        w = 1.0 / (d ** 0.5 + 0.5)
        wsum += w
        tot += w * n["z"]
    return tot / wsum if wsum else fallback


# The real surface under each placement: exact terrain height from the level's
# terrain files, the tops of shipped models from their collision meshes, and
# under a roof the floor the editor asked for (surface.py). The node blend above
# is only the fallback - near a concrete apron it lifted objects off bare ground.
from studio.build import surface as SF
_sizes = json.load(_models_path.open()).get("sizes", {}) if _models_path.exists() else {}
_skip = set(plan.get("removeRefs", []) or [])
_by_ref = {o.get("ref"): o for o in meta.get("objects", []) if o.get("ref")}
_edit_by_ref = {e["ref"]: e for e in EDITS}


def _as_edited(o):
    """A shipped object where the plan puts it."""
    e = _edit_by_ref.get(o.get("ref"))
    if not e:
        return o
    c = dict(o)
    for k in ("x", "y", "z", "gamma"):
        if e.get(k) is not None:
            c[k] = e[k]
    return c


def _moved(o, c):
    return (abs(c["x"] - o["x"]) >= 0.05 or abs(c["y"] - o["y"]) >= 0.05
            or abs(((c.get("gamma") or 0) - (o.get("gamma") or 0) + math.pi) % (2 * math.pi) - math.pi) >= 0.01)


def _gone(o):
    return (o.get("id") in REMOVED_IDS and o.get("id", -1) >= 0) or o.get("ref") in _skip


# the level as this plan leaves it: removals gone, edited objects where they now stand
WORLD = [_as_edited(o) for o in meta.get("objects", []) if not _gone(o)]
_world_by_ref = {o.get("ref"): o for o in WORLD if o.get("ref")}
_surface = None
try:
    _surface = SF.Surface(SLOT_DIR if SLOT_DIR is not None else GAME / "missions" / "location0" / ("level%d" % LV),
                          src_path, WORLD, _sizes, nodes=_nodes)
except Exception as e:                      # never let this block a build
    warnings.append("exact ground unavailable (%s) - using navmesh heights" % e)
# The ground is worked out from the level as it ships (the reference copy),
# never from the slot: an earlier Apply may have rebuilt the slot's terrain mesh
# or rewritten its height maps, and shaping on top of that would shape twice.
from studio.build.terrain import Terrain as _Terrain
TERR0 = None
try:
    TERR0 = _Terrain(GAME / "missions" / "location0" / ("level%d" % LV), src_path)
    if _surface is not None and _surface.terrain is not None:
        _surface.terrain = TERR0
except Exception as e:
    warnings.append("the level's own ground could not be read (%s)" % e)


def rest_z(x, y, near_z, model=None, skip=None):
    """Height to place an object's origin at so it stands on the surface."""
    src_, z = (None, None)
    if _surface is not None and near_z is not None:
        src_, z = _surface.height(x, y, near_z, skip=skip)
    if z is None:
        z = ground_z(x, y, None)
        src_ = "navmesh"
    if z is None:
        return None, None
    # models are set down by their lowest point, ignoring a base plate of a few cm
    z0 = (_sizes.get(model) or {}).get("z0", 0.0) if model else 0.0
    return z - (z0 if z0 < -0.1 else 0.0), src_


# The game's own player starts stand 0.9-1.0 m above the ground under them (the
# player's origin is at the hips, not the feet - measured over levels 2-13). A
# start moved to new ground keeps that, rather than spawning half in the earth.
PLAYER_LIFT = 0.94


def _rise(kind, how):
    if kind == "player":
        return PLAYER_LIFT
    if kind != "pickup":
        return 0.0
    return PICKUP_RISE if how in ("terrain", "navmesh", "node", "floor") else PICKUP_ON_TOP


# ---------------------------------------------------------------- flattening
# New buildings get level ground: height maps written into the slot's
# terrain.hmp (studio/build/flatten.py). Computed before anything is set down, and
# registered with the terrain, so every height asked for after this - the
# building's own, and the guards and pickups around it - sees the new ground.
from studio.build import flatten as FL
PADS, FLAT_PATCHES, FLAT_HMP = {}, [], None
# The Ground tool: areas to level, raise, lower, smooth or ramp, and brush strokes.
AREAS = [a for a in (plan.get("ground") or []) if isinstance(a, dict)]
AREA_PADS = []
BRUSH = FL.brush_cells(plan.get("brush"))
SCULPT = FL.sculpt_cells(plan.get("sculpt"))   # the big shapes, on the terrain's 4 m grid
# Nothing standing on the ground has it moved from under it: buildings, walls,
# props, crates, vehicles, pickups and the player start keep the ground they
# stand on (eased in round them). Carrying them up or down with it left crates
# half in the air and a button mounted on one hanging (level 3, 2026-09-18).
# Guards are not in it - they stand on the navmesh, and the nodes on shaped
# ground move with it. Your own building that levels its ground has its pad.
# The player start is not in it either: it is a place, not a thing, and it is
# set down on the shaped ground (below) rather than left in a pit of the old.
# The editor keeps the same list (plotter.html keepsGround).
KEEP = []
KEEP_TYPES = ("building", "prop", "explodable", "vehicle", "pickup", "fence")
NODE_SHIFTS = []        # (graph, node id, x, y, new z): navmesh nodes on shaped ground
NODE_ON_GROUND = 0.75
BASE_HMP = GAME / "missions" / "location0" / ("level%d" % LV) / "terrain" / "terrain.hmp"


def wants_flat(p):
    if p.get("type") != "building":
        return False
    if "flatten" in p:
        return bool(p["flatten"])
    sz = _sizes.get(p.get("model")) or {}
    return (bool(sz.get("body")) and sz.get("h", 0) >= 2.5
            and min(sz.get("w", 0), sz.get("d", 0)) >= 2.0 and sz.get("w", 0) * sz.get("d", 0) >= 16)


# The height maps the shaped ground needs take most of a build (15 s on a
# mission with a lot of it). Kept in cache/patches under a hash of everything
# they are made from - the pads, what keeps its ground, the brush, the level's
# own height maps and the ground code itself - so an Apply that changes guards,
# objectives or events reuses them.
_PATCH_CACHE = paths.cache() / "patches"


def _patches_cached(terr, pads, first_id, mesh=None):
    import hashlib
    try:
        key = hashlib.sha1(json.dumps({
            "lv": LV, "first": first_id, "pads": pads, "keep": KEEP,
            "brush": sorted([list(k), v] for k, v in BRUSH.items()),
            "sculpt": sorted([list(k), v] for k, v in SCULPT.items()),
            "hmp": [BASE_HMP.stat().st_size, int(BASE_HMP.stat().st_mtime)] if BASE_HMP.exists() else None,
            "mesh": mesh["key"] if mesh else None,
            "code": [hashlib.sha1((ROOT / "studio" / "build" / f).read_bytes()).hexdigest()
                     for f in ("flatten.py", "terrain.py", "terrain_mesh.py")]},
            sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]
    except (TypeError, ValueError, OSError):
        key = None
    f = _PATCH_CACHE / (key + ".json") if key else None
    if f is not None and f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            patches = [dict(p, data=base64.b64decode(p["data"]), task=tuple(p["task"])) for p in d["patches"]]
            print("  shaped ground: the height maps of an earlier build with the same ground (cache)")
            return patches, d["notes"]
        except (OSError, ValueError, KeyError):
            pass
    patches, notes = FL.build_patches(terr, pads, first_id, KEEP, BRUSH,
                                      mesh=mesh["terrain"] if mesh else None, mesh_cubes=mesh["cubes"] if mesh else None,
                                      sculpt=SCULPT, folds=mesh.get("folds") if mesh else None)
    if f is not None:
        try:
            _PATCH_CACHE.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"patches": [dict(p, data=base64.b64encode(p["data"]).decode("ascii"),
                                                      task=list(p["task"])) for p in patches],
                                     "notes": notes}), encoding="utf-8")
            old = sorted(_PATCH_CACHE.glob("*.json"), key=lambda q: q.stat().st_mtime)
            for q in old[:-24]:
                q.unlink()
        except (OSError, TypeError, ValueError):
            pass
    return patches, notes


# Where the shaped ground moves further than a height map can carry it (4 m),
# the terrain mesh itself is built again there (studio/build/terrain_mesh.py):
# its 4 m grid moved to the new ground, every cube over it rebuilt, the rest of
# the level's terrain kept as it is. The height maps then carry what is left.
# The game holds 32,767 terrain nodes; the level's own use 11,000-15,000.
TERRAIN_MESH = None             # for the report and the editor: nodes used, grid points moved


class _TooMuchGround(Exception):
    pass


def _shape_terrain(terr, pads):
    """None, or {"terrain": the level with its mesh rebuilt (and its own height
    maps), "cubes": the 64 m cubes whose mesh changed, "key": for the cache}."""
    global TERRAIN_MESH
    if LV == 14 or os.environ.get("IGISTUDIO_NO_TERRAIN_MESH"):
        return None                     # level 14 is underground: its terrain is not a terrain
    import hashlib
    from studio.build import terrain_mesh as TMS
    moves = FL.mesh_changes(terr, pads, KEEP, BRUSH, SCULPT)
    if not moves:
        return None
    tree0 = TMS.Tree.load(GAME / "missions" / "location0" / ("level%d" % LV) / "terrain")
    gis, gjs = [p[0] for p in moves], [p[1] for p in moves]
    own = TMS.Heights(tree0, (min(gis) - 2, max(gis) + 2, min(gjs) - 2, max(gjs) + 2))
    targets = {p: own(*p) + dz * FL.SCALE * 3 for p, dz in moves.items() if own(*p) is not None}
    moved = TMS.settle(targets, own)
    if not moved:
        return None
    try:
        tree1, rep = TMS.rebuild(tree0, own, moved)
    except TMS.TooManyNodes as e:
        TERRAIN_MESH = {"nodes": e.nodes, "limit": TMS.NODE_LIMIT, "was": len(tree0.nodes), "points": len(moved),
                        "over": True}
        raise _TooMuchGround("the shaped ground needs more new terrain than the game can hold: %d terrain nodes, "
                             "it takes %d (the level's own use %d). Make the biggest shapes smaller or fewer"
                             % (e.nodes, TMS.NODE_LIMIT, len(tree0.nodes)))
    (OUT / "terrain").mkdir(parents=True, exist_ok=True)
    tree1.save(OUT / "terrain")
    mesh = _Terrain(OUT)
    mesh.hmaps = list(terr.hmaps)           # the level's own height maps, over the new mesh
    cube = 1 << (31 - FL.LOD)
    cubes = {((a + da) * TMS.GRID // cube, (b + db) * TMS.GRID // cube)
             for (a, b) in list(moved) + list(rep.get("folds", ())) for da in (-1, 0, 1) for db in (-1, 0, 1)}
    TERRAIN_MESH = {"nodes": rep["nodes"], "limit": TMS.NODE_LIMIT, "was": rep["was"], "points": len(moved)}
    report.append("terrain mesh rebuilt where the ground moves more than %.0f m: %d grid points, "
                  "%d of %d terrain nodes (the level's own: %d)"
                  % (FL.MESH_FROM, len(moved), rep["nodes"], TMS.NODE_LIMIT, rep["was"]))
    key = hashlib.sha1(json.dumps(sorted([list(k), v] for k, v in moved.items())).encode()).hexdigest()[:16]
    mg = 64 * FL.SCALE                      # the light round a change moves a little way past it
    box = (min(a for a, _ in moved) * TMS.GRID - mg, max(a for a, _ in moved) * TMS.GRID + mg,
           min(b for _, b in moved) * TMS.GRID - mg, max(b for _, b in moved) * TMS.GRID + mg)
    changed = (min(a for a, _ in moved) * TMS.GRID, max(a for a, _ in moved) * TMS.GRID,
               min(b for _, b in moved) * TMS.GRID, max(b for _, b in moved) * TMS.GRID)
    tallest = max(abs(z - own(*p)) for p, z in moved.items() if own(*p) is not None) / (3 * FL.SCALE)
    return {"terrain": mesh, "cubes": cubes, "key": key, "box": box, "changed": changed, "tallest": tallest,
            "folds": rep.get("folds", [])}


MESH = None
if TERR0 is not None and _surface is not None and _surface.terrain is not None and not NO_SNAP:
    _terr = TERR0
    _pads = []
    if AREAS or BRUSH or SCULPT:
        for o in WORLD + [p for p in PLACE if not wants_flat(p)]:
            if o.get("type") not in KEEP_TYPES or o.get("cutscene") or o.get("x") is None:
                continue
            if o.get("onLevel"):
                continue                # set on ground this plan levels for it (a compound)
            if o.get("type") != "building":
                g0 = _terr.z(o["x"], o["y"])
                if g0 is not None and abs(o["z"] - g0) >= 3:
                    continue            # on a roof or up a tower: what it stands on keeps its ground
            k = FL.keep_for(o, _sizes)
            if k:
                KEEP.append(k)
    for _i, _a in enumerate(AREAS):
        try:
            _apad = FL.pad_for_area(dict(_a, name="ground area %d" % (_i + 1)), _terr)
        except (KeyError, TypeError, ValueError):
            _apad = None
        if _apad:
            AREA_PADS.append(_apad)
            _pads.append(_apad)
    # a building placed on shaped ground is levelled for the ground as shaped
    _shaped = FL.Shaped(_terr, AREA_PADS, KEEP, BRUSH, SCULPT) if (AREA_PADS or BRUSH or SCULPT) else _terr
    for p in PLACE:
        if wants_flat(p):
            pad = FL.pad_for(p, _sizes, _shaped)
            if pad and pad["high"] - pad["low"] > 0.25:
                _pads.append(pad)
                PADS[id(p)] = pad
    if _pads or BRUSH or SCULPT:
        try:
            # levels 2, 4, 5, 7 and 11-14 ship without height maps: start an empty file
            FLAT_HMP = FL.read_hmp(BASE_HMP) if BASE_HMP.exists() else FL.empty_hmp()
            MESH = _shape_terrain(_terr, _pads)
            FLAT_PATCHES, _notes = _patches_cached(_terr, _pads, FL.first_free_id(FLAT_HMP), MESH)
            warnings.extend(_notes)
        except _TooMuchGround as e:
            errors.append(str(e))
            PADS, FLAT_PATCHES, MESH = {}, [], None
        except (OSError, ValueError) as e:
            warnings.append("ground not flattened: %s" % e)
            PADS, FLAT_PATCHES, MESH = {}, [], None
    if FLAT_PATCHES:
        # what stands on ground that moves goes with it: before and after
        _boxes = [pd["box"] for pd in _pads]
        if BRUSH:
            _bx = [ix for ix, _ in BRUSH]
            _by = [iy for _, iy in BRUSH]
            _boxes.append((min(_bx) - 1, max(_bx) + 2, min(_by) - 1, max(_by) + 2))
        if SCULPT:
            _sx = [ix * FL.SCULPT_M for ix, _ in SCULPT]
            _sy = [iy * FL.SCULPT_M for _, iy in SCULPT]
            _boxes.append((min(_sx) - 4, max(_sx) + 4, min(_sy) - 4, max(_sy) + 4))

        def _in_shaped(x, y):
            return any(b[0] <= x <= b[1] and b[2] <= y <= b[3] for b in _boxes)

        _nodes_on = []
        _gj = DATA / ("graphs%d.json" % LV)
        if _gj.exists():
            for _gid, _gr in json.load(_gj.open()).items():
                for _n in _gr.get("nodes", []):
                    if _in_shaped(_n["x"], _n["y"]):
                        g0 = _terr.z(_n["x"], _n["y"])
                        if g0 is not None and abs(_n["z"] - g0) <= NODE_ON_GROUND:
                            _nodes_on.append((_gid, _n, g0))
        # from here on every height is the new ground's: the rebuilt mesh (if
        # any) with the height maps over it
        _after = MESH["terrain"] if MESH else _terr
        FL.register(_after, FLAT_PATCHES)
        _surface.terrain = _after
        # the terrain's baked light over the rebuilt ground (lightmaps.py)
        if MESH:
            try:
                from studio.build import lightmaps as LMP
                _lmp = GAME / "missions" / "location0" / ("level%d" % LV) / "terrain" / "terrain.lmp"
                if _lmp.exists():
                    _fit = LMP.fit_sun(LV, _terr, src, _lmp)
                    _items = LMP.read_lmp(_lmp)
                    _lit = LMP.relight(_items, LMP.tasks_of(src), _terr, _after, MESH["box"],
                                       dict(_fit, tallest=MESH["tallest"]), MESH["changed"])
                    if _lit:
                        (OUT / "terrain").mkdir(parents=True, exist_ok=True)
                        LMP.write_lmp(OUT / "terrain" / "terrain.lmp", _items)
                        MESH["lit"] = _lit
                        report.append("terrain light redone over the rebuilt ground: %d light map pixels" % _lit)
                    elif _fit.get("r", 0) < LMP.MIN_FIT:
                        report.append("terrain light kept as the level has it (its light does not follow the "
                                      "lie of the land closely enough to redo)")
            except (OSError, ValueError) as e:
                warnings.append("the terrain light over the rebuilt ground was left as it was: %s" % e)
        for _gid, _n, g0 in _nodes_on:
            g1 = _after.z(_n["x"], _n["y"])
            if g1 is not None and abs(g1 - g0) >= 0.03:
                NODE_SHIFTS.append((str(_gid), int(_n["id"]), _n["x"], _n["y"], round(_n["z"] + g1 - g0, 3)))
        # A player start that stood on the level's ground stands on the shaped
        # ground: set down on it again (_snap_edit, "settle"), whether or not the
        # plan moved it - so a start under a mountain is on its slope, and one
        # whose mountain was taken away again is back on the ground.
        for _o in WORLD:
            if _o.get("type") != "player" or not _o.get("ref") or _o.get("cutscene"):
                continue
            _own = _by_ref.get(_o["ref"]) or _o
            _g0 = _terr.z(_own["x"], _own["y"])
            if _g0 is None or abs(_own["z"] - PLAYER_LIFT - _g0) > 1.5:
                continue                        # on a roof or up a tower: not the ground's
            _e = _edit_by_ref.get(_o["ref"])
            _x, _y = (_e["x"], _e["y"]) if _e and _e.get("x") is not None else (_o["x"], _o["y"])
            _g1 = _after.z(_x, _y)
            if _g1 is None or abs((_e["z"] if _e else _o["z"]) - PLAYER_LIFT - _g1) < 0.05:
                continue
            if _e is None:
                _e = {"ref": _o["ref"], "type": "player", "qtype": _o.get("qtype") or "HumanPlayer",
                      "id": _o.get("id", -1), "name": _o.get("name") or "Player spawn",
                      "x": _o["x"], "y": _o["y"], "z": _o["z"], "gamma": _o.get("gamma") or 0}
                EDITS.append(_e)
                _edit_by_ref[_o["ref"]] = _e
            _e["settle"] = True


def _snap_place(p):
    if p.get("exact"):
        return                  # put down by hand in the 3D close-up: where it was put
    pad = PADS.get(id(p))
    if pad is not None and FLAT_PATCHES:
        # on the ground levelled for it
        z0 = (_sizes.get(p.get("model")) or {}).get("z0", 0.0)
        z = pad["target"] - (z0 if z0 < -0.1 else 0.0)
        if abs(z - p["z"]) > 0.15:
            warnings.append("%s: z %.2f -> %.2f (on ground flattened from %.1f-%.1f)"
                            % (p.get("name", "?"), p["z"], z, pad["low"], pad["high"]))
        p["z"] = round(z, 3)
        return
    if p["type"] == "building" and _surface is not None and not NO_SNAP             and (_sizes.get(p.get("model")) or {}).get("body"):
        # on the lowest ground under its footprint, so no side of it floats
        z, how = _surface.rest("building", p["x"], p["y"], None, p.get("model"), gamma=p.get("gamma") or 0)
        spread = (_surface.last or {}).get("spread")
        if z is not None:
            if abs(z - p["z"]) > 0.15:
                warnings.append("%s: z %.2f -> %.2f (on %s)" % (p.get("name", "?"), p["z"], z, how))
            if spread is not None and spread > 1.5:
                warnings.append("%s: the ground under it varies by %.1f m - it sinks up to %.1f m into the slope "
                                "on the high side" % (p.get("name", "?"), spread, spread))
            p["z"] = round(z, 3)
            return
    g, how = rest_z(p["x"], p["y"], p.get("z"), p.get("model") if p["type"] != "pickup" else None)
    if g is not None:
        want = round(g + _rise(p["type"], how), 3)
        if abs(want - p["z"]) > 0.15:
            warnings.append("%s: z %.2f -> %.2f (on %s)" % (p.get("name", "?"), p["z"], want, how))
        p["z"] = want


def _snap_edit(e, kinds):
    """A shipped object moved somewhere else rests on whatever is there - unless
    it was put down in the editor's 3D close-up, which saw what is there."""
    if e.get("exact"):
        return
    o = _by_ref.get(e["ref"])
    if not o or o.get("type") not in kinds:
        return
    ex, ey = (e["x"], e["y"]) if e.get("x") is not None else (o["x"], o["y"])
    moved = abs(ex - o["x"]) >= 0.05 or abs(ey - o["y"]) >= 0.05
    # "settle": the editor asked for this object to be dropped onto what is under it
    if not moved and not e.get("settle"):
        return
    g, how = rest_z(ex, ey, e.get("z", o["z"]) - _rise(o["type"], None) * (o["type"] == "player"),
                    o.get("model") if o["type"] not in ("pickup", "player") else None, skip=e["ref"])
    if g is not None:
        e["z"] = round(g + _rise(o["type"], how), 3)
        if e["ref"] in _world_by_ref:
            _world_by_ref[e["ref"]]["z"] = e["z"]


# ---------------------------------------------------------------- building interiors
# Building floors are not in the collision meshes: the engine stands a soldier
# on the navmesh. A building placed with no nodes inside leaves its guards in
# the foundation, and guards on the yard links underneath walk through it. So a
# building the plan places brings the interior of a shipped copy
# (navtemplates.json) - floor, stair and door nodes, joined to the yard through
# its doorways - and the yard links it now stands across are cut.
_tpl_path = DATA / "navtemplates.json"
_tpl = json.load(_tpl_path.open()) if _tpl_path.exists() else {"models": {}, "aliases": {}}
LINK_EXIT = 12.0        # metres: a doorway is joined to yard nodes this close
EXIT_LINKS = 3          # ... at most this many of them
DOOR_STEP = 1.5         # an inside doorway node is judged from this far out


def template_for(model):
    t = _tpl["models"].get(model)
    if t is None and model in _tpl.get("aliases", {}):
        t = _tpl["models"].get(_tpl["aliases"][model])
    return t


def to_world(o, mx, my, dz):
    g = o.get("gamma") or 0.0
    c, s_ = math.cos(g), math.sin(g)
    return (o["x"] + mx * c - my * s_, o["y"] + mx * s_ + my * c, o["z"] + dz)


def inside(o, x, y, z, margin=0.3):
    """Is a point within a building's walls and between its floor and roof?"""
    sz = _sizes.get(o.get("model")) or {}
    z0 = sz.get("z0", 0.0)
    if not (z0 - 0.5 <= z - o["z"] <= z0 + sz.get("h", 0.0) + 0.5):
        return False
    mx, my = NT.to_model(o, x, y)
    return NT.inside(sz.get("body") or [], mx, my, margin)


# 1. what the plan builds and moves is set down on the level first
for p in PLACE:
    if p.get("type") in ("building", "explodable"):
        _snap_place(p)      # cameras, buttons, sirens and lights hang where they were mounted
for e in EDITS:
    _snap_edit(e, ("prop", "building"))

# 2. it is solid from here on, and the interiors it brings have floors


def _base_counts():
    """Ref counts of the shipped level a custom slot was made from (None on a shipped level)."""
    if LV <= 14:
        return None
    refs = collections.Counter(o.get("ref") for o in WORLD if o.get("ref"))
    best = None
    for lv in range(1, 15):
        p = DATA / ("level%d.json" % lv)
        if not p.exists():
            continue
        base = collections.Counter(o.get("ref") for o in json.load(p.open())["objects"] if o.get("ref"))
        shared = sum((refs & base).values())
        if best is None or shared > best[0]:
            best = (shared, base)
    if not best or best[0] < len(refs) // 2:
        return None
    return best[1]


# objects an earlier Apply put in this slot - whatever the shipped level lacks
ADDED = set()
_bc = _base_counts()
if _bc is not None:
    _seen = collections.Counter()
    for o in WORLD:
        r = o.get("ref")
        if r:
            _seen[r] += 1
            if _seen[r] > _bc.get(r, 0):
                ADDED.add(id(o))

INTERIORS = []          # (key, pose, template, label)
FLOORS = {}             # key -> (floors, missing): heights above the building's origin


def own_heights(o):
    """Heights (above the building's origin) of the nodes a level building has inside."""
    here = [n for n in _nodes if inside(o, n["x"], n["y"], n["z"])]
    flat = [n["z"] - o["z"] for n in here if "STAIR" not in (n.get("c") or "")]
    return flat or [n["z"] - o["z"] for n in here]


def building_floors(key, o, t, merge):
    """(every floor, floors with no nodes yet). A placed building has none of its own;
    a level building keeps the floors its nodes are on - a watchtower's ground, say -
    and lacks only the template floors nothing stands on, like its platform."""
    if key not in FLOORS:
        zs = own_heights(o) if merge else []
        tf = [f for f, _ in t["floors"]]
        # a template floor is there if any node stands at its height - clustering
        # first let yard nodes at the doorstep swallow a floor 30 cm up
        missing = [f for f in tf if not any(abs(f - z) <= 0.3 for z in zs)]
        extra = [f for f, _ in NT.floors_of(zs)] if zs else []
        extra = [f for f in extra if not any(abs(f - g) <= 0.3 for g in tf)]
        FLOORS[key] = (sorted(tf + extra), missing)
    return FLOORS[key]


def add_interior(key, o, t, label, merge):
    if any(k == key for k, _, _, _ in INTERIORS):
        return True
    floors, missing = building_floors(key, o, t, merge)
    if not missing:
        report.append("%s already has nodes on every floor - left as it is" % label)
        return False
    INTERIORS.append((key, o, t, label))
    return True


def _label(o):
    return "%s at %.0f, %.0f" % (o.get("name") or o.get("modelName") or o.get("model"), o["x"], o["y"])


for p in objects:
    if _surface is not None:
        _surface.add_object(p)
    t = template_for(p.get("model"))
    # a building people walk into gets its floors now; a tower or pylon platform
    # (no way in, nothing near the ground) only once a guard is put up there
    if t and p.get("interior", True) and (t["exits"] or min(f for f, _ in t["floors"]) < 1.5):
        add_interior(p.get("uid") or "p%d" % objects.index(p), p, t, p.get("name") or p.get("model"), False)
for e in EDITS:
    if not e.get("interior"):
        continue
    o = _world_by_ref.get(e["ref"])
    t = o and template_for(o.get("model"))
    if not t:
        warnings.append("%s: no shipped copy of this building has an interior to borrow" % e["ref"])
        continue
    add_interior(e["ref"], o, t, _label(o), True)


def building_around(x, y, z):
    """(key, pose, template, label, merge) of the smallest building with a known
    interior that a point is inside - one the plan places, or one in the level."""
    best, area = None, 1e18
    cands = [(p.get("uid") or "p%d" % i, p, p.get("name") or p.get("model"), False)
             for i, p in enumerate(objects) if p.get("interior", True)]
    cands += [(o.get("ref"), o, _label(o), True) for o in WORLD
              if o.get("ref") and not o.get("cutscene") and o.get("type") in ("building", "prop")]
    for key, o, label, merge in cands:
        t = template_for(o.get("model"))
        sz = _sizes.get(o.get("model")) or {}
        if not t or not inside(o, x, y, z, margin=0.2):
            continue
        a = sz.get("w", 0) * sz.get("d", 0)
        if a < area:
            best, area = (key, o, t, label, merge), a
    return best


def pick_floor(floors, dz):
    below = [f for f in floors if f <= dz + 0.8]
    return max(below) if below else min(floors)


def stand_on_floor(x, y, z, who):
    """Where a guard inside a building stands: (interior key or None, floor height).
    A floor with no nodes yet gets them - the engine stands soldiers on nodes."""
    b = building_around(x, y, z)
    if not b:
        return None, None
    key, o, t, label, merge = b
    floors, missing = building_floors(key, o, t, merge)
    f = pick_floor(floors, z - o["z"])
    if any(abs(f - m) < 1e-6 for m in missing):
        if add_interior(key, o, t, label, merge) and merge:
            report.append("%s stands on a floor of %s with no nodes - its floor nodes are added" % (who, label))
    return (key if any(k == key for k, _, _, _ in INTERIORS) else None), o["z"] + f


_floored = 0            # interiors whose floors the surface model already knows


def floors_to_surface():
    global _floored
    if _surface is not None:
        for _k, o, t, _l in INTERIORS[_floored:]:
            _surface.nodes.extend(to_world(o, n[0], n[1], n[2]) for n in t["nodes"] if not n[7])
    _floored = len(INTERIORS)


floors_to_surface()


def floor_in(x, y, z):
    """(interior key, floor height) for a point inside a building given an interior."""
    for key, o, t, _ in INTERIORS:
        if inside(o, x, y, z):
            return key, o["z"] + pick_floor(FLOORS[key][0], z - o["z"])
    return None, None


# 3. pickups can now lie on a table the plan placed, and guards stand on floors
for p in PLACE:
    if p.get("type") == "pickup":
        _snap_place(p)
for e in EDITS:
    _snap_edit(e, ("pickup", "player"))
def on_what_is_under(x, y, z):
    """A guard's feet on the terrain, a kerb, an apron or a platform right under
    him. The engine leaves a guard placed in the air hanging there."""
    if _surface is None or NO_SNAP:
        return None, None
    return _surface.rest("soldier", x, y, z)


for s in soldiers:
    key, fz = stand_on_floor(s["x"], s["y"], s["z"], s.get("name") or "a guard")
    if fz is not None:
        s["z"] = round(fz, 3)
        if key is not None:
            s["_interior"] = key
    else:
        gz, how = on_what_is_under(s["x"], s["y"], s["z"])
        if gz is not None:
            if abs(gz - s["z"]) > 0.15:
                warnings.append("%s: z %.2f -> %.2f (on %s)" % (s.get("name", "guard"), s["z"], gz, how))
            s["z"] = round(gz, 3)
# guards an earlier Apply created (or this plan moves) stand on floors too; the
# level's own guards are left where the game put them
lifted = 0
for o in WORLD:
    if o.get("type") != "soldier" or not o.get("ref"):
        continue
    e = _edit_by_ref.get(o["ref"])
    if id(o) not in ADDED and not (e and e.get("x") is not None):
        # the level's own guard: only onto a floor that had no nodes until now
        key, fz = floor_in(o["x"], o["y"], o["z"])
        if key is None or not any(abs(fz - o_["z"] - m) < 1e-6 for k_, o_, _, _ in INTERIORS
                                  if k_ == key for m in FLOORS[key][1]):
            continue
    else:
        key, fz = stand_on_floor(o["x"], o["y"], o["z"], o.get("name") or "guard #%s" % o.get("id"))
        if fz is None:
            fz = on_what_is_under(o["x"], o["y"], o["z"])[0]
    if fz is None or abs(fz - o["z"]) < 0.05:
        continue
    if e is None:
        e = _edit_by_ref[o["ref"]] = {"ref": o["ref"], "type": "soldier"}
        EDITS.append(e)
    e["z"] = o["z"] = round(fz, 3)
    lifted += 1
if lifted:
    report.append("%d guard(s) already in the level now stand on the floor of the building they are in" % lifted)
floors_to_surface()     # floors added for guards just now

# What came with a building - its doors, its lift, the things inside it - keeps
# its place: the building may have been set down on the ground or lifted onto
# levelled ground since, and its own things go with it rather than staying where
# the plan first put them.
_by_uid = {p.get("uid"): p for p in PLACE if p.get("uid")}
_moved_doors = 0
for _d in PLACE:
    _sl, _of = _d.get("slot"), _d.get("of")
    if not (isinstance(_sl, dict) and _of and _of in _by_uid):
        continue
    _b = _by_uid[_of]
    _g = float(_b.get("gamma") or 0)
    _c, _s2 = math.cos(_g), math.sin(_g)
    _x = round(float(_b["x"]) + _sl.get("dx", 0) * _c - _sl.get("dy", 0) * _s2, 3)
    _y = round(float(_b["y"]) + _sl.get("dx", 0) * _s2 + _sl.get("dy", 0) * _c, 3)
    _z = round(float(_b["z"]) + _sl.get("dz", 0), 3)
    if abs(_x - float(_d["x"])) > 0.01 or abs(_y - float(_d["y"])) > 0.01 or abs(_z - float(_d["z"])) > 0.01:
        _moved_doors += 1
    _d["x"], _d["y"], _d["z"] = _x, _y, _z
    _d["gamma"] = round((_g + _sl.get("dh", 0)) % (2 * math.pi), 5)
if _moved_doors:
    report.append("%d thing(s) of a building's own moved with it" % _moved_doors)

# Every height is settled now: the editor takes them from here, so its map and
# its 3D close-up show things where the game will have them (serve.py
# mission_heights). Written before anything can stop the build.
try:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "heights.json").write_text(json.dumps({
        "placements": {p["uid"]: round(float(p["z"]), 3) for p in PLACE if p.get("uid") and p.get("z") is not None},
        "edits": {e["ref"]: round(float(e["z"]), 3) for e in EDITS if e.get("z") is not None},
        "terrain": TERRAIN_MESH}), encoding="utf-8")
except (OSError, TypeError, ValueError):
    pass


# ---------------------------------------------------------------- new graph nodes
# Plan nodes are added to the BASE level's graph files, which are then staged
# for the slot alongside the script. Patrols may name them as "n:<uid>"; those
# references are resolved to real node ids here, before validation, so a patrol
# through a brand-new node is checked against the edited routing table.
plan_nodes = [p for p in plan.get("nodes", []) or []]
node_edits = [e for e in plan.get("nodeEdits", []) or []]
edited_graphs = {}          # gid -> GE.Graph
node_ids = {}               # plan node uid -> assigned node id
origins = meta.get("graphOrigins") or {}


def edit_graph(gid, what):
    """The base level's graph, loaded once per plan so every edit stacks up."""
    if gid not in origins:
        errors.append("%s: graph %s has no AIGraph origin in level %d" % (what, gid, LV))
        return None
    if gid not in edited_graphs:
        try:
            edited_graphs[gid] = GE.Graph(str(BASE_GRAPHS / ("graph%s.dat" % gid)))
        except (OSError, GE.GraphError) as e:
            errors.append("cannot edit graph %s: %s" % (gid, e))
            return None
    return edited_graphs[gid]


# Patrol commands that name a node: 2 walk to, 3 run to, 5 look at.
NODE_CMDS = (2, 3, 5)
EDIT_SOLDIERS = [e for e in EDITS if e.get("type") == "soldier" and e.get("patrol") is not None]
for e in EDIT_SOLDIERS:
    e.setdefault("name", "guard %s" % e["ref"].split("@")[1])
    e.setdefault("graph", (_by_ref.get(e["ref"]) or {}).get("graph"))


def shipped_guards(gid):
    """(label, nodes any of his paths name, [walk routes]) for every shipped guard
    still on this graph. Alarm paths count: the engine routes them too."""
    out = []
    if MODE == "new":            # a new mission strips the shipped guards
        return out
    for o in meta.get("objects", []):
        if o.get("type") != "soldier" or str(o.get("graph")) != str(gid) or _gone(o):
            continue
        routes = o.get("routes")
        if isinstance(routes, dict):
            e = _edit_by_ref.get(o.get("ref"))
            idle = o.get("idlePath")
            # a rewritten patrol is checked with the plan's own soldiers
            routes = [r for k, r in routes.items()
                      if not (e and e.get("patrol") is not None and str(idle) == k)]
        else:
            routes = [[n for c, n in (o.get("patrolCmds") or []) if c in (2, 3)]]
        names = set(o.get("pathNodes") or [n for c, n in (o.get("patrolCmds") or []) if c in NODE_CMDS])
        if names or any(routes):
            out.append((o.get("name") or "guard #%s" % o.get("id"), names, [r for r in routes if r]))
    return out


def plan_routes(gid):
    """(label, [node ids]) for the plan's own patrols on a graph - new nodes left out."""
    out = []
    for s in soldiers + EDIT_SOLDIERS:
        if str(s.get("graph")) == str(gid):
            r = [n for n in (s.get("patrol") or []) if isinstance(n, int)]
            if r:
                out.append((s.get("name") or "guard", r))
    return out


def node_used(gid, nid):
    return sorted({w for w, names, _ in shipped_guards(gid) if nid in names} |
                  {w for w, r in plan_routes(gid) if nid in r})


def origin_of(gid):
    o = origins[gid]
    return (o["x"], o["y"], o["z"])


def node_world(gid, n):
    o = origins[gid]
    return (o["x"] + n["x"] / SCALE, o["y"] + n["y"] / SCALE, o["z"] + n["z"] / SCALE)


_peeked = {}


def peek_graph(gid):
    """A graph to look at; it only becomes an edit once adopt() is called."""
    if gid in edited_graphs:
        return edited_graphs[gid]
    if gid not in _peeked:
        try:
            _peeked[gid] = GE.Graph(str(BASE_GRAPHS / ("graph%s.dat" % gid)))
        except (OSError, GE.GraphError):
            _peeked[gid] = None
    return _peeked[gid]


def adopt(gid):
    if gid not in edited_graphs and _peeked.get(gid) is not None:
        edited_graphs[gid] = _peeked[gid]
    return edited_graphs.get(gid)


# Navmesh nodes on shaped ground go up or down with it (the engine stands a
# guard on the navmesh). A node the plan moves or removes itself is left to it.
_edited_nodes = {(str(e.get("graph")), int(e.get("id"))) for e in node_edits}
for _gid, _nid, _x, _y, _z in NODE_SHIFTS:
    if (_gid, _nid) not in _edited_nodes and _gid in origins:
        node_edits.append({"graph": _gid, "id": _nid, "action": "move", "x": _x, "y": _y, "z": _z, "_ground": True})

# Existing nodes first - moved or removed - so new nodes link to the graph as it
# will actually be.
for ed in node_edits:
    gid, nid = str(ed.get("graph")), int(ed.get("id"))
    g = edit_graph(gid, "node %d" % nid)
    if g is None:
        continue
    if ed.get("action") == "remove":
        users = node_used(gid, nid)
        if users:
            errors.append("node %d on graph %s cannot be removed - %s patrol%s through it"
                          % (nid, gid, ", ".join(users), "s" if len(users) > 1 else ""))
            continue
        try:
            ed["_linked"] = g.remove_node(nid)
        except GE.GraphError as e:
            errors.append("remove node %d on graph %s: %s" % (nid, gid, e))
    elif ed.get("action") == "move":
        try:
            far = g.move_node(nid, (ed["x"], ed["y"], ed["z"]), origin_of(gid))
        except GE.GraphError as e:
            errors.append("move node %d on graph %s: %s" % (nid, gid, e))
            continue
        for other, d, dz in (far if not ed.get("_ground") else []):
            warnings.append("node %d now sits %.1f m from linked node %d (%.1f m of height) - "
                            "guards will walk that link in a straight line"
                            % (nid, d, other, dz))

# A shipped building that moves takes its interior with it; one that goes
# takes its floor nodes away (a guard would otherwise stand on thin air).
CARRIED = set()                 # (gid, node id)
for o in meta.get("objects", []):
    if not (_sizes.get(o.get("model")) or {}).get("body"):
        continue
    # a building - or a big prop (an EditRigidObj barracks) with a known interior
    if o.get("type") != "building" and not (o.get("type") == "prop" and template_for(o.get("model"))):
        continue
    new = _world_by_ref.get(o.get("ref"))
    gone = _gone(o)
    if not gone and (new is None or not _moved(o, new)):
        continue
    for gid in origins:
        g = peek_graph(gid)
        t = NT.interior(o, _sizes[o["model"]], g, origins[gid]) if g else None
        if not t:
            continue
        label = "%s at %.0f, %.0f" % (o.get("modelName") or o["model"], o["x"], o["y"])
        g = adopt(gid)
        if gone:
            inner = [nid for k, nid in enumerate(t["ids"]) if not t["nodes"][k][7]]
            kept = [nid for nid in inner if node_used(gid, nid)]
            for nid in inner:
                if nid not in kept:
                    g.remove_node(nid)
            report.append("removed %s: %d floor node(s) on graph %s went with it"
                          % (label, len(inner) - len(kept), gid))
            if kept:
                warnings.append("removed %s, but patrols still use its floor node(s) %s on graph %s - "
                                "those guards will walk where it stood" % (label, kept, gid))
            continue
        ids = set(t["ids"])
        costs = {k: v for k, v in g.edge_cost.items() if k[0] in ids and k[1] in ids}
        for k, nid in enumerate(t["ids"]):
            n = t["nodes"][k]
            g.move_node(nid, to_world(new, n[0], n[1], n[2]), origin_of(gid))
            g._node(nid)["gamma"] = (n[3] + (new.get("gamma") or 0.0)) % (2 * math.pi)
            CARRIED.add((gid, nid))
        g.edge_cost.update(costs)          # the inside did not change shape
        report.append("moved %s: its %d interior node(s) on graph %s moved with it" % (label, len(ids), gid))


def _adjacency(edges):
    adj = collections.defaultdict(list)
    for e in edges:
        adj[e[0]].append(e[1])
        adj[e[1]].append(e[0])
    return adj


def _reach(adj, a, b):
    seen, todo = {a}, [a]
    while todo:
        u = todo.pop()
        if u == b:
            return True
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                todo.append(v)
    return False


def _shortest(edges, pos, a, b):
    adj = collections.defaultdict(list)
    for e in edges:
        u, v = e[0], e[1]
        if u in pos and v in pos:
            d = math.dist(pos[u], pos[v])
            adj[u].append((v, d))
            adj[v].append((u, d))
    best, prev, heap = {a: 0.0}, {}, [(0.0, a)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == b:
            path = [b]
            while path[-1] != a:
                path.append(prev[path[-1]])
            return path[::-1]
        if d > best[u]:
            continue
        for v, w in adj[u]:
            if d + w < best.get(v, 1e18):
                best[v], prev[v] = d + w, u
                heapq.heappush(heap, (d + w, v))
    return None


def _key(e):
    return (min(e[0], e[1]), max(e[0], e[1]))


# Links that now pass through something solid are cut: a guard follows his
# links in a straight line, walls or not. A link a patrol cannot do without is
# kept (with a warning), and a node the cuts leave stranded inside a new
# building is taken out unless a patrol names it.
# a gate of yours opens: walkways through it stay (guards walk through it open)
SOLIDS = [(p, p.get("name") or p.get("model")) for p in objects if not isinstance(p.get("door"), dict)]
for e in EDITS:
    o, new = _by_ref.get(e["ref"]), _world_by_ref.get(e["ref"])
    if o and new and o.get("type") in ("building", "prop") and (_moved(o, new) or e.get("interior")):
        SOLIDS.append((new, "%s %s" % ("moved" if _moved(o, new) else "the", o.get("modelName") or o.get("model"))))


def _added_before():
    """Buildings and props an earlier Apply put in a custom slot. Links under
    those were never cut."""
    return [o for o in WORLD if id(o) in ADDED and o.get("type") in ("building", "prop")
            and o.get("ref") and not o.get("cutscene")]


_listed = {id(o) for o, _ in SOLIDS}
for o in _added_before():
    if id(o) not in _listed:
        SOLIDS.append((o, "%s placed earlier" % (o.get("name") or o.get("modelName") or o.get("model"))))
if _surface is not None and SOLIDS:
    for gid in origins:
        g = peek_graph(gid)
        if g is None:
            continue
        pos = {n["id"]: node_world(gid, n) for n in g.nodes}
        # a building's own inside and doorway links go through its door frames
        # and partitions by design - they are never cut on its account
        own = {}
        for o, _ in SOLIDS:
            sz = _sizes.get(o.get("model")) or {}
            t = NT.interior(o, sz, g, origins[gid]) if sz.get("body") else None
            own[id(o)] = set(t["ids"]) if t else set()
        cut = {}
        for e in g.edges:
            a, c = e[0], e[1]
            if a not in pos or c not in pos or ((gid, a) in CARRIED and (gid, c) in CARRIED):
                continue
            for o, label in SOLIDS:
                if a in own[id(o)] and c in own[id(o)]:
                    continue
                if _surface.blocked(pos[a], pos[c], only=o):
                    cut[_key(e)] = label
                    break
        # yard nodes a building with a known floor now covers, under that floor:
        # a guard sent there would stand in the foundation
        under = set()
        for o, _ in SOLIDS:
            t = template_for(o.get("model"))
            if not t:
                continue
            low = min(f for f, _ in t["floors"])
            if low > 1.5:
                continue
            for nid in own[id(o)]:
                x, y, z = pos[nid]
                if z - o["z"] < low - 0.15 and inside(o, x, y, z, margin=0.0):
                    under.add(nid)
        if not cut and not under:
            continue
        g = adopt(gid)
        before = [list(e) for e in g.edges]
        g.edges = [e for e in g.edges if _key(e) not in cut]
        legs = [(w, r) for w, _, routes in shipped_guards(gid) for r in routes] + plan_routes(gid)
        kept = set()
        for who, r in legs:
            for a, c in zip(r, r[1:]):
                if a == c or a not in pos or c not in pos or _reach(_adjacency(g.edges), a, c):
                    continue
                path = _shortest(before, pos, a, c) or []
                for u, v in zip(path, path[1:]):
                    k = (min(u, v), max(u, v))
                    if k in cut and k not in kept:
                        kept.add(k)
                        g.edges.append(next(e for e in before if _key(e) == k))
                        warnings.append("%s still walks %d -> %d through %s on graph %s - his route "
                                        "has no other way round it" % (who, u, v, cut[k], gid))
        ends = lambda edges: {x for e in edges for x in e[:2]}
        stranded = ends(before) - ends(g.edges)
        buried = []
        for nid in sorted(stranded | under):
            if not (nid in under or any(inside(o, *pos[nid]) for o, _ in SOLIDS)):
                continue
            if node_used(gid, nid):
                if nid in under:
                    warnings.append("node %d on graph %s is now under the floor of a building, but %s "
                                    "patrol%s through it" % (nid, gid, ", ".join(node_used(gid, nid)),
                                                              "s" if len(node_used(gid, nid)) > 1 else ""))
                continue
            g.remove_node(nid)
            buried.append(nid)
        by = collections.Counter(v for k, v in cut.items() if k not in kept)
        report.append("graph %s: %d link(s) that pass through walls cut%s%s" % (
            gid, len(cut) - len(kept),
            (" (%s)" % ", ".join("%s %d" % kv for kv in by.most_common())) if by else "",
            ("; node(s) %s left inside buildings removed" % buried) if buried else ""))

# Interiors: the template's nodes and links, then its doorways joined to the yard
TEMPLATE_IDS = {}               # interior key -> (gid, [node ids])


def graph_near(x, y, z, radius=40.0):
    """The graph with a node nearest to a building's ground floor, for it to join."""
    best = None
    for gid in origins:
        g = peek_graph(gid)
        for n in (g.nodes if g else []):
            w = node_world(gid, n)
            d = math.hypot(w[0] - x, w[1] - y) + 3 * abs(w[2] - z)
            if d <= radius and (best is None or d < best[0]):
                best = (d, gid)
    return best and best[1]


def own_nodes_of(o):
    """{gid: [(node id, world xyz)]} of the nodes already inside a level building."""
    out = {}
    for gid in origins:
        g = peek_graph(gid)
        for n in (g.nodes if g else []):
            w = node_world(gid, n)
            if inside(o, *w):
                out.setdefault(gid, []).append((n["id"], w))
    return out


for key, o, t, label in INTERIORS:
    floors, missing = FLOORS[key]
    merge = key in _world_by_ref
    tf = [f for f, _ in t["floors"]]
    own = own_nodes_of(o) if merge else {}
    # it joins the graph its existing nodes are on, else the one nearest its lowest new floor
    gid = max(own, key=lambda k: len(own[k])) if own else \
        str(o.get("graph") or graph_near(o["x"], o["y"], o["z"]) or "")
    if gid not in origins:
        warnings.append("%s: no navmesh within 40 m - it gets no floor nodes, and guards "
                        "inside it will stand at ground level" % label)
        continue
    g = peek_graph(gid)
    if g is None:
        warnings.append("%s: graph %s cannot be edited - no floor nodes added" % (label, gid))
        continue
    mine = own.get(gid, [])

    def floor_of(dz):
        near = [f for f in tf if abs(f - dz) <= 0.4]
        return min(near, key=lambda f: abs(f - dz)) if near else None

    # A template node on a floor the building already has nodes on is that
    # floor's nearest node; one on a new floor (or a stair up to it) is added.
    plan_ids = []
    for n in t["nodes"]:
        w = to_world(o, n[0], n[1], n[2])
        f = floor_of(n[2])
        reuse = None
        if f is not None and f not in missing:
            on_floor = [(math.dist(w[:2], q[1][:2]), q[0]) for q in mine if abs(q[1][2] - o["z"] - f) <= 0.45]
            if on_floor:
                reuse = min(on_floor)[1]
        if reuse is None:
            here = [(math.dist(w, q[1]), q[0]) for q in mine if math.dist(w, q[1]) <= 0.6]
            if here:
                reuse = min(here)[1]
        plan_ids.append(reuse)
    fresh = sum(1 for i in plan_ids if i is None)
    if not fresh:
        report.append("%s already has nodes on every floor - left as it is" % label)
        continue
    g = adopt(gid)
    try:
        g.grow(fresh)
    except GE.GraphError as e:
        errors.append("%s: %s" % (label, e))
        continue
    ids, new = [], set()
    for n, reuse in zip(t["nodes"], plan_ids):
        if reuse is not None:
            ids.append(reuse)
            continue
        nid = g.add_raw_node(to_world(o, n[0], n[1], n[2]), origin_of(gid), n[6],
                             like={"radius": n[4], "material": n[5]})
        g._node(nid)["gamma"] = (n[3] + (o.get("gamma") or 0.0)) % (2 * math.pi)
        ids.append(nid)
        new.add(nid)
    joined_own = set()
    for a, c, typ, cac, cca in t["edges"]:
        A, C = ids[a], ids[c]
        if A == C or (A not in new and C not in new):
            continue
        if any({e[0], e[1]} == {A, C} for e in g.edges):
            continue
        g.edges.append([A, C, typ])
        if A in new and C in new:
            if cac is not None:
                g.edge_cost[(A, C)] = cac
            if cca is not None:
                g.edge_cost[(C, A)] = cca
        else:
            joined_own.add(C if A in new else A)
    TEMPLATE_IDS[key] = (gid, ids)
    joined = set()
    exits = [k for k in t["exits"] if ids[k] in new]
    for k in exits:
        n = t["nodes"][k]
        w = to_world(o, n[0], n[1], n[2])
        ok = 0
        for d, nid, q_ in g.near_nodes(w, origin_of(gid), LINK_EXIT, exclude=set(ids)):
            start = w
            if not n[7] and d > DOOR_STEP:
                # an inside doorway node: its own door frame is not a wall
                f = DOOR_STEP / d
                start = tuple(w[i] + (q_[i] - w[i]) * f for i in range(3))
            if _surface is not None and _surface.blocked(start, q_):
                continue
            g.link(ids[k], nid)
            joined.add(nid)
            ok += 1
            if ok >= EXIT_LINKS:
                break
    added_floors = ", ".join("+%.1f m" % f for f in missing)
    report.append("%s: %d floor node(s) added to graph %s (%s)%s%s" % (
        label, len(new), gid, added_floors,
        ("; joined to its own nodes %s" % sorted(joined_own)) if joined_own else "",
        ("; doorways joined to %s" % sorted(joined)) if joined else ""))
    if not joined and not joined_own:
        if not t["exits"]:
            report.append("%s: like the shipped copy, those nodes have no way down - a guard up there stays there" % label)
        else:
            warnings.append("%s: no yard node within %.0f m of its doorways can be reached without "
                            "passing through a wall - guards inside can't walk out" % (label, LINK_EXIT))

# guards inside a building that got an interior belong to that graph
for s in soldiers:
    job = TEMPLATE_IDS.get(s.get("_interior"))
    if job and str(s.get("graph")) != job[0]:
        warnings.append("%s stands inside a building on graph %s - now on that graph (was %s)"
                        % (s.get("name"), job[0], s.get("graph")))
        s["graph"] = job[0]


def _link_ok(a, b):
    return _surface is None or _surface.blocked(a, b) is None


for pn in plan_nodes:
    gid = str(pn.get("graph"))
    if edit_graph(gid, "new node %s" % pn.get("uid")) is None:
        continue
    try:
        g = edited_graphs[gid]
        g.grow(1)
        nid, linked = g.add_node((pn["x"], pn["y"], pn["z"]), origin_of(gid),
                                 float(pn.get("link", 15.0)), link_ok=_link_ok)
        node_ids[pn.get("uid")] = nid
        pn["_id"], pn["_linked"] = nid, linked
    except GE.GraphError as e:
        errors.append("new node at %.1f, %.1f: %s" % (pn["x"], pn["y"], e))

_edited_tables = {gid: g.build_table() for gid, g in edited_graphs.items()}


def resolve_stop(n, gid=None):
    """A patrol stop is an existing node id, "n:<uid>" for a node this plan adds,
    or "t:<building>:<i>" for node i of an interior this plan adds."""
    if isinstance(n, str) and n.startswith("n:"):
        return node_ids.get(n[2:])
    if isinstance(n, str) and n.startswith("t:"):
        key, _, i = n[2:].rpartition(":")
        job = TEMPLATE_IDS.get(key)
        if not job or not i.isdigit() or int(i) >= len(job[1]):
            return None
        if gid is not None and str(gid) != job[0]:
            return None
        return job[1][int(i)]
    try:
        return int(n)
    except (TypeError, ValueError):
        return None


def route_exists(gid, a, c):
    g = edited_graphs.get(str(gid))
    if g is not None:
        off = (a * g.max_nodes + c) * 8
        t = _edited_tables[str(gid)]
        return off + 4 <= len(t) and struct.unpack_from("<i", t, off)[0] != -1
    return (a, c) not in routing(gid)[2]


def graph_ids(gid):
    g = edited_graphs.get(str(gid))
    if g is not None:
        return {n["id"] for n in g.nodes}, set(g.isolated())
    ids, iso, _ = routing(gid)
    return ids, iso


# Edits can cut a route a shipped guard depends on even when no patrol names
# the node itself - check every leg of every path of theirs on edited graphs.
for gid in list(edited_graphs):
    ids, _ = graph_ids(gid)
    for who, names, routes in shipped_guards(gid):
        for n in sorted(names - ids):
            errors.append("%s on graph %s uses node %d, which this plan removes" % (who, gid, n))
        for route in routes:
            for a, c in zip(route, route[1:]):
                if a != c and a in ids and c in ids and not route_exists(gid, a, c):
                    errors.append("the plan cuts %s's route %d -> %d on graph %s"
                                  % (who, a, c, gid))


# shipped guards whose route the plan rewrites are checked exactly like new ones
for s in soldiers + EDIT_SOLDIERS:
    gid = s.get("graph")
    raw_route = s.get("patrol") or []
    if not raw_route:
        continue
    if gid is None:
        errors.append("%s has a patrol but no graph" % s.get("name"))
        continue
    route = []
    for n in raw_route:
        r = resolve_stop(n, gid)
        if r is None:
            errors.append("%s: patrol stop %r is not a node on graph %s"
                          % (s.get("name"), n, gid))
        else:
            route.append(r)
    s["patrol"] = route          # resolved ids are what gets written
    ids, iso = graph_ids(gid)
    if not ids:
        warnings.append("no parsed navmesh for graph %s - patrol not verified" % gid)
        continue
    for n in route:
        if n not in ids:
            errors.append("%s walks to node %d, which does not exist on graph %s"
                          % (s.get("name"), n, gid))
        elif n in iso:
            errors.append("%s walks to node %d on graph %s, which is isolated - "
                          "nothing routes to or from it" % (s.get("name"), n, gid))
    for a, c in zip(route, route[1:]):
        if a != c and a in ids and c in ids and not route_exists(gid, a, c):
            errors.append("%s walks %d -> %d on graph %s: the graph's routing table "
                          "has no path between them" % (s.get("name"), a, c, gid))

# When the mission starts, a guard walks to his walkway graph. With no node near
# him at his own height he walks off to the nearest one there is - across the map,
# or up into the air where a building's floor used to be (an empty map keeps the
# graphs of the buildings it takes away). So every guard needs one where he stands.
GUARD_REACH = 30.0                  # metres he may walk to his walkways
GUARD_STEP = 2.5                    # the height difference a floor allows (SAME_FLOOR)


def nearest_node(gid, here):
    """(metres away, height difference, node) of the node of graph gid nearest this
    point on the ground, or None when the graph has none."""
    g = peek_graph(str(gid))
    if g is None or not g.nodes:
        return None
    best = None
    for n in g.nodes:
        w = node_world(str(gid), n)
        d = math.dist(here[:2], w[:2])
        if best is None or d < best[0]:
            best = (d, abs(w[2] - here[2]), n)
    return best


for s in soldiers + EDIT_SOLDIERS:
    if s.get("arriveOn") or s.get("x") is None:
        continue                    # one that arrives on an event is put there by the event
    here = (float(s["x"]), float(s["y"]), float(s["z"]))
    who = s.get("name") or "a guard"
    gid = str(s.get("graph") or "")
    near = nearest_node(gid, here) if gid else None
    if not gid or near is None:
        # no graph of its own (or an empty one): the nearest graph with a node on
        # his floor, rather than whichever the level lists first
        best = None
        for other in origins:
            n = nearest_node(other, here)
            if n and n[1] <= GUARD_STEP and (best is None or n[0] < best[1][0]):
                best = (other, n)
        if best is None:
            errors.append("%s has no walkways near him: the game walks him to his graph when the "
                          "mission starts, and there is none he can stand on. Lay walkways where he "
                          "stands (the studio's Walkways tool, or add_walkways)." % who)
            continue
        gid, near = best[0], best[1]
        s["graph"] = gid
        warnings.append("%s had no walkways of his own - given graph %s, %.0f m away" % (who, gid, near[0]))
    if near[1] > GUARD_STEP:
        errors.append("%s stands %.1f m below or above his walkways (graph %s, the nearest point is "
                      "%.0f m away): in the game he walks to them and ends up in the air. Lay walkways "
                      "where he stands, or put him where they are." % (who, near[1], gid, near[0]))
    elif near[0] > GUARD_REACH:
        warnings.append("%s stands %.0f m from his walkways (graph %s): in the game he walks off to "
                        "them when the mission starts" % (who, near[0], gid))

if errors:
    print("PLAN REJECTED - %d problem(s):" % len(errors))
    for e in errors:
        print("   x " + e)
    sys.exit(1)

# ---------------------------------------------------------------- guard reactions
# Level 1's barracks guards are tied to the base alarm (SetAlarmControlID) and,
# on AIEVENT_ALARMON, run a patrol path out of the barracks along the navmesh -
# through the door ("Runs to node id 20"). A guard whose script is nothing but
# AIFunction_DefaultHandler reacts to gunfire by moving straight at it, and
# guards pass through walls. So every guard this plan (or an earlier Apply)
# creates gets the shipped pattern: the alarm control of the level's guards
# around him, and, standing inside a building, an alarm path that runs him out.
_script_dirs = [qvm_source.level_ai(LV, GAME)]


def script_text(aid):
    for d in _script_dirs:
        f = d / ("%d.qsc" % aid)
        if f.exists():
            return f.read_text(encoding="latin1")
    return None


_soldier_ai = {}                # soldier task id -> (HumanAI id, graph id)
_starts = [m for m in re.finditer(r'Task_New\((\d+), "HumanSoldier", ', src)]
for i, m in enumerate(_starts):
    end = _starts[i + 1].start() if i + 1 < len(_starts) else len(src)
    am = re.search(r'Task_New\((\d+), "HumanAI", "", "[A-Z_0-9]+", (\d+)\)', src[m.end():end])
    if am:
        _soldier_ai[int(m.group(1))] = (int(am.group(1)), am.group(2))

_controls = []                  # (x, y, alarm control id) of the level's own guards
for o in WORLD:
    if o.get("type") == "soldier" and id(o) not in ADDED and o.get("id") in _soldier_ai:
        c = re.search(r"SetAlarmControlID\((\d+)\)", script_text(_soldier_ai[o["id"]][0]) or "")
        if c:
            _controls.append((o["x"], o["y"], int(c.group(1))))


def alarm_control_near(x, y, reach=80.0):
    near = [(math.hypot(cx - x, cy - y), c) for cx, cy, c in _controls]
    near = [p for p in near if p[0] <= reach]
    return min(near)[1] if near else None


def is_tower(o):
    return "TOWER" in ("%s %s" % (o.get("modelName") or "", o.get("name") or "")).upper()


def container_of(x, y, z):
    """The smallest building a point is inside - not a crate or a desk."""
    best, area = None, 1e18
    for o in list(objects) + WORLD:
        sz = _sizes.get(o.get("model")) or {}
        if o.get("cutscene") or not sz.get("body") or sz.get("h", 0) < 2.2:
            continue
        if o.get("type") != "building" and not template_for(o.get("model")):
            continue
        if inside(o, x, y, z, margin=0.0) and sz["w"] * sz["d"] < area:
            best, area = o, sz["w"] * sz["d"]
    return best


def exit_node(gid, x, y, z):
    """[node inside, first node outside] of the building a guard stands in, along
    the navmesh - where his alarm path runs him. He goes to a node in his own room
    first: the nearest node may be the doorstep outside, and walking straight to it
    is walking through the wall. None outdoors, and on a tower (a guard up there
    stays up there, like the shipped ones)."""
    b = container_of(x, y, z)
    gid = str(gid)
    if b is None or is_tower(b) or gid not in origins:
        return None
    g = peek_graph(gid)
    if g is None:
        return None
    pos = {n["id"]: node_world(gid, n) for n in g.nodes}
    start = [(math.dist(p_, (x, y, z)), i) for i, p_ in pos.items()
             if abs(p_[2] - z) <= 1.5 and inside(b, *p_, margin=0.0)]
    if not start:
        return None
    start = min(start)[1]
    adj = g.adjacency()
    others = [o for o in list(objects) + WORLD if o is not b and (_sizes.get(o.get("model")) or {}).get("body")
              and (o.get("type") == "building" or template_for(o.get("model")))]
    best, heap, done = {start: 0.0}, [(0.0, start)], set()
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        p_ = pos[u]
        if not inside(b, *p_, margin=2.0) and not any(inside(o, *p_, margin=0.0) for o in others):
            return [start, u]
        for v, w in adj.get(u, []):
            if v in pos and d + w < best.get(v, 1e30):
                best[v] = d + w
                heapq.heappush(heap, (d + w, v))
    return None


def alarm_path_task(pid, nodes):
    runs = "".join('Task_New(-1, "PatrolPathCommand", "Runs to node id %d", 3, %d), ' % (n, n) + EOL
                   for n in nodes)
    return ('Task_New(%d, "PatrolPath", "", ' % pid + EOL + runs +
            'Task_New(-1, "PatrolPathCommand", "End script, only runs commands after this one. '
            'Takes no paramet", 6, 0))')


reactions = []                  # report lines

# ---------------------------------------------------------------- emit tasks
def q(v):
    return "%d.0" % int(round(v * SCALE))


def _qstr_early(text, limit=60):
    """A name safe to put in a task, before the objective helpers exist."""
    return re.sub(r'["\
]', " ", str(text or ""))[:limit]


blocks, ai_scripts = [], {}

# The skeleton a soldier model is built on (HumanSoldier "Bone Heirachy"): 1 for
# every guard model, 6 for Anya and Ekk - as every shipped level places them.
BONES = {"015_01_1": 6, "012_01_1": 6}

# ---------------------------------------------------------------- events
# plan["events"]: when something happens, do something. Each event is a latch,
# an EditVariable that goes to 1 the first time its condition holds and stays
# there, so it happens once (an area walked out of does not un-happen). What it
# does hangs off the latch: a message, an alarm, guards arriving, the mission
# failing. The latch ids are taken first: guards placed below name the event
# they arrive on.
EVENTS = [e for e in (plan.get("events") or []) if isinstance(e, dict) and e.get("uid") and isinstance(e.get("when"), dict)]
EVENT_VAR = {e["uid"]: take_id() for e in EVENTS}
EVENT_BY = {e["uid"]: e for e in EVENTS}
EVENT_FAILS = []                # LevelFlow failure terms
ANCHOR_NEW = []                 # (ref, id) shipped tasks given an id (a map marker, a door's lock)


def event_fired(uid):
    v = EVENT_VAR.get(uid)
    return ("EditVariable_%d.nValue == 1" % v) if v else None


def event_name(uid):
    e = EVENT_BY.get(uid) or {}
    return e.get("name") or "event %d" % (EVENTS.index(e) + 1 if e in EVENTS else 0)


# placed things an objective or an event points at need a task id the game can test
_target_uids = {(o.get("target") or {}).get("uid") for o in (plan.get("objectives") or []) if isinstance(o, dict)}
_target_uids |= {(e["when"].get("target") or {}).get("uid") for e in EVENTS}

for s in soldiers:
    tid, aid, pid = take_id(), take_id(), take_id()
    s["_tid"] = tid
    route = s.get("patrol") or []
    model = s.get("model") or "003_01_1"
    weapon = s.get("weapon") or "WEAPON_ID_AK47"
    ai = s.get("ai") or "AITYPE_GUARD_AK"
    gid = s.get("graph") or next(iter(meta.get("graphs") or {"4019": 0}), "4019")
    head = ('Task_New(%d, "HumanSoldier", "%s", %s, %s, %s, %s, "%s", %d, %d, -1, '
            % (tid, s.get("name", "Guard"), q(s["x"]), q(s["y"]), q(s["z"]),
               round(s.get("gamma", 3.14159), 5), model, int(s.get("team", 1)), BONES.get(model, 1)))
    kids = ['Task_New(-1, "Gun", "", "%s", 0)' % weapon,
            'Task_New(%d, "HumanAI", "", "%s", %s)' % (aid, ai, gid)]
    if route:
        cmds = []
        for n in route:
            cmds.append('Task_New(-1, "PatrolPathCommand", "Walks to node id %d", 2, %d)' % (n, n))
            cmds.append('Task_New(-1, "PatrolPathCommand", "Delays the script execution for 200 ticks", 1, 200)')
        cmds.append('Task_New(-1, "PatrolPathCommand", "Quit script, stops script. Takes no parameters", 7, 0)')
        kids.append('Task_New(%d, "PatrolPath", "", ' % pid + EOL + (", " + EOL).join(cmds) + ")")
    s["_aid"] = aid
    out_node = exit_node(gid, s["x"], s["y"], s["z"])
    apid = take_id() if out_node is not None else None
    if apid:
        kids.append(alarm_path_task(apid, out_node))
        reactions.append("%s runs out on the alarm: node %d, then %d" % ((s.get("name") or "guard",) + tuple(out_node)))
    ai_scripts[aid] = {"idle": pid if route else None, "alarm": apid,
                       "control": alarm_ctl_id(s.get("alarmId")) or alarm_control_near(s["x"], s["y"]),
                       "sees": s.get("sees"), "fov": s.get("fov")}
    task = head + EOL + (", " + EOL).join(kids) + ")"
    ring = alarm_expr_of(s.get("alarmId")) if s.get("reinforce") else None
    if s.get("reinforce") and not ring:
        warnings.append("%s is a reinforcement with no alarm to call him - he starts on the map instead"
                        % (s.get("name") or "guard"))
    arrive = event_fired(s.get("arriveOn")) if s.get("arriveOn") else None
    if s.get("arriveOn") and not arrive:
        warnings.append("%s arrives on an event that is no longer in the mission - he starts on the map instead"
                        % (s.get("name") or "guard"))
    if arrive:
        # not on the map until the event happens; back so many times after he dies
        times = max(1, min(20, int(s.get("arriveTimes") or 1)))
        blocks.append('Task_New(%d, "GuardGenerator", "%s", "%s", %d, %s), %s'
                      % (take_id(), _qstr_early((s.get("name") or "Guard") + " arrives", 40), arrive, times, task, EOL))
        reactions.append("%s arrives when %s happens, %d time(s)" % (s.get("name") or "a guard", event_name(s["arriveOn"]), times))
    elif ring:
        # he is not on the map until the alarm rings, and comes back so many times
        blocks.append('Task_New(%d, "GuardGenerator", "%s", "%s", %d, %s), %s'
                      % (take_id(), _qstr_early((s.get("name") or "Reinforcement") + " on the alarm", 40), ring,
                         max(1, min(20, int(s.get("reinforce") or 1))), task, EOL))
        reactions.append("%s comes when %s rings, up to %d time(s)"
                         % (s.get("name") or "a guard", s.get("alarmId"), max(1, min(20, int(s.get("reinforce") or 1)))))
    else:
        blocks.append(task + ", " + EOL)

AMMO_DEFAULT = {"AMMO_ID_919": 32, "AMMO_ID_556": 60, "AMMO_ID_762": 20, "AMMO_ID_DRAGUNOV": 20,
                "AMMO_ID_12": 16, "AMMO_ID_44": 14, "AMMO_ID_357": 12, "AMMO_ID_127": 100,
                "AMMO_ID_M203": 4, "AMMO_ID_GRENADE": 2, "AMMO_ID_FLASHBANG": 2,
                "AMMO_ID_PROXIMITYMINE": 2, "AMMO_ID_MEDIPACK": 1}
# Plans from 2026-09-18 on turn a lying weapon the way everything else turns:
# a larger heading is further anticlockwise. On its side the heading is alpha,
# and a larger alpha swings the barrel clockwise, so alpha is minus the heading.
# Older plans stored alpha itself (missions.py converts them when they load).
CCW_LYING = bool(plan.get("ccwLying"))


def pickup_pose(item, facing):
    """(alpha, beta, gamma) of a pickup at rest. Shipped weapons and items lying on a
    table, a crate or a bed are turned onto their side: beta 1.57, heading in alpha
    (a Dragunov with 0, 0, gamma stands on its end, half through the desk). Grenades
    and ammo boxes sit flat as they are; mines lie with alpha a quarter turn."""
    if item.startswith("AMMO_ID_") or item == "WEAPON_ID_GRENADE":
        return 0.0, 0.0, facing
    if item == "WEAPON_ID_PROXIMITYMINE":
        return 1.5708, 0.0, facing
    if CCW_LYING:
        return round((-facing) % (2 * math.pi), 6), 1.5708, 0.0
    return facing, 1.5708, 0.0


for p in pickups:
    pid_ = p.get("pickupId") or "WEAPON_ID_AK47"
    if pid_.startswith("AMMO_ID_"):
        # AmmoPickup: Position, Orientation, ID, Ammo (count)
        blocks.append('Task_New(-1, "AmmoPickup", "%s", %s, %s, %s, 0, 0, %s, "%s", %d), %s'
                      % (p.get("name", "Ammo"), q(p["x"]), q(p["y"]), q(p["z"]),
                         round(p.get("gamma", 0) or 0, 5), pid_,
                         int(p.get("count") or AMMO_DEFAULT.get(pid_, 10)), EOL))
    else:
        pa, pb, pg = pickup_pose(pid_, round(p.get("gamma", 0) or 0, 5))
        pk_id = take_id() if p.get("uid") in _target_uids else -1
        if pk_id >= 0:
            p["_tid"] = pk_id
        blocks.append('Task_New(%d, "GunPickup", "%s", %s, %s, %s, %s, %s, %s, "%s"), %s'
                      % (pk_id, p.get("name", "Pickup"), q(p["x"]), q(p["y"]), q(p["z"]),
                         pa, pb, pg, pid_, EOL))

OWN_GATES = []                  # gate leaves and doors of yours: Door tasks
OWN_LIFTS = []                  # lifts of yours: an Elevator, its path and its switches
for o in objects:
    if isinstance(o.get("door"), dict):
        o["_tid"] = take_id()
        OWN_GATES.append(o)
        continue
    if isinstance(o.get("lift"), dict):
        _d0 = o["lift"]
        o["_spline"], o["_tid"] = take_id(), take_id()
        o["_cabin_sw"] = take_id() if _d0.get("inside") else -1
        o["_calls"] = [take_id() for _ in (_d0.get("calls") or [])[:len(_d0.get("stops") or [])]]
        OWN_LIFTS.append(o)
        continue
    # a building with a map computer label needs a task id for the label to point at
    ob_id = take_id() if isinstance(o.get("label"), dict) and (o["label"].get("title") or "").strip() else -1
    if ob_id >= 0:
        o["_tid"] = ob_id
    blocks.append('Task_New(%d, "EditRigidObj", "%s", %s, %s, %s, 0, 0, %s, "%s", 1, 1, 1, 0, 0, 0), %s'
                  % (ob_id, o.get("name", "Object"), q(o["x"]), q(o["y"]), q(o["z"]),
                     round(o.get("gamma", 0), 5), o.get("model") or "219_01_1", EOL))

# ---------------------------------------------------------------- cameras
# SCamera: holder position and heading, holder model, camera tilt and pan, the
# camera and its wreck, how far it sweeps right and left (degrees), how fast
# (degrees a second) and how long it waits at each end, the view cone's height
# and width (degrees) and length (metres), and when it is on. Seeing you does
# nothing by itself: the level's alarm has to listen, so each camera that
# raises the alarm is added to the nearest camera control or alarm (at splice).
def _int(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _real(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def cam_params(c):
    """An SCamera's settings after the holder model, up to its On expression."""
    return ('%s, %s, "313_02_1", "313_03_1", %d, %d, %d, %s, %d, %d, %s'
            % (repr(round(_real(c.get("pitch"), -1.5, 0.6, -0.15), 5)), repr(round(_real(c.get("pan"), -3.2, 3.2, 0.0), 5)),
               _int(c.get("right"), 0, 180, 0), _int(c.get("left"), 0, 180, 0), _int(c.get("speed"), 0, 180, 0),
               repr(round(_real(c.get("delay"), 0, 60, 0.0), 2)), _int(c.get("fovV"), 10, 180, 90),
               _int(c.get("fov"), 10, 180, 60), repr(round(_real(c.get("range"), 1, 200, 30.0), 2))))


CAM_LINKS = []                  # (task id, x, y) of cameras that raise the alarm
CAM_ALARM = None                # an alarm made for them when the level has none
def cam_on(c):
    """When a new camera is on: like the level's nearest camera, so a terminal or
    generator that shuts the base's cameras down shuts this one down too."""
    near = [(math.hypot(o["x"] - c["x"], o["y"] - c["y"]), (o.get("cam") or {}).get("on") or "1")
            for o in WORLD if o.get("type") == "camera" and id(o) not in ADDED]
    near = [n for n in near if n[0] <= 80.0]
    on = min(near)[1] if near else "1"
    return on if '"' not in on else "1"


for c in cameras:
    cid = take_id()
    c["_tid"] = cid
    on = cam_on(c)
    blocks.append('Task_New(%d, "SCamera", "%s", %s, %s, %s, %s, "313_01_1", %s, "%s"), %s'
                  % (cid, re.sub(r'["\\\r\n]', " ", str(c.get("name") or "Camera"))[:60], q(c["x"]), q(c["y"]), q(c["z"]),
                     repr(round(float(c.get("gamma") or 0), 5)), cam_params(c.get("cam") or {}), on, EOL))
    if on != "1":
        report.append("camera %s is on while: %s" % (c.get("name") or cid, on.replace("\\n", " ")))
    if c.get("alarm", True) and not c.get("alarmId"):
        CAM_LINKS.append((cid, c["x"], c["y"]))
if CAM_LINKS and not re.search(r'Task_New\(\d+, "AlarmControl"', src):
    CAM_ALARM = take_id()
    blocks.append('Task_New(%d, "AlarmControl", "Camera alarm", 0, 0, 0, 0, 0, 0, "", "", 1, 0.5, 0.5, 1, 0, 5, 4, "", '
                  '"explo_02_m", "", 4.0, "!AlarmControl_%d.isAlarm && (%s)"), %s'
                  % (CAM_ALARM, CAM_ALARM, " || ".join("SCamera_%d.isDetection" % t for t, _, _ in CAM_LINKS), EOL))
    CAM_LINKS = []
    warnings.append("this level has no alarm: the cameras got one of their own, which no guard answers")
if cameras:
    report.append("cameras: %d placed, %d raise the alarm" % (len(cameras), sum(1 for c in cameras if c.get("alarm", True))))

# ---------------------------------------------------------------- alarms
# An alarm system is one AlarmControl and everything that names it by task id.
# The plan's parts carry alarmId - "lv:<task id>" for one the level ships, or
# "own:<uid>" for one of the mission's. A system of the mission's own is written
# the way the shipped ones are: the control holds the trigger, an EditVariable
# holds the alarm on until a button is pressed again.
for c in cameras:
    if c.get("alarm", True) and c.get("alarmId"):
        ALARM_TRIGGER.setdefault(c["alarmId"], []).append("SCamera_%d.isDetection" % c["_tid"])

# A camera or button the level ships, put on another system (or on none): it is
# taken out of every trigger at splice and added to the one the mission chose.
MOVED_PARTS = []                # expressions to clear before the new ones go in
TERM_OF = {"camera": "SCamera_%d.isDetection", "switch": "Switch_%d.isLastPressed"}
for _e in EDITS:
    if _e.get("type") not in TERM_OF or "alarmId" not in _e:
        continue
    _o = _world_by_ref.get(_e["ref"]) or {}
    if _o.get("id", -1) < 0:
        continue
    _term = TERM_OF[_e["type"]] % _o["id"]
    MOVED_PARTS.append(_term)
    if _e.get("alarmId"):
        ALARM_TRIGGER.setdefault(_e["alarmId"], []).append(_term)
        if _e["type"] == "switch":
            ALARM_SILENCE.setdefault(_e["alarmId"], []).append(_term)

for kit in alarm_kit:
    if kit["type"] == "alarmctl":
        continue
    key = kit.get("alarmId")
    on = alarm_expr_of(key)
    g = round(float(kit.get("gamma") or 0), 5)
    if kit["type"] == "switch" and kit.get("gate"):
        # a gate's switch: the gate panel, as level 10 opens its gate with one
        sid = take_id()
        kit["_tid"] = sid
        blocks.append('Task_New(%d, "Switch", "%s", %s, %s, %s, 0, 0, %s, "1", TRUE, '
                      '"202_01_1", "202_01_1", "202_01_1", "202_01_1", "202_01_1", FALSE), %s'
                      % (sid, _qstr_early(kit.get("name") or "Gate switch", 40), q(kit["x"]), q(kit["y"]), q(kit["z"]), g, EOL))
        continue
    if kit["type"] == "switch":
        sid = take_id()
        kit["_tid"] = sid
        blocks.append('Task_New(%d, "Switch", "%s", %s, %s, %s, 0, 0, %s, "1", FALSE, '
                      '"234_01_1", "234_01_1", "234_01_1", "234_01_1", "234_01_1", FALSE), %s'
                      % (sid, _qstr_early(kit.get("name") or "Alarm button", 40), q(kit["x"]), q(kit["y"]), q(kit["z"]), g, EOL))
        if key:
            ALARM_TRIGGER.setdefault(key, []).append("Switch_%d.isLastPressed" % sid)
            ALARM_SILENCE.setdefault(key, []).append("Switch_%d.isLastPressed" % sid)
    elif kit["type"] == "siren":
        blocks.append('Task_New(-1, "Siren", "%s", %s, %s, %s, 0, 0, %s, "310_01_1", "", 1, 0.5, 0.5, 1, 0, 5, 4, "", '
                      '"explosion_1", "alarmsystem_working", "alarmsystem_working", "%s"), %s'
                      % (_qstr_early(kit.get("name") or "Siren", 40), q(kit["x"]), q(kit["y"]), q(kit["z"]), g, on or "0", EOL))
    elif kit["type"] == "alarmlight":
        blocks.append('Task_New(-1, "AlarmLight", "%s", %s, %s, %s, 0, 0, %s, "%s", "344_03_1", "344_01_1", "", "", ""), %s'
                      % (_qstr_early(kit.get("name") or "Alarm light", 40), q(kit["x"]), q(kit["y"]), q(kit["z"]), g, on or "0", EOL))
    if key and alarm_ctl_id(key) is None:
        warnings.append("%s is on an alarm system that is no longer in the mission" % (kit.get("name") or kit["type"]))

# ---------------------------------------------------------------- doors of yours
# A door of yours is written the way the game writes its own (studio/extract/
# doors.py reads them out of the levels): position, the stop it slides to in its
# own frame, the slider, its three angles, its model, max angle, open time,
# whether it can be picked and for how long, then the locked, open and close
# expressions and its three sounds. A plain door has no locked expression and
# the game's own close expression, so the player opens it by walking up to it
# and the "open" prompt comes; a gate leaf (304, as level 10 writes its two
# leaves sliding apart) is locked and opens while its switch is pressed.
DOOR_DEFAULTS = {}
_kits = {}                      # what each building of the game's comes with (doors.json "buildings")
try:
    _doors_json = json.loads((paths.data() / "doors.json").read_text(encoding="utf-8"))
    DOOR_DEFAULTS = _doors_json.get("models") or {}
    _kits = _doors_json.get("buildings") or {}
except (OSError, ValueError):
    pass


def _kit_leaf(o):
    """This door as its building's kit has it, when it came with one: the leaf
    in the same doorway, facing the same way. How far and which way a leaf
    slides belongs to its doorway, not its model - Eagle's Nest's lift doorway
    slides its outer leaves -0.6 and its inner +1.3, where those models most
    often go +0.4 and +0.9 - and doors placed before the kits kept it carry the
    model's instead."""
    sl, home = o.get("slot"), _by_uid.get(o.get("of")) if o.get("of") else None
    if not (isinstance(sl, dict) and home):
        return None
    for d in (_kits.get(home.get("model")) or {}).get("doors") or []:
        if d.get("model") != o.get("model") or not d.get("stop"):
            continue
        if all(abs(float(d[k]) - float(sl.get(k, 1e9))) < 0.05 for k in ("dx", "dy", "dz")) and \
                abs((float(d["dh"]) - float(sl.get("dh", 0)) + math.pi) % (2 * math.pi) - math.pi) < 0.05:
            return d
    return None
GATE_OPEN_S = 12                # a gate of yours stands open this long after its switch
GATE_SOUNDS = ["gate_loop_e", "gate_loop_e", "gate_loop"]
DOOR_SOUNDS = ["door_open_1", "door_close_1", "door_slide_1"]
# a door of ours never carries another level's wiring: an expression naming a
# task by id ("Switch_211.isLastPressed") is dropped for the plain timed close
NAMES_TASK = re.compile(r"(?:Switch|Door|Generator|Elevator|EditVariable|CutScene|Terminal)_\d+\.")
TIMED_CLOSE = "this.nDoorOpenTicks > 6*GAME_FREQUENCY"


CABIN_FLOOR = {}                # cabin model -> how far its floor is below its origin


def _cabin_drop(model):
    """A lift cabin's origin stands this far above its floor (models.json z0)."""
    if model not in CABIN_FLOOR:
        try:
            z0 = (json.loads((paths.data() / "models.json").read_text(encoding="utf-8"))["sizes"]
                  .get(model) or {}).get("z0") or 0.0
        except (OSError, ValueError, KeyError):
            z0 = 0.0
        CABIN_FLOOR[model] = -float(z0)
    return CABIN_FLOOR[model]


def _lift_of_door(o):
    """(the lift this door is part of, which floor of it) - only a door the game
    itself wires to a lift ("liftFloor": it opens when the cabin is at that
    floor, and is locked otherwise). An ordinary door beside a shaft stays the
    player's to open."""
    floor = (o.get("door") or {}).get("liftFloor")
    if floor is None:
        return None, None
    near = None
    for L in OWN_LIFTS:
        d = math.dist((float(o["x"]), float(o["y"])), (float(L["x"]), float(L["y"])))
        if d <= 12.0 and (near is None or d < near[1]):
            near = (L, d)
    if near is None:
        return None, None
    stops = near[0]["lift"].get("stops") or []
    if not stops:
        return None, None
    # The floor it opens at is the one at its own height. The number the game
    # wires it with counts the floors of the copy the door was read from, and
    # copies run their lift's path either way: Eagle's Nest's lift building has
    # one counting from the bottom and one from the top, so a door taken from one
    # and a lift from the other opened at the top while the cabin stood below.
    L, z = near[0], float(o.get("z") or 0)
    return L, min(range(len(stops)), key=lambda k: abs(float(L["z"]) + float(stops[k][2]) - z))


def _door_angles(head, fixed, heading):
    """The three angles of a door of this model, turned to face `heading`."""
    f = list(fixed or [0, 0])
    while len(f) < 2:
        f.append(0)
    if head == 0:                       # it lies on its side: alpha carries the heading
        return (-heading, f[0], f[1])
    return (f[0], f[1], heading)


for _g in OWN_GATES:
    _d = _g["door"]
    _kl = _kit_leaf(_g)
    if _kl:
        _d = dict(_d, stop=_kl["stop"], slider=_kl.get("slider", _d.get("slider")))
    _dm = DOOR_DEFAULTS.get(_g.get("model") or "") or {}
    _kind = _d.get("kind") or "gate"
    _sw = next((k for k in alarm_kit if k.get("uid") == _d.get("switch") and "_tid" in k), None)
    if _kind == "gate":
        # the switch stays pressed while the gate is open, and pressing it again
        # lets it go: the leaves follow it both ways
        _open = "Switch_%d.isPressed" % _sw["_tid"] if _sw else "0"
        _close = "this.nDoorOpenTicks > %d*GAME_FREQUENCY" % GATE_OPEN_S
        _locked = ""
        _sounds = _d.get("sounds") or _dm.get("sounds") or GATE_SOUNDS
        if not _sw:
            warnings.append("%s has no switch to open it - it stays shut" % (_g.get("name") or "a gate"))
    else:
        _lift, _floor = _lift_of_door(_g)
        if _lift is not None:
            # a lift's own door: the lift works it, as the game's lift doors are
            _locked = "1"
            _open = "Elevator_%d.vFloor == %d" % (_lift["_tid"], _floor)
            _buttons = list(_lift["_calls"]) + ([_lift["_cabin_sw"]] if _lift["_cabin_sw"] >= 0 else [])
            _close = " || ".join("Switch_%d.isLastPressed" % b for b in _buttons)
            _sounds = _d.get("sounds") or _dm.get("sounds") or DOOR_SOUNDS
            _stop = _d.get("stop") or _dm.get("stop") or [0, 0]
            _slider = _d.get("slider", _dm.get("slider", 0))
            _a, _b, _c = _door_angles(_d.get("head", _dm.get("head", 2)), _d.get("fixed", _dm.get("fixed")),
                                      float(_g.get("gamma") or 0))
            _open_t = _d.get("openTime", _dm.get("openTime", 2.0))
            _pick_t = _d.get("pickTime", _dm.get("pickTime", 4.0))
            _max_a = _d.get("maxAngle", _dm.get("maxAngle", 0))
            _snd = (list(_sounds) + ["", "", ""])[:3]
            _lift_doors = _lift.setdefault("_doors", [])
            _lift_doors.append(_g["_tid"])
            blocks.append('Task_New(%d, "Door", "%s", %s, %s, %s, %s, %s, %s, %s, %s, %s, "%s", %s, %s, FALSE, %s, "%s", "%s", "%s", '
                          '"%s", "%s", "%s"), %s'
                          % (_g["_tid"], _qstr_early(_g.get("name") or "Lift door", 40),
                             q(_g["x"]), q(_g["y"]), q(_g["z"]),
                             repr(round(float(_stop[0]), 3)), repr(round(float(_stop[1]), 3)), repr(round(float(_slider), 3)),
                             repr(round(_a, 5)), repr(round(_b, 5)), repr(round(_c, 5)),
                             _g.get("model") or "505_01_1", repr(round(float(_max_a), 3)), repr(round(float(_open_t), 3)),
                             repr(round(float(_pick_t), 3)), _locked, _open, _close,
                             _snd[0], _snd[1], _snd[2], EOL))
            continue
        # a door: the player opens it, unless a switch of yours does
        _open = "Switch_%d.isLastPressed" % _sw["_tid"] if _sw else ""
        _locked = "1" if (_sw or _d.get("locked")) else ""
        if _d.get("locked") and _d["locked"] != "1":
            _locked = str(_d["locked"])
        _close = "" if _sw else (_d.get("close") or _dm.get("close") or TIMED_CLOSE)
        if NAMES_TASK.search(_close):
            _close = TIMED_CLOSE            # a plan made before this was noticed
        _sounds = _d.get("sounds") or _dm.get("sounds") or DOOR_SOUNDS
    _stop = _d.get("stop") or _dm.get("stop") or [0, 0]
    _slider = _d.get("slider", _dm.get("slider", 0))
    _a, _b, _c = _door_angles(_d.get("head", _dm.get("head", 2)), _d.get("fixed", _dm.get("fixed")),
                              float(_g.get("gamma") or 0))
    _open_t = _d.get("openTime", _dm.get("openTime", 2.0))
    _pick_t = _d.get("pickTime", _dm.get("pickTime", 4.0))
    _max_a = _d.get("maxAngle", _dm.get("maxAngle", 0))
    _snd = (list(_sounds) + ["", "", ""])[:3]
    blocks.append('Task_New(%d, "Door", "%s", %s, %s, %s, %s, %s, %s, %s, %s, %s, "%s", %s, %s, FALSE, %s, "%s", "%s", "%s", '
                  '"%s", "%s", "%s"), %s'
                  % (_g["_tid"], _qstr_early(_g.get("name") or ("Gate" if _kind == "gate" else "Door"), 40),
                     q(_g["x"]), q(_g["y"]), q(_g["z"]),
                     repr(round(float(_stop[0]), 3)), repr(round(float(_stop[1]), 3)), repr(round(float(_slider), 3)),
                     repr(round(_a, 5)), repr(round(_b, 5)), repr(round(_c, 5)),
                     _g.get("model") or "304_01_1", repr(round(float(_max_a), 3)), repr(round(float(_open_t), 3)),
                     repr(round(float(_pick_t), 3)), _locked, _open, _close.replace('"', "'"),
                     _snd[0], _snd[1], _snd[2], EOL))
_n_gates = sum(1 for _g in OWN_GATES if (_g["door"].get("kind") or "gate") == "gate")
if _n_gates:
    report.append("%d gate leaf(s) of yours, opened by their switch" % _n_gates)
if len(OWN_GATES) - _n_gates:
    report.append("%d door(s) of yours that open in the game" % (len(OWN_GATES) - _n_gates))

# ---------------------------------------------------------------- lifts of yours
# A lift as the game writes its own (level 12's Guard HQ, level 13, level 5):
# a SplineObj whose waypoints are the floors it stops at, an "Elevator" task on
# it with the cabin's model and its speed, a call switch at each floor, and one
# more inside the cabin, written into the Elevator itself. "Go to floor k"
# happens when that floor's call switch is pressed, or when the cabin is at
# another floor and the button inside it is pressed.
SPLINE_WP = 'Task_New(-1, "SplineObjWaypoint", "", 0, 0, 6.283181190490723, %s, %s, %s, "", "", 20, FALSE, FALSE, FALSE)'
LIFT_SWITCH = 'Task_New(%d, "Switch", "%s", %s, %s, %s, 0, 0, %s, "1", FALSE, "%s", "%s", "%s", "%s", "%s", FALSE)'
LIFT_BUTTON = "202_01_1"


def _lift_at(o, p):
    """A point of a lift, given in the lift's own frame, in game units."""
    g = float(o.get("gamma") or 0)
    c, sn = math.cos(g), math.sin(g)
    return (q(float(o["x"]) + p[0] * c - p[1] * sn), q(float(o["y"]) + p[0] * sn + p[1] * c),
            q(float(o["z"]) + p[2]))


for _L in OWN_LIFTS:
    _d = _L["lift"]
    _stops = [list(map(float, st))[:3] for st in (_d.get("stops") or [])]
    if len(_stops) < 2:
        warnings.append("%s has fewer than two floors - left out" % (_L.get("name") or "a lift"))
        continue
    _calls = [c for c in (_d.get("calls") or [])][:len(_stops)]
    _sp_id, _lift_id = _L["_spline"], _L["_tid"]
    _cab_id = _L["_cabin_sw"]
    _call_ids = list(_L["_calls"])[:len(_calls)]
    _g = repr(round(float(_L.get("gamma") or 0), 5))
    # the path the cabin runs on
    _wps = ", ".join(SPLINE_WP % _lift_at(_L, st) for st in _stops)
    blocks.append('Task_New(%d, "SplineObj", "", FALSE, FALSE, FALSE, FALSE, 20, 0, 0, 0, 0, %s, 1, 1, 1, 0, 0, 0, %s), %s'
                  % (_sp_id, _g, _wps, EOL))
    # a call button at each floor
    for _i, (_c, _cid) in enumerate(zip(_calls, _call_ids)):
        _x, _y, _z = _lift_at(_L, _c)
        blocks.append(LIFT_SWITCH % ((_cid, _qstr_early("Lift button", 40), _x, _y, _z,
                                      repr(round(float(_L.get("gamma") or 0) + float(_c[3] if len(_c) > 3 else 0), 5)))
                                     + (LIFT_BUTTON,) * 5) + ", %s" % EOL)
    # which floor each call button belongs to: the one it stands nearest
    _floor_of = {}
    for _i, _c in enumerate(_calls):
        _k = min(range(len(_stops)), key=lambda k: abs(_stops[k][2] - _c[2]))
        _floor_of.setdefault(_k, _call_ids[_i])
    _go = []
    for _k in range(len(_stops)):
        _parts = []
        if _floor_of.get(_k) is not None:
            _parts.append("Switch_%d.isLastPressed" % _floor_of[_k])
        if _cab_id >= 0:
            _other = (_k + 1) % len(_stops) if len(_stops) == 2 else (_k - 1) % len(_stops)
            _parts.append("(Elevator_%d.vFloor == %d && Switch_%d.isLastPressed)" % (_lift_id, _other, _cab_id))
        _go.append(" || ".join(_parts))
    _go += [""] * max(0, 10 - len(_go))
    _inside = ""
    if _cab_id >= 0:
        _ix, _iy, _iz = _lift_at(_L, _d["inside"])
        _inside = ", " + LIFT_SWITCH % ((_cab_id, _qstr_early("Lift button", 40), _ix, _iy, _iz,
                                         repr(round(float(_L.get("gamma") or 0) + float(_d["inside"][3] if len(_d["inside"]) > 3 else 0), 5)))
                                        + (LIFT_BUTTON,) * 5)
    blocks.append('Task_New(%d, "Elevator", "%s", %s, %s, %s, 0, 0, %s, "%s", %d, TRUE, FALSE, 0, %s, 1, "", "", "1", '
                  '"%s", "%s", "%s", "%s", "%s", "%s", "%s", "%s", "%s", "%s", '
                  '"elv_start_1", "elv_stop_1", "elv_move_1"%s), %s'
                  % ((_lift_id, _qstr_early(_L.get("name") or "Lift", 40), q(_L["x"]), q(_L["y"]), q(_L["z"]), _g,
                      _L.get("model") or "200_01_1", _sp_id, repr(round(float(_d.get("speed") or 5.0), 3)))
                     + tuple(x.replace('"', "'") for x in _go[:10]) + (_inside, EOL)))
# The ground a building of yours opens, as the game opens it for that building:
# the squares its home level takes away (a cellar's stairs, a lift's shaft - the
# kit carries them, doors.json "holes"). The game opens ground only a whole
# octree cube at a time, and draws it that way: its levels use 16 m cubes
# (LOD 15) and 32 m ones (LOD 14), each on a grid of its own size, and its
# buildings stand where those squares fall under their walls. The terrain's
# finest cubes, the 8 m leaves its meshes are held in (studio/build/terrain.py),
# open the way but not the picture: every cube carries a mesh of its own, and
# over an 8 m opening the 16 m cube's is still drawn - soil over the stairs you
# walk through. So a building of yours stands on the grid as the game's copy of
# it does (the editor sets it there), and Apply opens the game's own squares for
# it. One turned off the square cannot stand so: it gets the 8 m leaves wholly
# inside its squares and its footprint - walkable, the soil still drawn - and a
# warning. A lift of yours going below the ground has its shaft opened too,
# where no square of its building covers it already. A cube is dropped at the
# ground's height and in the cubes above and below it, so one on a slope that
# crosses a cube's top or bottom goes whole.
HOLE_TOL = 0.25                 # metres off the grid still counted as on it
HOLE_GRID = 16.0                # every opening laid in 16 m cubes (LOD 15): a 32 m square is four,
                                # so a building needs only this grid - it moves at most 8 m to sit on it
LEAF_LOD = 16                   # the terrain's 8 m leaves
LEAF_M = (1 << (31 - LEAF_LOD)) / SCALE
def _lod_of(size):
    """The octree level whose cubes are this many metres across."""
    return 31 - int(round(math.log2(size * SCALE)))


def _grid_off(v):
    """How far a square's corner lies from the nearest line of the grid."""
    return v - math.floor(v / HOLE_GRID + 0.5) * HOLE_GRID


def _square_turn(g):
    r = g % (math.pi / 2)
    return min(r, math.pi / 2 - r) < 0.02


def _hole_centres(b):
    """[(x, y, size)] of the squares building b opens, where they fall as it stands."""
    hs = (_kits.get(b.get("model")) or {}).get("holes") if b.get("type") == "building" else None
    if not hs:
        return []
    g = float(b.get("gamma") or 0)
    c, sn = math.cos(g), math.sin(g)
    return [(float(b["x"]) + h["dx"] * c - h["dy"] * sn, float(b["y"]) + h["dx"] * sn + h["dy"] * c, float(h["size"]))
            for h in hs]


def _leaves_of(cx, cy, hw, hd, g, step=1.0):
    """The leaves a rectangle touches: its middle (cx, cy), half its width and
    depth, turned by g - sampled every step metres."""
    out = set()
    c, sn = math.cos(g), math.sin(g)
    nx, ny = max(1, int(math.ceil(2 * hw / step))), max(1, int(math.ceil(2 * hd / step)))
    for i in range(nx + 1):
        for j in range(ny + 1):
            lx, ly = -hw + 2 * hw * i / nx, -hd + 2 * hd * j / ny
            out.add((math.floor((cx + lx * c - ly * sn) / LEAF_M), math.floor((cy + lx * sn + ly * c) / LEAF_M)))
    return out


def _leaves_inside(cx, cy, half, g):
    """The leaves wholly inside a square: its middle, half its side, turned by g."""
    out = set()
    c, sn = math.cos(-g), math.sin(-g)
    r = half * math.sqrt(2)
    for ix in range(math.floor((cx - r) / LEAF_M), math.floor((cx + r) / LEAF_M) + 1):
        for iy in range(math.floor((cy - r) / LEAF_M), math.floor((cy + r) / LEAF_M) + 1):
            if all(abs(((ix + ax) * LEAF_M - cx) * c - ((iy + ay) * LEAF_M - cy) * sn) <= half + 0.01 and
                   abs(((ix + ax) * LEAF_M - cx) * sn + ((iy + ay) * LEAF_M - cy) * c) <= half + 0.01
                   for ax in (0, 1) for ay in (0, 1)):
                out.add((ix, iy))
    return out


def _leaf_within(b, leaf, pad=0.3):
    """Is a leaf wholly inside building b's footprint?"""
    sz = _sizes.get(b.get("model")) or {}
    if not sz.get("w"):
        return False
    g = float(b.get("gamma") or 0)
    c, sn = math.cos(-g), math.sin(-g)
    for ax in (0, 1):
        for ay in (0, 1):
            x, y = (leaf[0] + ax) * LEAF_M - float(b["x"]), (leaf[1] + ay) * LEAF_M - float(b["y"])
            u, v = x * c - y * sn - (sz.get("cx") or 0), x * sn + y * c - (sz.get("cy") or 0)
            if abs(u) > sz["w"] / 2 + pad or abs(v) > sz.get("d", sz["w"]) / 2 + pad:
                return False
    return True


_cubes = {}                     # (x, y, size) of a square's middle -> (the ground's height, whose it is)
_leaves = {}                    # leaf -> (the ground's height, whose it is)
_covers = {}                    # uid -> the squares opened for that building
_on_grid = _off_grid = 0
for _b in PLACE:
    _cs = _hole_centres(_b)
    if not _cs:
        continue
    _who, _bz, _g = _b.get("name") or "Building", float(_b["z"]), float(_b.get("gamma") or 0)
    if _square_turn(_g) and all(abs(_grid_off(x - s / 2)) < HOLE_TOL and abs(_grid_off(y - s / 2)) < HOLE_TOL
                                for x, y, s in _cs):
        for x, y, s in _cs:
            _x0 = math.floor((x - s / 2) / HOLE_GRID + 0.5) * HOLE_GRID
            _y0 = math.floor((y - s / 2) / HOLE_GRID + 0.5) * HOLE_GRID
            _n = max(1, int(round(s / HOLE_GRID)))
            for _i in range(_n):
                for _j in range(_n):
                    _cubes.setdefault((_x0 + (_i + 0.5) * HOLE_GRID, _y0 + (_j + 0.5) * HOLE_GRID, HOLE_GRID), (_bz, _who))
        _covers[_b.get("uid")] = _cs
        _on_grid += 1
        continue
    for x, y, s in _cs:
        for _lf in _leaves_inside(x, y, s / 2.0, _g):
            if _leaf_within(_b, _lf):
                _leaves.setdefault(_lf, (_bz, _who))
    _off_grid += 1
    warnings.append("%s %s: the ground over its cellar is opened so it can be walked, but the soil over it "
                    "is still drawn - %s" % (_who, "stands between the game's ground squares" if _square_turn(_g)
                                             else "is turned %.0f degrees, off the game's ground grid" % (math.degrees(_g) % 360),
                                             "move it in the editor and it settles on the grid" if _square_turn(_g)
                                             else "turn it square and it settles on the grid"))
_holes = 0
for _L in OWN_LIFTS:
    _stops = [list(map(float, st))[:3] for st in (_L["lift"].get("stops") or [])]
    if len(_stops) < 2:
        continue
    _low = min(float(_L["z"]) + st[2] for st in _stops)
    # Where the ground is over the shaft: the building the lift came with, which
    # the build has already set down on the ground (the terrain's own height is
    # the height before this mission shaped it, so it is no use here).
    _home = _by_uid.get(_L.get("of"))
    _ground = float(_home["z"]) if _home else float(_L["z"])
    if _low > _ground - 2.0:
        continue                # it stays above the ground: nothing to open
    _holes += 1
    warnings.append("%s runs %.0f m below the ground: the ground over its shaft is opened, "
                    "so the cabin can go down" % (_L.get("name") or "a lift", _ground - _low))
    if any(abs(float(_L["x"]) - x) <= s / 2 and abs(float(_L["y"]) - y) <= s / 2
           for x, y, s in _covers.get(_L.get("of")) or []):
        continue                # its building's own square opens it, as in the game
    _cab = _sizes.get(_L.get("model") or "200_01_1") or {}
    _lg = float(_L.get("gamma") or 0)
    _ccx, _ccy = _cab.get("cx") or 0, _cab.get("cy") or 0
    _mx = float(_L["x"]) + _ccx * math.cos(_lg) - _ccy * math.sin(_lg)
    _my = float(_L["y"]) + _ccx * math.sin(_lg) + _ccy * math.cos(_lg)
    for _lf in _leaves_of(_mx, _my, (_cab.get("w") or 3.8) / 2 + 0.2, (_cab.get("d") or 3.8) / 2 + 0.2, _lg, 0.5):
        if _home is None or _leaf_within(_home, _lf):     # never ground beside its building
            _leaves.setdefault(_lf, (_ground, _L.get("name") or "Lift"))
for (_x, _y, _s), (_gz, _who) in sorted(_cubes.items()):
    for _dz in (-_s, 0.0, _s):
        blocks.append('Task_New(-1, "DiscardTerrain", "%s", %s, %s, %s, %d), %s'
                      % (_qstr_early(_who, 30), q(_x), q(_y), q(_gz + _dz), _lod_of(_s), EOL))
for (_ix, _iy), (_gz, _who) in sorted(_leaves.items()):
    for _dz in (-LEAF_M, 0.0, LEAF_M):
        blocks.append('Task_New(-1, "DiscardTerrain", "%s", %s, %s, %s, %d), %s'
                      % (_qstr_early(_who, 30), q((_ix + 0.5) * LEAF_M), q((_iy + 0.5) * LEAF_M),
                         q(_gz + _dz), LEAF_LOD, EOL))
if _cubes or _leaves:
    report.append("ground opened: %d of the game's square(s) for %d building(s) on its grid%s%s"
                  % (len(_cubes), _on_grid,
                     ", %d 8 m square(s) for %d off it" % (len(_leaves), _off_grid) if _off_grid else "",
                     "; %d lift shaft(s) going below the ground" % _holes if _holes else ""))
if OWN_LIFTS:
    report.append("%d lift(s) of yours, with a button at each floor and one inside" % len(OWN_LIFTS))

# ---------------------------------------------------------------- events: conditions and actions
_slot_m = re.search(r"level(\d+)$", str(SLOT_DIR)) if SLOT_DIR is not None else None
STRING_SLOT = int(_slot_m.group(1)) if _slot_m else LV
PREFIX = "MS%d_" % STRING_SLOT
LANG = {"slot": STRING_SLOT, "objectives.res": {}, "messages.res": {}}
# what each kind of event tests on its target, by the target's task type
EVENT_TESTS = {
    "switch": {"Switch": "isLastPressed"},
    "dead": {"HumanSoldier": "isDead", "HumanSoldierFemale": "isDead"},
    "hacked": {"Terminal": "isHacked"},
    "picked": {"GunPickup": "isPickedUp", "GenericPickup": "isPickedUp"},
    "destroyed": {"ExplodeObject": "isExploded", "Car": "isExploded", "Generator": "isExploded", "SCamera": "isExploded",
                  "Radio": "isExploded", "Terminal": "isExploded", "Heli": "isExploded"},
    "seen": {"SCamera": "isDetection"},
}
OWN_QTYPE = {"soldier": "HumanSoldier", "pickup": "GunPickup", "camera": "SCamera", "switch": "Switch"}


def _event_text(text, limit=200):
    return re.sub(r'["\\\r\n]', " ", str(text or "")).strip()[:limit]


def _event_cond(e):
    """The expression that makes an event happen, or (None, why)."""
    w = e["when"]
    kind = w.get("kind")
    if kind == "area":
        if w.get("x") is None or w.get("y") is None:
            return None, "no area set"
        aid = take_id()
        r = max(1.0, min(60.0, float(w.get("r") or 6.0)))
        gz = rest_z(w["x"], w["y"], w.get("z"))[0]
        z = (gz if gz is not None else (w.get("z") or 0.0)) + 1.0
        blocks.append('Task_New(%d, "AreaActivate", "Event area", %s, %s, %s, 0, 0, 0, %s, %s, %s, "CRITERIA_HUMAN0"), %s'
                      % (aid, q(w["x"]), q(w["y"]), q(z), q(r), q(r), q(3.0), EOL))
        return "AreaActivate_%d.nActive" % aid, None
    if kind == "alarm":
        ex = alarm_expr_of(w.get("alarmId"))
        return (ex, None) if ex else (None, "its alarm is no longer in the mission")
    if kind == "time":
        tid = take_id()
        blocks.append('Task_New(%d, "LevelTimer", "Event clock", 0, 0, 0, 0, 0, 0, "1", "", FALSE), %s' % (tid, EOL))
        return "LevelTimer_%d.nTick > %d*GAME_FREQUENCY" % (tid, max(1, int(float(w.get("seconds") or 10)))), None
    if kind == "after":
        before = event_fired(w.get("after"))
        if not before or w.get("after") == e["uid"]:
            return None, "the event it follows is no longer in the mission"
        tid = take_id()
        blocks.append('Task_New(%d, "LevelTimer", "Event clock", 0, 0, 0, 0, 0, 0, "%s", "", FALSE), %s' % (tid, before, EOL))
        return "LevelTimer_%d.nTick > %d*GAME_FREQUENCY" % (tid, max(1, int(float(w.get("seconds") or 0)) or 1)), None
    tests = EVENT_TESTS.get(kind)
    if not tests:
        return None, "unknown kind %r" % kind
    t = w.get("target") or {}
    if t.get("uid"):
        pl = next((x for x in PLACE if x.get("uid") == t["uid"]), None)
        if pl is None or "_tid" not in pl:
            return None, "its target is no longer placed"
        qt, tid = OWN_QTYPE.get(pl.get("type")), pl["_tid"]
    elif t.get("ref"):
        o = _world_by_ref.get(t["ref"])
        if o is None:
            return None, "its target was removed from the mission"
        if o.get("id", -1) < 0:
            return None, "its target has no task id the game can test"
        qt, tid = o.get("qtype"), o["id"]
    else:
        return None, "no target picked"
    if qt not in tests:
        return None, "a %s can't do that" % (qt or "thing")
    ex = "%s_%d.%s" % (qt, tid, tests[qt])
    if kind == "picked" and qt == "GunPickup":
        # the engine flags a weapon only when it goes into a free hand, not when it
        # tops up one the player carries: standing on it counts too (as objectives)
        o = pl if t.get("uid") else _world_by_ref.get(t["ref"])
        aid = take_id()
        gz = rest_z(o["x"], o["y"], o.get("z"))[0]
        zz = (gz if gz is not None else (o.get("z") or 0.0)) + 1.0
        blocks.append('Task_New(%d, "AreaActivate", "Event pickup spot", %s, %s, %s, 0, 0, 0, %s, %s, %s, '
                      '"CRITERIA_HUMAN0"), %s' % (aid, q(o["x"]), q(o["y"]), q(zz), q(1.5), q(1.5), q(3.0), EOL))
        ex = "%s || AreaActivate_%d.nActive" % (ex, aid)
    return ex, None


for _n, _e in enumerate(EVENTS, 1):
    _cond, _why = _event_cond(_e)
    _name = _e.get("name") or "event %d" % _n
    if _cond is None:
        warnings.append("event %d (%s): %s - it never happens" % (_n, _name, _why))
        continue
    _v = EVENT_VAR[_e["uid"]]
    blocks.append('Task_New(%d, "EditVariable", "%s", 0, 0, 0, 0, "EditVariable_%d.nValue == 0 && (%s)", ""), %s'
                  % (_v, _qstr_early("Event: " + _name, 60), _v, _cond, EOL))
    _fired = event_fired(_e["uid"])
    _did = []
    for _k, _a in enumerate(_e.get("do") or [], 1):
        if not isinstance(_a, dict):
            continue
        if _a.get("kind") == "message":
            _txt = _event_text(_a.get("text"))
            if not _txt:
                continue
            _key = PREFIX + "E%d_%d" % (_n, _k)
            LANG["messages.res"][_key] = _txt
            blocks.append('Task_New(%d, "StatusMessage", "%s", 0, 0, 0, 0, 0, 0, "%s", "%s", "", "message", TRUE, FALSE, %s), %s'
                          % (take_id(), _qstr_early("Event message " + _name, 60), _fired, _key,
                             repr(round(max(1.0, min(30.0, float(_a.get("secs") or 4.0))), 1)), EOL))
            _did.append('says "%s"' % _txt[:40])
        elif _a.get("kind") == "alarm":
            if alarm_ctl_id(_a.get("alarmId")) is None:
                warnings.append("event %d (%s): its alarm is no longer in the mission" % (_n, _name))
                continue
            # a pulse of a few ticks as it happens: an alarm switched off later is not
            # raised again by an event that stays happened
            _pt = take_id()
            blocks.append('Task_New(%d, "LevelTimer", "Event pulse", 0, 0, 0, 0, 0, 0, "%s", "", FALSE), %s' % (_pt, _fired, EOL))
            ALARM_TRIGGER.setdefault(_a["alarmId"], []).append("(LevelTimer_%d.nTick > 0 && LevelTimer_%d.nTick < 6)" % (_pt, _pt))
            _did.append("raises the alarm")
        elif _a.get("kind") == "fail":
            _txt = _event_text(_a.get("text"))
            _key = "MISSION_FAILED"
            if _txt:
                _key = PREFIX + "E%d_%d" % (_n, _k)
                LANG["messages.res"][_key] = _txt
            _fid = take_id()
            blocks.append('Task_New(%d, "StatusMessage", "%s", 0, 0, 0, 0, 0, 0, "%s", "%s", "", "fail", TRUE, FALSE, 2.0), %s'
                          % (_fid, _qstr_early("Event fails " + _name, 60), _fired, _key, EOL))
            EVENT_FAILS.append("StatusMessage_%d.nTicksSinceFinishedDisplay > 1 * GAME_FREQUENCY" % _fid)
            _did.append("fails the mission")
    _arrive = [x for x in soldiers if x.get("arriveOn") == _e["uid"]]
    if _arrive:
        _did.append("sends %d guard(s)" % len(_arrive))
    report.append("event %d (%s): when %s, %s" % (_n, _name, _cond if len(_cond) < 70 else _cond[:67] + "...",
                                                ", ".join(_did) or "nothing else"))

# ---------------------------------------------------------------- doors
# A door of the level (Door: ... Model, Max angle, Open time, Pickable, Pick lock
# time, Locked expression, Open door expression, Close door expression, sounds).
# The edit carries lock {kind, target, event}, pick (seconds) and openOn (an
# event): locked until a switch, a terminal, an item, a guard or an event, as
# level 10 does it (an EditVariable the door waits for); a lock that can be
# picked (level 11: "Door_405.isClosed && !Door_405.isPicked"); opening by
# itself when an event happens. The text is rewritten at splice (DOOR_SET).
DOOR_SET = {}                   # ref -> (locked expression or None, open expression to add or None, pick seconds)
DOOR_LOCK_KIND = {"switch": "switch", "terminal": "hacked", "item": "picked", "guard": "dead"}
for _e in EDITS:
    if _e.get("type") != "door" or not any(_e.get(k) for k in ("lock", "pick", "openOn")):
        continue
    _o = _world_by_ref.get(_e["ref"])
    if _o is None:
        continue
    _lk = _e.get("lock") or {}
    _locked = None
    if _lk.get("kind") == "always":
        _locked = "1"
    elif _lk.get("kind") == "event":
        if EVENT_VAR.get(_lk.get("event")):
            _locked = "EditVariable_%d.nValue == 0" % EVENT_VAR[_lk["event"]]
        else:
            warnings.append("door at %.0f, %.0f: the event that unlocks it is no longer in the mission" % (_o["x"], _o["y"]))
    elif _lk.get("kind") in DOOR_LOCK_KIND:
        _c, _why = _event_cond({"uid": "door", "when": {"kind": DOOR_LOCK_KIND[_lk["kind"]], "target": _lk.get("target")}})
        if _c is None:
            warnings.append("door at %.0f, %.0f: %s - it stays as the level has it" % (_o["x"], _o["y"], _why))
        else:
            _v = take_id()
            blocks.append('Task_New(%d, "EditVariable", "Door key", 0, 0, 0, 0, "EditVariable_%d.nValue == 0 && (%s)", ""), %s'
                          % (_v, _v, _c, EOL))
            _locked = "EditVariable_%d.nValue == 0" % _v
    _pick = max(0.0, min(60.0, float(_e.get("pick") or 0)))
    if _pick:
        _did = _o.get("id", -1)
        if _did < 0:
            _did = take_id()
            ANCHOR_NEW.append((_o["ref"], _did))
            _o["id"] = _did
        _locked = "(%s) && !Door_%d.isPicked" % (_locked or "Door_%d.isClosed" % _did, _did)
    _open = event_fired(_e.get("openOn")) if _e.get("openOn") else None
    if _e.get("openOn") and not _open:
        warnings.append("door at %.0f, %.0f: the event that opens it is no longer in the mission" % (_o["x"], _o["y"]))
    if _locked or _open or _pick:
        DOOR_SET[_e["ref"]] = (_locked, _open, _pick)
        report.append("door at %.0f, %.0f: %s" % (_o["x"], _o["y"], ", ".join(filter(None, [
            ("locked" if _locked == "1" else "locked until %s" % (_lk.get("kind"))) if _lk.get("kind") else None,
            "lock picked in %gs" % _pick if _pick else None, "opens on an event" if _open else None]))))

# now the mission's own controls, with everything that joins them known
for kit in alarm_kit:
    if kit["type"] != "alarmctl":
        continue
    key, cid, vid = "own:%s" % kit.get("uid"), kit["_tid"], kit["_var"]
    raise_terms = ALARM_TRIGGER.get(key) or []
    if not raise_terms:
        warnings.append("%s: nothing raises it - put a camera or a button on it" % (kit.get("name") or "alarm system"))
    trigger = "!AlarmControl_%d.isAlarm && (%s)" % (cid, " ||\\n".join(raise_terms) if raise_terms else "0")
    off = ALARM_SILENCE.get(key) or []
    # no model: "waypoint", which most shipped levels give it, is the level
    # editor's arrow (2.9 x 6.3 m) and the game draws it - the designers bury
    # theirs underground. Level 5's alarm control has none, as here.
    blocks.append('Task_New(%d, "AlarmControl", "%s", %s, %s, %s, 0, 0, 0, "", "", 1, 0.5, 0.5, 1, 0, 5, 4, "", '
                  '"explo_02_m", "1", %s, "%s", "EditVariable_%d.nValue == 1"), %s'
                  % (cid, _qstr_early(kit.get("name") or "Alarm system", 40), q(kit["x"]), q(kit["y"]), q(kit["z"]),
                     repr(round(float(kit.get("hackTime") or 4.0), 2)), trigger, vid, EOL))
    blocks.append('Task_New(%d, "EditVariable", "%s state", %s, %s, %s, 0, '
                  '"EditVariable_%d.nValue == 0 && AlarmControl_%d.isTrigger", "%s"), %s'
                  % (vid, _qstr_early(kit.get("name") or "Alarm", 30), q(kit["x"]), q(kit["y"]), q(kit["z"]),
                     vid, cid,
                     ("EditVariable_%d.nValue == 1 && AlarmControl_%d.isAlarm && (%s)" % (vid, cid, " || ".join(off)))
                     if off else "", EOL))
    report.append("alarm system %s: task %d, raised by %d thing(s)%s"
                  % (kit.get("name") or cid, cid, len(raise_terms),
                     ", switched off by %d button(s)" % len(off) if off else ""))

# ---------------------------------------------------------------- objectives
# The mission's own goals, the way the shipped levels wire theirs (level 14):
#   DefineComputerObjective   up to 6: text resource, map position, complete expression
#   StatusMessage             "Objective complete" as each one is done, then "Mission complete"
#   LevelFlow                 completes when that last message has shown; fails on the
#                             level's own failures, the player's death, and (if asked) the alarm
# Texts go into the language files under MS<slot>_ (studio/build/lang.py, at install).
# "level" is one of the base level's own objectives, kept (and possibly
# reordered) by the plan: its text key, link and expressions are the level's.
OBJ_KINDS = {"kill", "killAll", "collect", "reach", "hack", "destroy", "level"}
OBJECTIVES = [o for o in (plan.get("objectives") or []) if isinstance(o, dict) and o.get("kind") in OBJ_KINDS]
if len(OBJECTIVES) > 6:
    warnings.append("only the first 6 objectives are used - the map computer lists 6")
    OBJECTIVES = OBJECTIVES[:6]
FAIL_ON_ALARM = bool(plan.get("failOnAlarm"))
DEFAULT_TEXT = {"kill": "Eliminate the %s.", "killAll": "Eliminate every guard.", "collect": "Collect the %s.",
                "reach": "Reach the marked area.", "hack": "Hack the %s.", "destroy": "Destroy the %s."}


def _qstr(s, limit=250):
    return re.sub(r'["\\\r\n]', " ", str(s or ""))[:limit]


# The map computer draws a numbered marker for each objective on its terrain
# view: a ComputerHilight with the sprite COMPUTER:h_<n>.spr at the objective's
# position. The level's own are switched off, so ours carry the numbers.
HILIGHT = re.compile(r'Task_New\((-?\d+), "ComputerHilight", ')


def _brackets_end(text, start):
    """Index just past the ')' closing the Task_New that starts at start."""
    depth, j, instr = 0, start, False
    while j < len(text):
        ch = text[j]
        if ch == '"' and text[j - 1] != "\\":
            instr = not instr
        elif not instr:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
        j += 1
    return len(text)


def shipped_hilights(text):
    """{link task id: (x, y, z, show expression)} of the level's numbered markers."""
    out = {}
    for m in HILIGHT.finditer(text):
        seg = text[m.start():_brackets_end(text, m.start())]
        sp = [x for x in re.finditer(r'"((?:[^"\\]|\\.)*)"', seg)]
        if len(sp) < 5 or not sp[4].group(1).startswith("COMPUTER:h_"):
            continue
        nums = re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", seg[sp[1].end():sp[2].start()])
        if len(nums) < 3:
            continue
        out[sp[3].group(1)] = (nums[0], nums[1], nums[2], sp[2].group(1))
    return out


# A marker is drawn where the TASK IT NAMES stands, not at its own position:
# level 1 puts all 17 of its hilights at one point and they show at their own
# buildings. The computer can only find the level's fixed objects this way - a
# marker pointing at a guard or at a weapon on the ground draws nothing - so
# every marker is hung on the nearest thing it does know.
LOCATABLE = ("Building", "Terminal", "GenericPickup", "ExplodeObject", "Car", "Heli",
             "Generator", "Radio", "Switch")


def _pickup_spot(x, y, z):
    """|| the player standing on the item. A weapon is taken by walking into it, and
    the engine only flags GunPickup.isPickedUp when it goes into a free hand - not
    when it merely tops up the ammo of one the player already carries. The box is
    1.5 m, so it takes standing on the thing."""
    aid = take_id()
    gz = rest_z(x, y, z)[0]
    zz = (gz if gz is not None else (z or 0.0)) + 1.0
    blocks.append('Task_New(%d, "AreaActivate", "Objective pickup spot", %s, %s, %s, 0, 0, 0, %s, %s, %s, '
                  '"CRITERIA_HUMAN0"), %s' % (aid, q(x), q(y), q(zz), q(1.5), q(1.5), q(3.0), EOL))
    return " || AreaActivate_%d.nActive" % aid


def marker_anchor(x, y):
    """Task id of the nearest thing the map computer can place, or None."""
    cands = sorted(((math.hypot(o["x"] - x, o["y"] - y), i, o) for i, o in enumerate(WORLD)
                    if o.get("qtype") in LOCATABLE and not o.get("cutscene")),
                   key=lambda c: c[0])
    if not cands:
        return None
    near = cands[0]
    with_id = next((c for c in cands if c[2].get("id", -1) >= 0), None)
    # one that already has an id is worth a few metres of detour
    if with_id and with_id[0] <= max(25.0, near[0] * 1.5):
        return with_id[2]["id"]
    o = near[2]
    if o.get("id", -1) >= 0:
        return o["id"]
    if not o.get("ref"):
        return with_id[2]["id"] if with_id else None
    nid = take_id()                     # the level left it at -1: give it one
    ANCHOR_NEW.append((o["ref"], nid))
    o["id"] = nid
    _by_id[nid] = o
    return nid


def _objective_expr(ob):
    """(expression, task id to show on the map computer, what it is) or (None, why)."""
    kind, t = ob["kind"], ob.get("target") or {}
    if kind == "reach":
        if ob.get("x") is None or ob.get("y") is None:
            return None, "no area set"
        aid = take_id()
        r = max(1.0, float(ob.get("r") or 5.0))
        gz = rest_z(ob["x"], ob["y"], ob.get("z"))[0]
        z = (gz if gz is not None else (ob.get("z") or 0.0)) + 1.0
        OBJ_AT[id(ob)] = (ob["x"], ob["y"], z)
        blocks.append('Task_New(%d, "AreaActivate", "Objective area", %s, %s, %s, 0, 0, 0, %s, %s, %s, "CRITERIA_HUMAN0"), %s'
                      % (aid, q(ob["x"]), q(ob["y"]), q(z), q(r), q(r), q(3.0), EOL))
        return ("AreaActivate_%d.nActive" % aid, aid, "the area"), None
    if kind == "killAll":
        terms = ["HumanSoldier_%d.isDead" % s["_tid"] for s in soldiers if "_tid" in s and int(s.get("team", 1)) != 0]
        for o in WORLD:
            if (o.get("type") == "soldier" and not o.get("cutscene") and o.get("id", -1) >= 0
                    and int(o.get("team", 1) if o.get("team") is not None else 1) != 0):
                terms.append("%s_%d.isDead" % (o.get("qtype") or "HumanSoldier", o["id"]))
        if not terms:
            return None, "there are no guards"
        return (" && ".join(terms), -1, "every guard"), None
    if t.get("uid"):
        p = next((x for x in PLACE if x.get("uid") == t["uid"]), None)
        if p is None or "_tid" not in p:
            return None, "its target is no longer placed"
        OBJ_AT[id(ob)] = (p["x"], p["y"], p.get("z") or 0.0)
        name = p.get("name") or p.get("model")
        if kind == "kill" and p.get("type") == "soldier":
            return ("HumanSoldier_%d.isDead" % p["_tid"], p["_tid"], re.sub(r"^the ", "", str(name))), None
        if kind == "collect" and p.get("type") == "pickup":
            return ("GunPickup_%d.isPickedUp%s" % (p["_tid"], _pickup_spot(p["x"], p["y"], p.get("z"))),
                    p["_tid"], name), None
        if kind == "destroy" and p.get("type") == "camera":
            return ("SCamera_%d.isExploded" % p["_tid"], p["_tid"], "security camera"), None
        return None, "a %s can't be the target of a '%s' objective" % (p.get("type"), kind)
    if t.get("ref"):
        o = _world_by_ref.get(t["ref"])
        if o is None:
            return None, "its target was removed from the mission"
        OBJ_AT[id(ob)] = (o["x"], o["y"], o.get("z") or 0.0)
        if o.get("id", -1) < 0:
            return None, "its target has no task id the game can test"
        qt = o.get("qtype") or ""
        name = ("the guard" if o.get("type") == "soldier" else
                (o.get("name") or o.get("modelName") or qt).replace("_", " ").lower())
        name = re.sub(r"^the ", "", name)
        if kind == "kill" and o.get("type") == "soldier":
            return ("%s_%d.isDead" % (qt, o["id"]), o["id"], "guard"), None
        if kind == "hack" and qt == "Terminal":
            return ("Terminal_%d.isHacked" % o["id"], o["id"], name), None
        if kind == "collect" and qt in ("GunPickup", "GenericPickup"):
            spot = _pickup_spot(o["x"], o["y"], o.get("z")) if qt == "GunPickup" else ""
            return ("%s_%d.isPickedUp%s" % (qt, o["id"], spot), o["id"], name), None
        if kind == "destroy" and qt in ("ExplodeObject", "Car", "Generator", "SCamera", "Radio", "Terminal", "Heli"):
            return ("%s_%d.isExploded" % (qt, o["id"]), o["id"], name), None
        return None, "a %s can't be the target of a '%s' objective" % (qt or o.get("type"), kind)
    return None, "no target picked"


OBJ_TASK_IDS = {}
OBJ_AT = {}                     # objective -> where its marker goes
OBJ_MARKS = []                  # the numbered markers, built with the list
_SHIPPED_HILIGHTS = shipped_hilights(src)
# the level's own numbered markers: the mission writes its own over these
_NUMBERED_HILIGHTS = [m for m in HILIGHT.finditer(src)
                      if 'COMPUTER:h_' in src[m.start():_brackets_end(src, m.start())]]
_by_id = {o["id"]: o for o in WORLD if o.get("id", -1) >= 0}
if OBJECTIVES:
    exprs, slots_txt, own_n = [], [], 0
    for i, ob in enumerate(OBJECTIVES, 1):
        if ob["kind"] == "level":
            if EMPTY:
                # its complete and failed expressions name the level's own tasks,
                # and the empty map has none of them
                errors.append("objective %d (%s) is one of the level's own, and the empty map has none of "
                              "the level's mission logic, so it could never be completed - remove it"
                              % (i, (ob.get("text") or ob.get("key") or "")[:60]))
                continue
            # the level's own: its text is already in the language files, unless
            # the mission words it anew (retext: the AI designer's write_texts)
            key, link = _qstr(ob.get("key"), 31), int(ob.get("link") or -1)
            if ob.get("retext") and (ob.get("text") or "").strip():
                key = PREFIX + "O%d" % i
                LANG["objectives.res"][key] = ob["text"].strip()[:70]
            done, failed = _qstr(ob.get("done"), 250), _qstr(ob.get("failed"), 250)
            if not key:
                errors.append("objective %d: a level objective with no text key" % i)
                continue
            slots_txt.append('"%s", %d, "%s", "%s"' % (key, link, done, failed))
            if done:
                exprs.append(done)
            hl = _SHIPPED_HILIGHTS.get(str(link))
            if hl:
                OBJ_MARKS.append((len(slots_txt), hl[0], hl[1], hl[2], link, hl[3] or "1"))
            elif link >= 0 and link in _by_id:
                o = _by_id[link]
                anchor = o["id"] if o.get("qtype") in LOCATABLE else marker_anchor(o["x"], o["y"])
                if anchor is not None:
                    OBJ_MARKS.append((len(slots_txt), q(o["x"]), q(o["y"]), q(o.get("z") or 0.0), anchor,
                                      done and ("!(%s)" % done) or "1"))
            report.append("objective %d: %s (the level's own)%s"
                          % (i, (ob.get("text") or key)[:60], "" if done else " - it has no completion of its own"))
            continue
        got, why = _objective_expr(ob)
        if got is None:
            errors.append("objective %d (%s): %s" % (i, ob["kind"], why))
            continue
        expr, link, what = got
        key = PREFIX + "O%d" % i
        text = (ob.get("text") or "").strip() or (DEFAULT_TEXT[ob["kind"]] % what if "%s" in DEFAULT_TEXT[ob["kind"]]
                                                  else DEFAULT_TEXT[ob["kind"]])
        LANG["objectives.res"][key] = text
        own_n += 1
        sid = take_id()
        blocks.append('Task_New(%d, "StatusMessage", "Objective %d complete", 0, 0, 0, 0, 0, 0, "%s", '
                      '"OBJECTIVE_COMPLETE", "", "message", TRUE, FALSE, 2.0), %s' % (sid, i, expr, EOL))
        # The map computer ticks an objective off when its complete expression is
        # true AT THAT MOMENT, and some of them only hold for an instant: standing
        # in an area sets AreaActivate.nActive while you are in it and no longer.
        # The message is sent once and stays sent, so the tick hangs off that -
        # the way levels 6 and 10 do it.
        done_expr = "StatusMessage_%d.isSendt" % sid
        exprs.append(done_expr)
        at = OBJ_AT.get(id(ob))
        anchor = None
        if at:
            tgt = _world_by_ref.get((ob.get("target") or {}).get("ref") or "")
            anchor = tgt["id"] if tgt and tgt.get("qtype") in LOCATABLE and tgt.get("id", -1) >= 0 \
                else marker_anchor(at[0], at[1])
            if anchor is None:
                warnings.append("objective %d: nothing near it that the map computer can mark" % i)
        # the number on the map, and where the computer goes when the objective is
        # picked in the list, both name a task the computer can place
        slots_txt.append('"%s", %d, "%s", ""' % (key, anchor if anchor is not None else link, done_expr))
        if anchor is not None:
            OBJ_MARKS.append((len(slots_txt), q(at[0]), q(at[1]), q(at[2]), anchor, "!" + done_expr))
            if anchor != link:
                a_o = _by_id.get(anchor)
                if a_o:
                    report.append("objective %d: marked by %s (%.0f m from it) - the map computer cannot place a %s"
                                  % (i, a_o.get("name") or a_o.get("modelName") or a_o.get("qtype"),
                                     math.hypot(a_o["x"] - at[0], a_o["y"] - at[1]),
                                     (tgt or {}).get("qtype") if tgt else "placed object"))
        report.append("objective %d: %s  [%s]" % (i, text, expr if len(expr) < 90 else expr[:87] + "..."))
    if slots_txt:
        while len(slots_txt) < 6:
            slots_txt.append('"", -1, "", ""')
        # The list itself goes into the level's own DefineComputerObjective at
        # splice time - the map computer shows that one, and a second task of
        # ours would compete with it.
        OBJ_TASK_IDS["slots"] = slots_txt[:6]
    if exprs and own_n:
        done = take_id()
        blocks.append('Task_New(%d, "StatusMessage", "Mission complete", 0, 0, 0, 0, 0, 0, "%s", '
                      '"MISSION_COMPLETE", "", "message", TRUE, FALSE, 2.0), %s'
                      % (done, " && ".join("(%s)" % e for e in exprs), EOL))
        OBJ_TASK_IDS["done"] = done
        fails = ["HumanPlayer_0.isDead"]
        if FAIL_ON_ALARM:
            alarms = re.findall(r'Task_New\((\d+), "AlarmControl"', src) + ([str(CAM_ALARM)] if CAM_ALARM else [])
            if alarms:
                fid = take_id()
                blocks.append('Task_New(%d, "StatusMessage", "Alarm raised", 0, 0, 0, 0, 0, 0, "%s", '
                              '"MISSION_FAILED", "", "fail", TRUE, FALSE, 2.0), %s'
                              % (fid, " || ".join("AlarmControl_%s.isAlarm" % a for a in alarms), EOL))
                fails.append("StatusMessage_%d.nTicksSinceFinishedDisplay > 1 * GAME_FREQUENCY" % fid)
            else:
                warnings.append("fail on alarm: this level has no alarm to raise")
        OBJ_TASK_IDS["fails"] = fails

# map computer labels for your own buildings
LABELS = [p for p in objects if isinstance(p.get("label"), dict) and (p["label"].get("title") or "").strip()]
MARK_TASKS = ['Task_New(-1, "ComputerHilight", "Objective %d", %s, %s, %s, "%s", "%s", "COMPUTER:h_%d.spr", '
              '"MARKER_NONE", "MARKER_COLOR_NONE", "", "")'
              % (n, x, y, z, show, "" if link is None or link < 0 else link, n)
              for n, x, y, z, link, show in OBJ_MARKS[:6]]
LABEL_TASKS = []
for i, p in enumerate(LABELS, 1):
    tk, ik = PREFIX + "L%dT" % i, PREFIX + "L%dI" % i
    LANG["messages.res"][tk] = p["label"]["title"].strip()
    LANG["messages.res"][ik] = (p["label"].get("info") or "").strip() or p["label"]["title"].strip()
    LABEL_TASKS.append('Task_New(%d, "ComputerHilight", "%s", %s, %s, %s, "1", "%d", "", "MARKER_NONE", '
                       '"MARKER_COLOR_NONE", "%s", "%s")'
                       % (take_id(), _qstr(p["label"]["title"], 60), q(p["x"]), q(p["y"]), q(p["z"]), p["_tid"], tk, ik))
if LABELS:
    report.append("map computer labels: %s" % ", ".join(p["label"]["title"].strip() for p in LABELS))
# The map computer holds 32 of these and no more: a 33rd is the fatal
# "QTaskList is full" at level load. Level 8 ships exactly 32, level 3 ships 29.
# Objective markers come first, then labels; what does not fit is dropped here
# rather than in the player's face.
HILIGHT_MAX = 32
_hil_have = len(re.findall(r'Task_New\(-?\d+, "ComputerHilight"', src))
_room = HILIGHT_MAX - _hil_have - max(0, len(MARK_TASKS) - min(len(MARK_TASKS), len(_NUMBERED_HILIGHTS)))
if len(LABEL_TASKS) > max(0, _room):
    dropped = len(LABEL_TASKS) - max(0, _room)
    warnings.append("map computer labels: %d left out - it holds %d markers and this level already uses %d"
                    % (dropped, HILIGHT_MAX, _hil_have))
    LABEL_TASKS = LABEL_TASKS[:max(0, _room)]
if not re.search(r'Task_New\(-?\d+, "ComputerHilight"', src):
    blocks.extend(t + ", " + EOL for t in LABEL_TASKS + MARK_TASKS)
    LABEL_TASKS, MARK_TASKS = [], []
if errors:
    print("PLAN REJECTED - %d problem(s):" % len(errors))
    for e in errors:
        print("   x " + e)
    sys.exit(1)


# ---------------------------------------------------------------- splice
# A marker goes in first, the shipped soldiers are stripped around it if this is
# a new mission, and only then does the marker become our blocks. That way the
# stripper never has to tell our soldiers apart from theirs.
MARKER = "/*@@PLOTTER_INSERT@@*/"


def container_chain(text, pos):
    """Containers enclosing an offset, outermost first."""
    stack, i, instr = [], 0, False
    while i < pos:
        c = text[i]
        if c == '"':
            instr = not instr
        elif not instr:
            if text.startswith("Task_New(", i):
                mm = re.match(r'Task_New\((-?\d+), "([A-Za-z0-9_]+)", "([^"]*)"', text[i:])
                if mm:
                    stack.append(mm.groups())
            elif c == ")" and stack:
                stack.pop()
        i += 1
    return [s for s in stack if s[1] in ("Container", "ConditionalContainer")]


def pick_anchor(text):
    """Choose a HumanSoldier to insert beside.

    Not just the first one: in level 1 that is id 1505, which sits inside
    ConditionalContainer 'Intro cutscene' / 'Opening heli and train'. Anything
    placed there exists only while the intro plays, so it never appears in
    normal play. We want a soldier in the live gameplay branch - the container
    the game's own patrolling guards live in.
    """
    best = None
    for m in re.finditer(r'Task_New\(\d+, "HumanSoldier", "', text):
        chain = container_chain(text, m.start())
        # The OUTERMOST container is called "Cutscenes" for every soldier in
        # level 1, gameplay ones included, so only the conditional branches tell
        # the intro apart from the live level.
        cond = " ".join((c[2] or "").lower() for c in chain if c[1] == "ConditionalContainer")
        if re.search(r"cutscene|intro|outro|opening|ending", cond):
            continue
        names = " ".join((c[2] or "").lower() for c in chain)
        score = len(chain)
        if re.search(r"\bguard", names):
            score += 10
        if re.search(r"\bai\b", names):
            score += 5
        if best is None or score > best[0]:
            best = (score, m.start(), chain)
    return best


picked = (None, src.index(MARKER), []) if MARKER in src else pick_anchor(src)
if not picked:
    sys.exit("no HumanSoldier outside a cutscene container in level %d - "
             "cannot find a safe insertion point" % LV)
anchor_pos, anchor_chain = picked[1], picked[2]
out_src = src if MARKER in src else src[:anchor_pos] + MARKER + src[anchor_pos:]
anchor_desc = " > ".join(("%s(%s)%s" % (c[1], c[0], (" " + c[2]) if c[2] else ""))
                         for c in anchor_chain[-3:]) or "(top level)"


def strip_soldier_blocks(text):
    """Remove every shipped HumanSoldier task, children included, by matching
    parentheses. Buildings, props and terrain are untouched - those are the map."""
    pat = re.compile(r'Task_New\(-?\d+, "HumanSoldier\w*", "')
    res, i, n = [], 0, 0
    while True:
        m = pat.search(text, i)
        if not m:
            res.append(text[i:])
            return "".join(res), n
        res.append(text[i:m.start()])
        depth, j, instr = 0, m.start(), False
        while j < len(text):
            ch = text[j]
            if ch == '"':
                instr = not instr
            elif not instr:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        while j < len(text) and text[j] in ", \r\n":
                            j += 1
                        break
            j += 1
        n += 1
        i = j


def strip_task(text, tid):
    """Remove one task by id, children included, by matching parentheses."""
    m = re.search(r'Task_New\(%d, "[A-Za-z0-9_]+", "' % tid, text)
    if not m:
        return text, False
    depth, j, instr = 0, m.start(), False
    while j < len(text):
        ch = text[j]
        if ch == '"':
            instr = not instr
        elif not instr:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    j += 1
                    while j < len(text) and text[j] in ", \r\n":
                        j += 1
                    break
        j += 1
    return text[:m.start()] + text[j:], True


removed = 0
if MODE == "new":
    out_src, removed = strip_soldier_blocks(out_src)

# objects the plan asked to delete - the stock level is never touched, only this build
dropped = 0
for tid in plan.get("removals", []) or []:
    try:
        out_src, ok = strip_task(out_src, int(tid))
        dropped += 1 if ok else 0
    except (TypeError, ValueError):
        pass


# ---------------------------------------------------------------- shipped objects, in place
# Edits and removals of what the level already has are made to the very task
# that holds it, found by its reference (type + position exactly as written).
# Ids never change, so objectives, scripts and anything else that names the
# task keep working.
def task_end(text, start):
    """Index just past the ')' closing the Task_New that starts at start."""
    depth, j, instr = 0, start, False
    while j < len(text):
        ch = text[j]
        if ch == '"' and text[j - 1] != "\\":
            instr = not instr
        elif not instr:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
        j += 1
    return len(text)


def find_ref(text, ref):
    qtype, _, coords = ref.partition("@")
    parts = coords.split(",")
    if len(parts) != 3:
        return None
    return re.search(r'Task_New\((-?\d+), "%s", "(?:[^"\\]|\\.)*", %s, %s, %s(?=\s*[,)])'
                     % (re.escape(qtype), re.escape(parts[0]), re.escape(parts[1]), re.escape(parts[2])), text)


def cut_task(text, start, end):
    """Remove text[start:end] and exactly one of the commas around it."""
    j = end
    while j < len(text) and text[j] in " \t\r\n":
        j += 1
    if j < len(text) and text[j] == ",":
        j += 1
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        return text[:start] + text[j:]
    k = start
    while k > 0 and text[k - 1] in " \t\r\n":
        k -= 1
    if k > 0 and text[k - 1] == ",":
        k -= 1
    return text[:k] + text[end:]


NUM = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
# an SCamera's settings after the holder model, up to (not including) its On expression
CAM_REST = re.compile(r', (%s), (%s), "[^"]*", "[^"]*", (%s), (%s), (%s), (%s), (%s), (%s), (%s)' % ((NUM,) * 9))
HEAD = re.compile(r'(Task_New\(-?\d+, "[^"]+", "(?:[^"\\]|\\.)*", )(%s), (%s), (%s)((?:, %s)*), "([^"]*)"'
                  % (NUM, NUM, NUM, NUM))


def patrol_commands(route, terminal):
    out = []
    for n in route:
        out.append('Task_New(-1, "PatrolPathCommand", "Walks to node id %d", 2, %d), ' % (n, n) + EOL)
        out.append('Task_New(-1, "PatrolPathCommand", "Delays the script execution for 200 ticks", 1, 200), ' + EOL)
    desc = ("End script, only runs commands after this one. Takes no paramet" if terminal == 6
            else "Quit script, stops script. Takes no parameters")
    out.append('Task_New(-1, "PatrolPathCommand", "%s", %d, 0)' % (desc, terminal))
    return "".join(out)


GONE_CAMS = []
for r in plan.get("removeRefs", []) or []:
    m = find_ref(out_src, r)
    if not m:
        warnings.append("could not find %s to remove - skipped" % r)
        continue
    out_src = cut_task(out_src, m.start(), task_end(out_src, m.start()))
    dropped += 1
    if int(m.group(1)) >= 0:
        GONE_CAMS.append((r.split("@")[0], int(m.group(1))))
# Nothing may still ask a task that is no longer there: what it did becomes 0,
# what happened to it becomes 1. No \b in front - expressions break lines with a
# literal \n, as in "||\nSCamera_1303". "FALSE" is not a word the engine knows.
GONE_OFF = "isDetection|isPressed|isLastPressed|isHacked|isHackedThisTick|isAlarm|isTrigger|isOn|isRun|isOpen|isClosed|isPicked|nActive|nValue|nTick|isPickedUp|isSendt|isSearched|isSpawned|nSpawns"
GONE_ON = "isDead|isExploded|isFinished"
for qt, tid in GONE_CAMS:
    out_src = re.sub(r"%s_%d\.(?:%s)\b" % (re.escape(qt), tid, GONE_OFF), "0", out_src)
    out_src = re.sub(r"%s_%d\.(?:%s)\b" % (re.escape(qt), tid, GONE_ON), "1", out_src)

edited = 0
for e in EDITS:
    m = find_ref(out_src, e["ref"])
    if not m:
        warnings.append("could not find %s to edit - skipped" % e["ref"])
        continue
    s0 = m.start()
    s1 = task_end(out_src, s0)
    seg = out_src[s0:s1]
    h = HEAD.match(seg)
    if not h:
        warnings.append("%s has a layout this editor does not rewrite - skipped" % e["ref"])
        continue
    x = q(e["x"]) if e.get("x") is not None else h.group(2)
    y = q(e["y"]) if e.get("y") is not None else h.group(3)
    z = q(e["z"]) if e.get("z") is not None else h.group(4)
    nums = h.group(5)
    if e.get("gamma") is not None and nums:
        vals = re.findall(NUM, nums)
        if e.get("type") == "pickup" and len(vals) == 3 and abs(float(vals[1]) - 1.5708) < 0.05:
            # lying on its side: the heading is alpha - turn it by what the editor turned
            turn = float(e["gamma"]) - float((_by_ref.get(e["ref"]) or {}).get("gamma") or 0)
            vals[0] = repr(round((float(vals[0]) + (-turn if CCW_LYING else turn)) % (2 * math.pi), 6))
            nums = "".join(", " + v for v in vals)
        else:
            # yaw is the last number before the model - see extract_levels.py
            nums = re.sub(r"(%s)$" % NUM, repr(round(float(e["gamma"]), 6)), nums)
    model = e.get("model") or e.get("pickupId") or h.group(6)
    rest = seg[h.end():]
    if e.get("type") == "camera" and isinstance(e.get("cam"), dict):
        cm = CAM_REST.match(rest)
        if cm:
            rest = ", " + cam_params(e["cam"]) + rest[cm.end():]
        else:
            warnings.append("%s: camera settings in a layout this editor does not rewrite - kept" % e["ref"])
    seg = h.group(1) + "%s, %s, %s%s, \"%s\"" % (x, y, z, nums, model) + rest
    if e.get("type") == "soldier":
        if e.get("team") is not None:
            seg = set_soldier_team(seg, model, e["team"])
        if e.get("weapon"):
            seg = re.sub(r'("Gun\w*", "", ")WEAPON_ID_[A-Z0-9_]+(")', r"\g<1>%s\g<2>" % e["weapon"], seg, count=1)
        if e.get("ai"):
            seg = re.sub(r'(Task_New\(-?\d+, "HumanAI", "", ")AITYPE_[A-Z_0-9]+(")', r"\g<1>%s\g<2>" % e["ai"], seg, count=1)
        if e.get("graph") is not None and str(e["graph"]).isdigit():
            seg = re.sub(r'(Task_New\(-?\d+, "HumanAI", "", "[A-Z_0-9]+", )\d+(\))', r"\g<1>%s\g<2>" % e["graph"], seg, count=1)
        if e.get("patrol") is not None:
            route = e["patrol"]
            am = re.search(r'Task_New\((\d+), "HumanAI", "", "[A-Z_0-9]+", -?\d+\)', seg)
            # the path his AI script walks when idle; the others are alarm routes
            idle = (_by_ref.get(e["ref"]) or {}).get("idlePath")
            if isinstance(idle, int):
                pm = re.search(r'Task_New\((%d), "PatrolPath", "(?:[^"\\]|\\.)*", ' % idle, seg)
            elif idle == "none":
                pm = None           # alarm paths only: a new patrol goes beside them
            else:
                pm = re.search(r'Task_New\((-?\d+), "PatrolPath", "(?:[^"\\]|\\.)*", ', seg)
            if pm:
                p1 = task_end(seg, pm.start())
                old = seg[pm.start():p1]
                last = re.findall(r'"PatrolPathCommand", "(?:[^"\\]|\\.)*", (\d+), -?\d+\)', old)
                terminal = int(last[-1]) if last and int(last[-1]) in (6, 7) else 7
                if route:
                    seg = seg[:pm.start()] + pm.group(0) + EOL + patrol_commands(route, terminal) + ")" + seg[p1:]
                else:
                    seg = cut_task(seg, pm.start(), p1)
                    if am:
                        ai_scripts[int(am.group(1))] = None         # standing guard now
            elif route and am:
                pid_new = take_id()
                seg = (seg[:am.end()] + ", " + EOL + 'Task_New(%d, "PatrolPath", "", ' % pid_new + EOL
                       + patrol_commands(route, 7) + ")" + seg[am.end():])
                ai_scripts[int(am.group(1))] = pid_new           # its script must now patrol
    out_src = out_src[:s0] + seg + out_src[s1:]
    edited += 1

# Weapons an earlier Apply placed were written standing on end (0, 0, heading):
# lay them on their side like the shipped ones.
relaid = 0
for o in WORLD:
    if o.get("qtype") != "GunPickup" or id(o) not in ADDED or not o.get("ref"):
        continue
    m = find_ref(out_src, o["ref"])
    if not m:
        continue
    s0 = m.start()
    s1 = task_end(out_src, s0)
    h = HEAD.match(out_src[s0:s1])
    vals = re.findall(NUM, h.group(5)) if h else []
    if len(vals) != 3 or float(vals[0]) != 0 or float(vals[1]) != 0:
        continue
    pose = pickup_pose(h.group(6), float(vals[2]))
    if pose[1] == 0:
        continue
    seg = out_src[s0:s1]
    seg = h.group(1) + "%s, %s, %s, %s, %s, %s, \"%s\"" % (h.group(2), h.group(3), h.group(4),
                                                         pose[0], pose[1], pose[2], h.group(6)) + seg[h.end():]
    out_src = out_src[:s0] + seg + out_src[s1:]
    relaid += 1
if relaid:
    reactions.append("%d weapon pickup(s) placed earlier now lie on their side" % relaid)

# Guards an earlier Apply created have scripts with no alarm behaviour: upgrade
# them once (a script that already handles AIEVENT_ALARMON is left alone).
for o in WORLD:
    if o.get("type") != "soldier" or id(o) not in ADDED or o.get("id") not in _soldier_ai:
        continue
    aid, gid = _soldier_ai[o["id"]]
    cur = ai_scripts.get(aid)
    if isinstance(cur, dict):
        continue
    old = script_text(aid)
    if aid not in ai_scripts and old is not None and "AIEVENT_ALARMON" in old:
        continue
    out_node = exit_node(gid, o["x"], o["y"], o["z"])
    control = alarm_control_near(o["x"], o["y"])
    if out_node is None and control is None:
        continue
    if aid in ai_scripts:
        idle = cur
    else:
        mi = re.search(r"AIEVENT_IDLE\s*\)\s*\{\s*AIAction_Patrol\(\s*(\d+)", old or "")
        idle = int(mi.group(1)) if mi else None
    apid = None
    if out_node is not None:
        sm = re.search(r'Task_New\(%d, "HumanSoldier", ' % o["id"], out_src)
        am = sm and re.search(r'Task_New\(%d, "HumanAI", "", "[A-Z_0-9]+", \d+\)' % aid, out_src[sm.start():])
        if am:
            apid = take_id()
            at = sm.start() + am.end()
            out_src = out_src[:at] + ", " + EOL + alarm_path_task(apid, out_node) + out_src[at:]
            reactions.append("%s (placed earlier) runs out on the alarm: node %d, then %d"
                             % ((o.get("name") or "guard",) + tuple(out_node)))
    ai_scripts[aid] = {"idle": idle, "alarm": apid, "control": control}

# A part the mission moved between alarms is taken out of the level's own
# expressions first - before the mission's own blocks go in, which name it again.
for _term in MOVED_PARTS:
    out_src = re.sub(re.escape(_term) + r"\b", "0", out_src)

# The marker stays behind our blocks until the objectives are in: a level with
# no list of its own gets ours there, inside the task tree with the rest.
out_src = out_src.replace(MARKER, "".join(blocks) + MARKER, 1)

# The AIGraph task records node count, capacity and edge count. If those stop
# matching the graph file the engine is loading, it reads the file wrong.
for gid, g in edited_graphs.items():
    out_src = GE.graphdata_counts(out_src, gid, len(g.nodes), len(g.edges), g.max_nodes)

# ---------------------------------------------------------------- write
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "ai").mkdir(exist_ok=True)
for f in (OUT / "ai").glob("*.qsc"):
    f.unlink()
(OUT / "graphs").mkdir(exist_ok=True)
for f in (OUT / "graphs").glob("*.dat"):
    f.unlink()


# ---- objectives and labels, part 2: edits in place once the script is assembled
def _quoted_spans(text, start, end):
    """(start, end) of every "..." string inside text[start:end]."""
    spans, j, open_at = [], start, None
    while j < end:
        if text[j] == '"' and (j == 0 or text[j - 1] != "\\"):
            if open_at is None:
                open_at = j
            else:
                spans.append((open_at, j + 1))
                open_at = None
        j += 1
    return spans


EMPTY_SLOTS = ", ".join(['"", -1, "", ""'] * 6)
if OBJ_TASK_IDS.get("slots"):
    # The level's own numbered markers carry the level's numbering. The mission's
    # are written over them where there are enough, so the map computer's list of
    # 32 does not grow; any left over are switched off, and any still needed are
    # added below.
    spare = [(m.start(), task_end(out_src, m.start())) for m in HILIGHT.finditer(out_src)
             if "COMPUTER:h_" in out_src[m.start():task_end(out_src, m.start())]]
    reuse = min(len(spare), len(MARK_TASKS))
    for i in range(len(spare) - 1, -1, -1):
        a, b = spare[i]
        if i < reuse:
            out_src = out_src[:a] + MARK_TASKS[i] + out_src[b:]
        else:
            seg = out_src[a:b]
            sp = [x for x in re.finditer(r'"((?:[^"\\]|\\.)*)"', seg)]
            if len(sp) > 2:
                out_src = out_src[:a + sp[2].start()] + '"0"' + out_src[a + sp[2].end():]
    MARK_TASKS = MARK_TASKS[reuse:]
    if OBJ_MARKS:
        report.append("map computer markers: %d (%d written over the level's own, %d added)"
                      % (len(OBJ_MARKS[:6]), reuse, len(MARK_TASKS)))
    # The mission's list replaces the level's own, in the level's own task: the
    # map computer lists that task, and the numbers beside the objectives are
    # the order it holds them in. A level can carry several lists, each taking
    # over when its "Objectives Valid" expression comes true (level 3 swaps
    # its list once Priboi has moved); the rest are switched off and emptied,
    # so nothing of the level's can come back over ours.
    defs = list(re.finditer(r'Task_New\((-?\d+), "DefineComputerObjective", ', out_src))
    if defs:
        first = defs[0]
        for m in reversed(defs):
            end = task_end(out_src, m.start())
            sp = _quoted_spans(out_src, m.start(), end)
            name = out_src[sp[1][0]:sp[1][1]] if len(sp) > 1 else '""'
            if m.start() == first.start():
                body = '%s, "", %s' % (name, ", ".join(OBJ_TASK_IDS["slots"]))
                report.append("the mission's %d objective(s) go in the level's own list (task %s)"
                              % (len([x for x in OBJ_TASK_IDS["slots"] if not x.startswith('"", -1')]), m.group(1)))
            else:
                body = '%s, "0", %s' % (name, EMPTY_SLOTS)
            out_src = out_src[:m.end()] + body + ")" + out_src[end:]
    else:
        # no list of its own (an empty map): add one where our blocks went. Not
        # beside LevelFlow - every level has it as a statement of its own, after
        # the task tree, where a second task is a syntax error.
        # (An empty "Objectives Valid" means always.)
        did = take_id()
        blocks_late = 'Task_New(%d, "DefineComputerObjective", "Mission Studio", "", %s)' % (did, ", ".join(OBJ_TASK_IDS["slots"]))
        out_src = out_src.replace(MARKER, blocks_late + ", " + EOL, 1)
        report.append("the mission's objectives go in a new list (this level ships none)")
out_src = out_src.replace(MARKER, "", 1)
if OBJ_TASK_IDS.get("done") or EVENT_FAILS:
    lf = re.search(r'Task_New\(-?\d+, "LevelFlow"', out_src)
    if lf:
        sp = _quoted_spans(out_src, lf.start(), task_end(out_src, lf.start()))
        if len(sp) >= 4:
            base_failed = out_src[sp[3][0] + 1:sp[3][1] - 1].strip() or "FALSE"
            fails = (OBJ_TASK_IDS.get("fails") or []) + EVENT_FAILS
            failed = "(%s) || %s" % (base_failed, " || ".join(fails))
            out_src = out_src[:sp[3][0]] + '"%s"' % failed + out_src[sp[3][1]:]
            if OBJ_TASK_IDS.get("done"):
                complete = "StatusMessage_%d.nTicksSinceFinishedDisplay > 1 * GAME_FREQUENCY" % OBJ_TASK_IDS["done"]
                out_src = out_src[:sp[2][0]] + '"%s"' % complete + out_src[sp[2][1]:]
                report.append("mission complete when all %d objective(s) are done" % len([k for k in LANG["objectives.res"]]))
    else:
        warnings.append("this level has no LevelFlow task - objectives show and events fire, but they won't end the mission")

# ---------------------------------------------------------------- mission settings
# plan["settings"]: a time limit, rain or snow, haze. Each rewrites a task every
# level ships (LevelFlow, FlatSky) or adds the one it may lack (RainEffect), in
# place, so the level keeps everything else it had. Parameters as the levels
# declare them (docs/TASK-PARAMETERS.md).
SETTINGS = plan.get("settings") or {}


def _settings(text):
    # a time limit: LevelFlow's "Interface timer enabled" and "Max level play time"
    # (level 7 ships with 1200 s), right after its Failed expression
    # The game's own "Max level play time" only counts (in its small font); it does
    # not end the mission (found in game 2026-09-18). So the mission keeps its own
    # clock: a LevelTimer from the start, messages as time runs short, and at zero
    # a "Time is up" message LevelFlow fails on, as an event's failure does.
    tl = int(float(SETTINGS.get("timeLimit") or 0))
    if tl > 0:
        lf = re.search(r'Task_New\(-?\d+, "LevelFlow"', text)
        sp = _quoted_spans(text, lf.start(), task_end(text, lf.start())) if lf else []
        m = re.compile(r'\s*,\s*(TRUE|FALSE|0|1)\s*,\s*(%s)' % NUM).match(text, sp[3][1]) if len(sp) >= 4 else None
        if not lf:
            warnings.append("this level has no LevelFlow task - no time limit")
        elif not m:
            warnings.append("the level's LevelFlow has a layout this editor does not rewrite - no time limit")
        else:
            shown = SETTINGS.get("showTimer", True) is not False
            cid, fid = take_id(), take_id()
            tasks = ['Task_New(%d, "LevelTimer", "Mission clock", 0, 0, 0, 0, 0, 0, "1", "", FALSE)' % cid]
            for i, (left, words) in enumerate(((300, "5 minutes left"), (60, "1 minute left"), (10, "10 seconds left"))):
                if tl - left < 15:
                    continue
                key = PREFIX + "T%d" % i
                LANG["messages.res"][key] = words
                tasks.append('Task_New(%d, "StatusMessage", "Time left", 0, 0, 0, 0, 0, 0, "LevelTimer_%d.nTick > %d*GAME_FREQUENCY", '
                             '"%s", "", "message", TRUE, FALSE, 3.0)' % (take_id(), cid, tl - left, key))
            LANG["messages.res"][PREFIX + "TUP"] = "Time is up"
            tasks.append('Task_New(%d, "StatusMessage", "Time is up", 0, 0, 0, 0, 0, 0, "LevelTimer_%d.nTick > %d*GAME_FREQUENCY", '
                         '"%s", "", "fail", TRUE, FALSE, 2.0)' % (fid, cid, tl, PREFIX + "TUP"))
            # the countdown on screen, and the limit the game itself keeps
            text = text[:sp[3][1]] + ", %s, %.1f" % ("TRUE" if shown else "FALSE", tl) + text[m.end():]
            # LevelFlow fails when the last message has shown
            old = text[sp[3][0] + 1:sp[3][1] - 1].strip() or "FALSE"
            text = text[:sp[3][0]] + '"(%s) || StatusMessage_%d.nTicksSinceFinishedDisplay > 1 * GAME_FREQUENCY"' % (old, fid) + text[sp[3][1]:]
            at = task_end(text, lf.start())
            text = text[:at] + "".join(", " + EOL + t for t in tasks) + text[at:]
            report.append("time limit %d:%02d%s, the mission fails when it runs out" % (tl // 60, tl % 60, ", on screen" if shown else ""))
    # rain or snow: RainEffect (Is Rain, Traceline start, Traceline end, Is Active, Rain Alpha)
    fall = SETTINGS.get("fall") or ""
    if fall in ("none", "rain", "snow"):
        alpha = max(0.03, min(0.4, float(SETTINGS.get("heavy") or 0.13)))
        task = 'Task_New(-1, "RainEffect", "", %s, 50.0, 20.0, "%s", %s)' % (
            "FALSE" if fall == "snow" else "TRUE", "0" if fall == "none" else "1", repr(round(alpha, 4)))
        m = re.search(r'Task_New\(-?\d+, "RainEffect"', text)
        if m:
            text = text[:m.start()] + task + text[task_end(text, m.start()):]
        elif fall != "none":
            sky = re.search(r'Task_New\(-?\d+, "FlatSky"', text)
            if sky:
                at = task_end(text, sky.start())
                text = text[:at] + ", " + EOL + task + text[at:]
                if 'Task_DeclareParameters("RainEffect"' not in text:
                    last = [d.end() for d in re.finditer(r'Task_DeclareParameters\("\w+"[^;]*\);', text)]
                    decl = ('Task_DeclareParameters("RainEffect", "Is Rain", "bool8", "Traceline start", "Real32", '
                            '"Traceline end", "Real32", "Is Active", "VarString", "Rain Alpha", "Real32");')
                    at = last[-1] if last else 0
                    text = text[:at] + EOL + decl + text[at:]
            else:
                warnings.append("this level has no sky task to put rain in - no %s" % fall)
                fall = ""
        if fall:
            report.append({"none": "no rain or snow", "rain": "rain", "snow": "snow"}[fall] +
                          ("" if fall == "none" else " (%.2f)" % alpha))
    # haze: FlatSky's Fog Amount and Distance, between the clearest level (5:
    # 0.975, 250) and the thickest (3 and 9: 0.907, 40). To be confirmed in game.
    hz = SETTINGS.get("haze")
    if hz is not None and hz != "":
        t = max(0.0, min(1.0, float(hz)))
        sky = re.search(r'Task_New\(-?\d+, "FlatSky", "(?:[^"\\]|\\.)*", (%s), (%s), (%s)' % (NUM, NUM, NUM), text)
        if sky:
            amount, dist = 0.975 + (0.9067 - 0.975) * t, 250.0 + (40.0 - 250.0) * t
            text = (text[:sky.start(1)] + repr(round(amount, 4)) + text[sky.end(1):sky.start(3)] +
                    repr(round(dist, 1)) + text[sky.end(3):])
            report.append("haze %d%%" % round(t * 100))
    return text


# ---------------------------------------------------------------- painted ground
# plan["paint"]: [[ix, iy, material], ...], 1 m cells on the world grid. The game
# paints a material over an octree cube wherever a bit of its mask is set
# (TextureModifier: Position, Level, Material Index, Bitmap ID, Size, isEdit; the
# masks in terrain/terrain.bit: 256 headers of 12 bytes, then each mask as
# size*size bits, least significant bit first, row by row from the cube's
# south-west corner - see studio/extract/ground.py). One 64x64 mask per level-13
# cube (64 m, 1 m a bit) and material, and a TextureModifier for it after the
# level's own, which it paints over. The slot gets its own terrain.bit.
PAINT = [p for p in (plan.get("paint") or []) if isinstance(p, list) and len(p) >= 3 and int(p[2]) >= 0]
BASE_BIT = GAME / "missions" / "location0" / ("level%d" % LV) / "terrain" / "terrain.bit"
PAINT_LOD, PAINT_SIZE = 13, 64


def _read_bit(path):
    b = path.read_bytes()
    heads = [list(struct.unpack_from("<III", b, i * 12)) for i in range(256)]
    items, off = {}, 256 * 12
    for i, h in enumerate(heads):
        if h[2]:
            n = h[2] * h[2] // 8
            items[i] = bytes(b[off:off + n])
            off += n
    return heads, items


def _paint(text):
    """(text with the TextureModifier tasks, terrain.bit bytes or None)."""
    if not PAINT:
        return text, None
    if not BASE_BIT.exists():
        warnings.append("this level has no ground texture masks - the painted ground is left out")
        return text, None
    last = [m.start() for m in re.finditer(r'Task_New\(-?\d+, "TextureModifier"', text)]
    if not last:
        warnings.append("this level paints no ground of its own - the painted ground is left out")
        return text, None
    heads, items = _read_bit(BASE_BIT)
    cube = PAINT_SIZE                       # metres: a level-13 cube
    groups = collections.OrderedDict()
    for ix, iy, mat in sorted((int(p[0]), int(p[1]), int(p[2])) for p in PAINT):
        cx, cy = ix // cube, iy // cube
        mask = groups.setdefault((cx, cy, mat), bytearray(PAINT_SIZE * PAINT_SIZE // 8))
        k = (iy - cy * cube) * PAINT_SIZE + (ix - cx * cube)
        mask[k >> 3] |= 1 << (k & 7)
    used = [i for i, h in enumerate(heads) if h[2]]
    free = [i for i in range(256) if not heads[i][2] and (not used or i > max(used))]
    if len(free) < len(groups):
        warnings.append("terrain.bit has room for %d more masks, the paint needs %d - some is left out" % (len(free), len(groups)))
    lastb = max(used) if used else None
    ptr = heads[lastb][0] + heads[lastb][2] * heads[lastb][2] // 8 if lastb is not None else 0x1000000
    tasks = []
    for (cx, cy, mat), mask in list(groups.items())[:len(free)]:
        bid = free.pop(0)
        heads[bid] = [ptr, 0, PAINT_SIZE]
        items[bid] = bytes(mask)
        ptr += PAINT_SIZE * PAINT_SIZE // 8
        x, y = (cx * cube + cube / 2.0), (cy * cube + cube / 2.0)
        _t = globals().get("_terr")         # only there when the exact ground loaded
        z = _t.z(x, y) if _t is not None else None
        tasks.append('Task_New(-1, "TextureModifier", "Mission paint", %s, %s, %s, %d, %d, %d, %d, FALSE)'
                     % (q(x), q(y), q(z if z is not None else 0.0), PAINT_LOD, mat, bid, PAINT_SIZE))
    at = task_end(text, last[-1])
    text = text[:at] + "".join(", " + EOL + t for t in tasks) + text[at:]
    out = bytearray()
    for h in heads:
        out += struct.pack("<III", *h)
    for i in range(256):
        if heads[i][2]:
            out += items[i]
    report.append("painted ground: %d m² in %d mask(s)" % (len(PAINT), len(tasks)))
    return text, bytes(out)


def _link_camera(text, cid, x, y):
    """Add SCamera_cid.isDetection to the camera control or alarm listening to the
    nearest cameras, or else to the nearest alarm. Returns (text, what it joined)."""
    cams = {o["id"]: o for o in meta.get("objects", []) if o.get("type") == "camera" and o.get("id", -1) >= 0}
    best = None
    for m in re.finditer(r'Task_New\((\d+), "(SCameraControl|AlarmControl)"', text):
        sp = _quoted_spans(text, m.start(), task_end(text, m.start()))
        if len(sp) < 8:
            continue
        a, b = sp[7]                 # SCameraControl's detection / AlarmControl's trigger expression
        expr = text[a + 1:b - 1]
        refs = [cams[int(i)] for i in re.findall(r"SCamera_(\d+)\.isDetection", expr) if int(i) in cams]
        if refs:
            rank = (0 if m.group(2) == "SCameraControl" else 1, min(math.hypot(o["x"] - x, o["y"] - y) for o in refs))
        elif m.group(2) == "AlarmControl":
            pos = re.match(r'Task_New\(\d+, "AlarmControl", "(?:[^"\\]|\\.)*", (%s), (%s)' % (NUM, NUM), text[m.start():])
            px, py = (float(pos.group(1)) / SCALE, float(pos.group(2)) / SCALE) if pos else (0.0, 0.0)
            rank = (2, math.hypot(px - x, py - y) if (px or py) else 1e6)
        else:
            continue
        if best is None or rank < best[0]:
            best = (rank, m.group(1), m.group(2), a, b, expr)
    if best is None:
        return text, None
    rank, tid, kind, a, b, expr = best
    if kind == "SCameraControl":
        new = "SCamera_%d.isDetection || %s" % (cid, expr)
    else:
        new = "(!AlarmControl_%s.isAlarm && SCamera_%d.isDetection) || (%s)" % (tid, cid, expr)
    return text[:a] + '"%s"' % new + text[b:], "%s_%s" % (kind, tid)


def _join_shipped_alarm(text, ctl_id, raise_terms, off_terms):
    """Add the mission's cameras and buttons to a level alarm's trigger, and its
    buttons to the EditVariable that holds the alarm on, so they switch it off
    again the way the level's own buttons do."""
    m = re.search(r'Task_New\(%d, "AlarmControl", ' % ctl_id, text)
    if not m:
        return text, "not found"
    sp = _quoted_spans(text, m.start(), task_end(text, m.start()))
    if len(sp) < 9:
        return text, "a layout this editor does not rewrite"
    a, b = sp[7]                                   # Trigger Expression
    old = text[a + 1:b - 1]
    guard = "!AlarmControl_%d.isAlarm" % ctl_id
    if raise_terms:
        gap = r"(?:\s|\\n)*"
        inner = re.match(r"%s!AlarmControl_%d\.isAlarm%s&&%s\((.*)\)%s$" % (gap, ctl_id, gap, gap, gap), old, re.S)
        if inner:
            new = "%s &&\\n((%s) ||\\n%s)" % (guard, inner.group(1), " ||\\n".join(raise_terms))
        elif old.strip():
            new = "(%s) ||\\n(%s && (%s))" % (old, guard, " ||\\n".join(raise_terms))
        else:
            new = "%s &&\\n(%s)" % (guard, " ||\\n".join(raise_terms))
        text = text[:a] + '"%s"' % new + text[b:]
    if off_terms:
        # the alarm's memory: EditVariable_V.nValue == 1 keeps it ringing
        keep = text[_quoted_spans(text, m.start(), task_end(text, m.start()))[8][0] + 1:
                    _quoted_spans(text, m.start(), task_end(text, m.start()))[8][1] - 1]
        vm = re.search(r"EditVariable_(\d+)\.nValue", keep)
        if vm:
            em = re.search(r'Task_New\(%s, "EditVariable", ' % vm.group(1), text)
            if em:
                esp = _quoted_spans(text, em.start(), task_end(text, em.start()))
                if len(esp) >= 4:
                    sa, sb = esp[3]                # the Sub expression
                    sub = text[sa + 1:sb - 1]
                    add = "EditVariable_%s.nValue == 1 && AlarmControl_%d.isAlarm && (%s)" % (
                        vm.group(1), ctl_id, " || ".join(off_terms))
                    text = text[:sa] + '"%s"' % ((sub + " ||\\n" + add) if sub.strip() else add) + text[sb:]
    return text, None


for _key in sorted(set(list(ALARM_TRIGGER) + list(ALARM_SILENCE))):
    _cid = alarm_ctl_id(_key)
    if _cid is None or _key in ALARM_IDS:
        continue                                   # the mission's own were written whole
    out_src, why = _join_shipped_alarm(out_src, _cid, ALARM_TRIGGER.get(_key) or [], ALARM_SILENCE.get(_key) or [])
    if why:
        warnings.append("alarm %d: %s - the mission's parts are not wired to it" % (_cid, why))
    else:
        report.append("alarm %d: %d of the mission's part(s) raise it%s"
                      % (_cid, len(ALARM_TRIGGER.get(_key) or []),
                         ", %d switch it off" % len(ALARM_SILENCE[_key]) if ALARM_SILENCE.get(_key) else ""))

for cid, cx, cy in CAM_LINKS:
    out_src, joined = _link_camera(out_src, cid, cx, cy)
    if joined:
        report.append("camera SCamera_%d raises the alarm through %s" % (cid, joined))
    else:
        warnings.append("camera SCamera_%d: no alarm to raise" % cid)

for _ref, (_locked, _open, _pick) in DOOR_SET.items():
    _m = find_ref(out_src, _ref)
    if not _m:
        warnings.append("could not find the door %s to lock" % _ref)
        continue
    _end = task_end(out_src, _m.start())
    _sp = _quoted_spans(out_src, _m.start(), _end)
    if len(_sp) < 6:
        warnings.append("the door %s has a layout this editor does not rewrite - left as it is" % _ref)
        continue
    # from the back, so the spans in front stay where they are
    if _open:
        _old = out_src[_sp[4][0] + 1:_sp[4][1] - 1].strip()
        _new = "(%s) || (%s)" % (_old, _open) if _old and _old != "0" else _open
        out_src = out_src[:_sp[4][0]] + '"%s"' % _new + out_src[_sp[4][1]:]
    if _locked is not None:
        out_src = out_src[:_sp[3][0]] + '"%s"' % _locked + out_src[_sp[3][1]:]
    if _pick:
        _pm = re.compile(r'(,\s*%s\s*,\s*%s\s*,\s*)(TRUE|FALSE)(\s*,\s*)(%s)(\s*,\s*)$' % (NUM, NUM, NUM)).search(out_src, _sp[2][1], _sp[3][0])
        if _pm:
            out_src = out_src[:_pm.start(2)] + "TRUE" + _pm.group(3) + "%.1f" % _pick + out_src[_pm.end(4):]
        else:
            warnings.append("the door %s: its lock settings are in a layout this editor does not rewrite" % _ref)

for _ref, _nid in ANCHOR_NEW:
    _m = find_ref(out_src, _ref)
    if _m:
        out_src = out_src[:_m.start()] + ('Task_New(%d,' % _nid) + out_src[_m.start() + len("Task_New(%s," % _m.group(1)):]
    else:
        warnings.append("could not give %s an id for a map computer marker" % _ref)

if LABEL_TASKS or MARK_TASKS:
    last = [m.start() for m in re.finditer(r'Task_New\(-?\d+, "ComputerHilight"', out_src)][-1]
    at = task_end(out_src, last)
    out_src = out_src[:at] + "".join(", " + EOL + t for t in MARK_TASKS + LABEL_TASKS) + out_src[at:]
    n_hil = len(re.findall(r'Task_New\(-?\d+, "ComputerHilight"', out_src))
    if n_hil > HILIGHT_MAX:
        errors.append("the map computer would hold %d markers and labels; it holds %d" % (n_hil, HILIGHT_MAX))

if FLAT_PATCHES:
    _targets = [pd["target"] for pd in list(PADS.values()) + AREA_PADS if pd.get("target") is not None]
    _targets = _targets or [pd["low"] for pd in list(PADS.values()) + AREA_PADS]
    if not _targets:
        # no pad to take it from: the ground in the middle of what the brush (1 m
        # cells) and the big shapes (4 m cells) moved. Ground shaped with big
        # shapes alone took min() of an empty brush here (level 7, 2026-09-21).
        _pts = list(BRUSH) + [(ix * FL.SCULPT_M, iy * FL.SCULPT_M) for ix, iy in SCULPT]
        _mid = _surface.terrain.z((min(x for x, _ in _pts) + max(x for x, _ in _pts)) / 2.0,
                                  (min(y for _, y in _pts) + max(y for _, y in _pts)) / 2.0) if _pts else None
        _targets = [_mid or 0.0]
    _task_z = min(_targets) * SCALE
    out_src = FL.add_tasks(out_src, FLAT_PATCHES, _task_z, task_end, EOL)
out_src = _settings(out_src)
out_src, _bit = _paint(out_src)
(OUT / "objects.qsc").write_bytes(out_src.encode("latin1"))
# the mission's own strings, for the installer to put in the language files
(OUT / "language.json").write_text(json.dumps(LANG, indent=1), encoding="utf-8")
# the slot's terrain.hmp: the base level's, plus this plan's pads (so a pad the
# plan no longer has is gone again)
(OUT / "terrain").mkdir(exist_ok=True)
# the terrain mesh, where this plan rebuilt it (_shape_terrain saved it); none
# staged means the slot gets its base level's own mesh back
for _f in ("terrain.ctr", "terrain.cmd", "terrain.lmp"):
    if (OUT / "terrain" / _f).exists() and not (MESH and (_f != "terrain.lmp" or MESH.get("lit"))):
        (OUT / "terrain" / _f).unlink()
_hmp_out = OUT / "terrain" / "terrain.hmp"
_hmp_gone = OUT / "terrain" / "terrain.hmp.remove"
for _f in (_hmp_out, _hmp_gone):
    if _f.exists():
        _f.unlink()
if FLAT_PATCHES:
    FL.add_items(FLAT_HMP, FLAT_PATCHES)
    FL.write_hmp(_hmp_out, FLAT_HMP)
elif BASE_HMP.exists():
    _hmp_out.write_bytes(BASE_HMP.read_bytes())
else:
    _hmp_gone.write_text("the base level has no height maps and this plan adds none")
# the slot's terrain.bit: the base level's masks, plus this plan's paint (so
# paint the plan no longer has is gone again)
_bit_out = OUT / "terrain" / "terrain.bit"
if _bit is not None:
    _bit_out.write_bytes(_bit)
elif BASE_BIT.exists():
    _bit_out.write_bytes(BASE_BIT.read_bytes())
elif _bit_out.exists():
    _bit_out.unlink()
# The mission's own textures: pictures the plan carries (PNG, base64) that go in
# the place of the level's. They are written as the game's own format here, and
# laid into the slot by studio/build/install.py; one the plan no longer has is
# the level's own again.
_tex = plan.get("textures") or []
if _tex or (OUT / "textures" / TEX.STAGE_LIST).exists():
    _entries = []
    for _t in _tex[:64]:
        _png = (_t.get("png") or "")
        _png = _png.split(",", 1)[1] if _png.startswith("data:") else _png
        try:
            _raw = base64.b64decode(_png, validate=True)
        except (ValueError, binascii.Error):
            errors.append("texture %s: its picture is not readable" % _t.get("name"))
            continue
        _entries.append({"name": _t.get("name") or "", "png": _raw,
                         "bpp": 4 if str(_t.get("format") or "") in ("bgra", "argb8888", "4") else 2})
    try:
        _names = TEX.stage(OUT, _entries, log=lambda m: report.append(m))
        if _names:
            report.append("the mission's own textures: %s" % ", ".join(_names))
    except ValueError as e:
        errors.append("textures: %s" % e)

# models the slot must receive from other levels before this script can show them
_needed = OUT / "models_needed.json"
if IMPORTS:
    json.dump(sorted(IMPORTS), _needed.open("w"))
elif _needed.exists():
    _needed.unlink()

# Stage EVERY graph of the base level, edited or not. The script's AIGraph counts
# come from the base level, so the slot must receive the base level's graphs too -
# otherwise a slot that got extra nodes from an earlier plan would disagree with
# a script built fresh from a shipped level.
staged_graphs = []
if BASE_GRAPHS.is_dir():
    for gp in sorted(BASE_GRAPHS.glob("graph*.dat")):
        m = re.fullmatch(r"graph(\d+)\.dat", gp.name)
        if not m:
            continue
        gid = m.group(1)
        dst = OUT / "graphs" / gp.name
        if gid in edited_graphs:
            dst.write_bytes(edited_graphs[gid].serialise(_edited_tables[gid]))
        else:
            dst.write_bytes(gp.read_bytes())
        staged_graphs.append(gp.name)

def ai_script(spec):
    """An AI script in the shape 825 of the game's 855 have: CREATE -> default (+ alarm
    control), IDLE -> patrol, ALARMON -> alarm path, anything else -> default."""
    if not isinstance(spec, dict):
        spec = {"idle": spec}
    if "raw" in spec:
        return spec["raw"]              # the level's own script (with its sight set, or put back)
    idle, alarm, control = spec.get("idle"), spec.get("alarm"), spec.get("control")
    ev = "if(AIFunction_GetCurrentEventType() == %s)\n"
    out = [ev % "AIEVENT_CREATE", "{\n", "\tAIFunction_DefaultHandler();\n"]
    if control:
        out.append("\tAIFunction_SetAlarmControlID(%d);\n" % control)
    # how far and how wide he sees, as the shipped scripts set it (97 and 10 of them)
    if spec.get("sees"):
        out.append("\tAIFunction_SetViewLength(%d);\n" % max(1, min(300, int(spec["sees"]))))
    if spec.get("fov"):
        out.append("\tAIFunction_SetViewGamma(%d);\n" % max(10, min(360, int(spec["fov"]))))
    out.append("}\n")
    branches = []
    if idle:
        branches.append(("AIEVENT_IDLE", "AIAction_Patrol(%d, 0, AIACTIONFLAG_NONE);" % idle))
    if alarm:
        branches.append(("AIEVENT_ALARMON", "AIAction_Patrol(%d, 0, AIACTIONFLAG_NONE);" % alarm))
    tail = "AIFunction_DefaultHandler();"

    def nest(bs, depth):
        pad = "\t" * depth
        if not bs:
            return pad + tail + "\n"
        name, act = bs[0]
        return (pad + ev % name + pad + "{\n" + pad + "\t" + act + "\n" + pad + "}\n" +
                pad + "else\n" + pad + "{\n" + nest(bs[1:], depth + 1) + pad + "}\n")
    out += ["else\n", "{\n", nest(branches, 1), "}\n"]
    return "".join(out)


# A level guard's own sight (sees / fov on his edit): his script as the level has
# it - or as this build rewrote it - with SetViewLength / SetViewGamma in its
# CREATE handler, as 97 and 10 of the shipped scripts set them. Nothing else of
# his behaviour changes. A level guard whose script an earlier Apply rewrote
# and who needs no change now gets the level's own back.
def _with_sight(text, sees, fov):
    m = re.search(r"AIEVENT_CREATE\s*\)\s*\{", text or "")
    if not m:
        return None
    depth, j = 1, m.end()
    while j < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        j += 1
    block = re.sub(r"\s*AIFunction_SetView(?:Length|Gamma)\([^)]*\);", "", text[m.end():j - 1]).rstrip()
    add = ("\n\tAIFunction_SetViewLength(%d);" % max(1, min(300, int(sees))) if sees else "") + \
          ("\n\tAIFunction_SetViewGamma(%d);" % max(10, min(360, int(fov))) if fov else "")
    return text[:m.end()] + block + add + "\n" + text[j - 1:]


_level_ai = {aid for aid, _g in _soldier_ai.values()}
for _e in EDITS:
    if _e.get("type") != "soldier" or not (_e.get("sees") or _e.get("fov")):
        continue
    _o = _world_by_ref.get(_e["ref"]) or {}
    if _o.get("id", -1) not in _soldier_ai:
        continue
    _aid = _soldier_ai[_o["id"]][0]
    _cur = ai_scripts.get(_aid)
    if _cur is not None and not (isinstance(_cur, dict) and "raw" in _cur):
        _cur = dict(_cur) if isinstance(_cur, dict) else {"idle": _cur}
        _cur.update({"sees": _e.get("sees"), "fov": _e.get("fov")})
        ai_scripts[_aid] = _cur
    else:
        _txt = _with_sight(script_text(_aid), _e.get("sees"), _e.get("fov"))
        if _txt is None:
            warnings.append("%s: his script has a shape this editor does not change - his sight stays as it was"
                            % (_e.get("name") or "a guard"))
            continue
        ai_scripts[_aid] = {"raw": _txt}
    reactions.append("%s sees %s, %s wide" % (_e.get("name") or "a guard",
                                                "%d m" % _e["sees"] if _e.get("sees") else "as his type",
                                                "%d°" % _e["fov"] if _e.get("fov") else "as his type"))
try:
    _prev_own = set(json.load(open(SLOT_DIR / "ai" / "_mission_studio.json")).get("aiScripts", [])) \
        if SLOT_DIR is not None else set()
except (OSError, ValueError):
    _prev_own = set()
for _aid in sorted(_prev_own & _level_ai):
    if _aid not in ai_scripts:
        _orig = script_text(_aid)
        if _orig:
            ai_scripts[_aid] = {"raw": _orig}

# Every HumanAI in the FINAL script needs a script, not just the ones this plan
# created. When a plan is built on top of a custom slot, the previous plan's
# soldiers are baked into the base level - their AI ids are still referenced but
# this run did not generate them. Scan the output and fill any gaps.
OWN_SCRIPTS = sorted(ai_scripts)   # generated for this plan's placements
GAME_AI = arg("--game-ai") or (str(SLOT_DIR / "ai") if SLOT_DIR is not None else None)
have = set()
# Scripts that already exist are never regenerated: the slot's own, and the base
# level's shipped ones. Checking only the slot (or nothing, when --game-ai is not
# passed) made every shipped HumanAI look orphaned, and they were rewritten as
# generic templates - destroying their real behaviour.
for _dir in (GAME_AI, GAME / "missions" / "location0" / ("level%d" % LV) / "ai"):
    if _dir and pathlib.Path(_dir).is_dir():
        for f in pathlib.Path(_dir).glob("*.qvm"):
            if f.stem.isdigit():
                have.add(int(f.stem))

adopted = 0
for m in re.finditer(r'Task_New\((\d+), "HumanAI", "", "[A-Z_0-9]+", \d+\)(\s*,\s*'
                     r'Task_New\((\d+), "PatrolPath")?', out_src, re.S):
    aid = int(m.group(1))
    if aid in ai_scripts or aid in have:
        continue
    ai_scripts[aid] = int(m.group(3)) if m.group(3) else None
    adopted += 1

for aid, spec in ai_scripts.items():
    body = ai_script(spec)
    (OUT / "ai" / ("%d.qsc" % aid)).write_bytes(body.replace("\n", EOL).encode("latin1"))

# Manifest of exactly which AI scripts this plan owns. The installer removes the
# previous plan's scripts by reading the manifest it left behind - never by id
# range. Level 1 ships AI scripts numbered 3001-3333, so "delete everything >=
# 3000" wipes the game's own files and the level then fails to load with
# "No AI script in HumanAI #3091".
json.dump({"aiScripts": OWN_SCRIPTS, "plan": NAME, "level": LV},
          (OUT / "ai" / "_manifest.json").open("w"), indent=2)

print('PLAN "%s"  level %d  mode %s' % (NAME, LV, MODE))
print("  inserted into: %s" % anchor_desc)
print("  %d soldier(s), %d pickup(s), %d object(s)" % (len(soldiers), len(pickups), len(objects)))
print("  task ids allocated: %s" % (sorted(i for i in used if i not in set(meta["usedIds"])) or "none"))
print("  ai scripts: %s%s" % (sorted(ai_scripts) or "none",
      ("  (%d adopted from the base level)" % adopted) if adopted else ""))
if MODE == "new":
    print("  shipped soldiers removed: %d" % removed)
if dropped:
    print("  shipped objects removed by the plan: %d" % dropped)
if edited:
    print("  shipped objects edited in place: %d" % edited)
if IMPORTS:
    print("  models to import into the slot: %s" % ", ".join(sorted(IMPORTS)))
if FLAT_PATCHES:
    def _area_text(pd):
        m = pd.get("mode")
        if m == "level":
            return "level %.1f m" % pd["target"]
        if m in ("raise", "lower"):
            return "%+.1f m" % pd["delta"]
        if m == "smooth":
            return "smooth %.0f m" % pd["radius"]
        if m == "remove":
            return "taken down to its surroundings"
        return "ramp %.1f -> %.1f m" % (pd["z0"], pd["z1"])
    _what = ["%s %.1f m" % (pd["name"], pd["high"] - pd["low"]) for pd in PADS.values()]
    _what += ["%s: %s" % (pd["name"], _area_text(pd)) for pd in AREA_PADS]
    if BRUSH:
        _what.append("brush strokes over %d m2" % len(BRUSH))
    if SCULPT:
        _what.append("big shapes over %d m2 (%.0f m at the most)"
                     % (len(SCULPT) * int(FL.SCULPT_M ** 2), max(abs(v) for v in SCULPT.values())))
    print("  shaped the ground under %d building(s) and %d area(s): %s (%d height map%s)" % (
        len(PADS), len(AREA_PADS), ", ".join(_what),
        len(FLAT_PATCHES), "" if len(FLAT_PATCHES) == 1 else "s"))
    _kept = [k for k in KEEP if any(k["box"][0] <= pd["box"][1] and k["box"][1] >= pd["box"][0] and
                                     k["box"][2] <= pd["box"][3] and k["box"][3] >= pd["box"][2] for pd in AREA_PADS)
             or (BRUSH and any(k["box"][0] <= ix <= k["box"][1] and k["box"][2] <= iy <= k["box"][3] for ix, iy in BRUSH))]
    if _kept:
        print("  the ground under %d thing(s) standing in the shaped areas is kept as it was" % len(_kept))
    if NODE_SHIFTS:
        print("  navmesh nodes moved with the ground: %d" % len(NODE_SHIFTS))
for ed in node_edits:
    if ed.get("action") == "remove" and "_linked" in ed:
        print("  removed node %s from graph %s (was linked to %s)" % (ed["id"], ed["graph"], ed["_linked"]))
    elif ed.get("action") == "move":
        if not ed.get("_ground"):
            print("  moved node %s on graph %s to %.1f, %.1f, %.1f" % (ed["id"], ed["graph"], ed["x"], ed["y"], ed["z"]))
for pn in plan_nodes:
    if "_id" in pn:
        print("  new node %d on graph %s at %.1f, %.1f, %.1f  linked to %s"
              % (pn["_id"], pn["graph"], pn["x"], pn["y"], pn["z"], pn["_linked"]))
for line in report + reactions:
    print("  " + line)
for gid, g in edited_graphs.items():
    print("  graph %s now %d nodes / %d edges (capacity %d)"
          % (gid, len(g.nodes), len(g.edges), g.max_nodes))
if staged_graphs:
    print("  graphs staged: %d" % len(staged_graphs))
print("  %s bytes -> %s" % (format(len(out_src), ","), OUT / "objects.qsc"))
for w in warnings:
    print("  ! " + w)
