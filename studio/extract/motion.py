# What moves in a level, and its cutscenes, read from the level's script.
#
#   from studio.extract import motion
#   motion.read(qsc_text, texts) -> {"vehicles": [...], "cutscenes": [...]}
#
# studio/extract/levels.py puts this in each levelN.json as "motion".
#
# Vehicles: every Car, Heli, Plane and Train task. Each moves in one of three
# ways, or stands:
#   drives   AnimTask   a recorded drive: control inputs (throttle, steering, a
#                       helicopter's lift...) with waits in game ticks, 30 a
#                       second (IGI.exe registers GAME_FREQUENCY as 30). It
#                       plays from where the vehicle stands, so it is relative.
#   ai       CarAI      a child of its Car: the game's AI drives it along a
#                       PatrolPath (the route) on an AIGraph of its own (a
#                       vehicle graph, not the guards' walkways).
#   rail     Train      runs along a SplineObj (its RailroadQTaskID), its
#                       carriages as child Trains.
# Most sit inside a ConditionalContainer: its condition is when the vehicle is
# there at all (on the alarm, once some guards are dead...), kept as "when".
#
# Cutscenes: the CutScene tasks, grouped by the ConditionalContainer that runs
# them (one intro, one outro in the shipped levels; never one in mid-mission).
# A CutScene plays its EditCameras in order: a camera with "Smooth to next"
# moves to the next one over its duration; one without holds for its duration,
# then cuts. Durations are seconds. Alpha is the heading, gamma the pitch
# (-pi/2 looks straight down), beta the roll, in radians; FOV is a factor
# (1 normal, below 1 a longer lens). A camera with a link task rides along with
# that thing (its position is where it starts, beside the thing as it stands);
# one with a target keeps turning to look at it. Viewport height 0.7 is the
# letterbox. Subtitles are StatusMessages marked "Cutscene message", sent on a
# timer that runs with the cutscene; the skip key is an EditVariable that
# LevelFlow_GetBreakCutSceneKey() raises, which the intro's condition tests.
import re

from studio.qvm import qsc

SCALE = 4096.0
FREQ = 30.0                     # GAME_FREQUENCY, ticks a second
KINDS = {"Car": "car", "Heli": "heli", "Plane": "plane", "Train": "train"}
SCENE_NAME = re.compile(r"cutsc|intro|outro|opening|ending", re.I)


class _T:
    __slots__ = ("id", "kind", "name", "args", "kids", "parent", "at")


def _val(n):
    if n.kind in ("int", "float", "string"):
        return n.value
    if n.kind == "ident":
        return {"TRUE": True, "FALSE": False}.get(n.value, n.value)
    if n.kind == "unary" and n.value == "-" and n.kids and n.kids[0].kind in ("int", "float"):
        return -n.kids[0].value
    return None


def _task(call, parent, out):
    a = call.kids
    t = _T()
    t.id, t.kind, t.name = _val(a[0]), a[1].value, a[2].value
    t.args, t.kids, t.parent, t.at = [], [], parent, len(out)
    out.append(t)
    for k in a[3:]:
        if k.kind == "call" and k.value == "Task_New":
            t.kids.append(_task(k, t, out))
        else:
            t.args.append(_val(k))
    return t


def tasks(text):
    """Every task of a level script, parents before children, each knowing its
    parent."""
    out = []

    def walk(n):
        if n.kind == "call" and n.value == "Task_New":
            _task(n, None, out)
            return
        for k in n.kids or []:
            walk(k)
    walk(qsc.parse(text))
    return out


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _m(v):
    return round(_num(v) / SCALE, 2)


def _expr(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _ancestors(t):
    p = t.parent
    while p is not None:
        yield p
        p = p.parent


def _when(t):
    """The condition of the nearest ConditionalContainer holding t, and its id."""
    for p in _ancestors(t):
        if p.kind == "ConditionalContainer":
            return _expr(p.args[0] if p.args else ""), p.id
    return "", None


def _scene_box(t):
    """The ConditionalContainer that runs a cutscene: the outermost one named
    like one (level 3 nests "Outro plane in hanger" inside its outro), else the
    nearest."""
    near, named = None, None
    for p in _ancestors(t):
        if p.kind != "ConditionalContainer":
            continue
        near = near or p
        if SCENE_NAME.search(p.name or ""):
            named = p
    return named or near


def _seconds(expr):
    """`X.nTick > 12*GAME_FREQUENCY` -> 12.0; `X.nTick > 1` -> 1/30 s."""
    m = re.search(r"nTick\s*>=?\s*([\d.]+)\s*(\*\s*GAME_FREQUENCY)?", expr or "")
    if not m:
        return None
    v = float(m.group(1))
    return v if m.group(2) else v / FREQ


def _shot(c):
    a = c.args
    # Position(3) Alpha Beta Gamma FOV Duration Link UpdLink Target UpdTarget
    # Smooth TimeOfDay FILTER Noise R G B Shake
    shot = {"name": c.name, "x": _m(a[0]), "y": _m(a[1]), "z": _m(a[2]),
            "a": round(_num(a[3]), 5), "b": round(_num(a[4]), 5), "g": round(_num(a[5]), 5),
            "fov": round(_num(a[6], 1), 3), "dur": round(_num(a[7]), 3),
            "link": a[8] if isinstance(a[8], int) and a[8] >= 0 else None,
            "target": a[10] if isinstance(a[10], int) and a[10] >= 0 else None,
            "smooth": a[12] is True}
    if len(a) > 14 and a[14] and a[14] != "CAMERAFILTER_TYPE_NONE":
        shot["filter"] = str(a[14]).replace("CAMERAFILTER_TYPE_", "").lower()
    if len(a) > 19 and _num(a[19]) > 0:
        shot["shake"] = round(_num(a[19]), 4)
    return shot


def read(text, texts=None):
    texts = texts or {}
    ts = tasks(text)
    ids = {t.id: t for t in ts if isinstance(t.id, int) and t.id >= 0}
    flow = next((t for t in ts if t.kind == "LevelFlow"), None)
    complete = _expr(flow.args[7]) if flow and len(flow.args) > 7 else ""

    # ---- cutscenes, by the container that runs them
    boxes, order = {}, []
    for t in ts:
        if t.kind != "CutScene":
            continue
        box = _scene_box(t)
        key = box.id if box is not None else ("scene", t.id)
        if key not in boxes:
            boxes[key] = {"box": box, "scenes": []}
            order.append(key)
        boxes[key]["scenes"].append(t)
    skip_vars = {t.id for t in ts if t.kind == "EditVariable"
                 and any("BreakCutSceneKey" in str(x) for x in t.args)}
    cutscenes = []
    for key in order:
        box, scenes = boxes[key]["box"], boxes[key]["scenes"]
        cond = _expr(box.args[0]) if box is not None and box.args else ""
        name = (box.name if box is not None else "") or scenes[0].name or ""
        mine = {s.id for s in scenes}
        ends = any(re.search(r"CutScene_%d\.isFinished" % i, complete) for i in mine)
        role = ("outro" if ends or re.search(r"outro|ending", name, re.I)
                else "intro" if re.search(r"intro|opening", name, re.I) else "event")
        skip = [v for v in skip_vars if "EditVariable_%d.nValue" % v in cond]
        out_scenes, start = [], 0.0
        for s in scenes:
            a = s.args
            shots = [_shot(c) for c in s.kids if c.kind == "EditCamera"]
            secs = round(sum(x["dur"] for x in shots), 2)
            out_scenes.append({"id": s.id, "name": s.name, "run": _expr(a[6]),
                               "letterbox": round(_num(a[12], 1), 3), "start": round(start, 2),
                               "seconds": secs, "shots": shots})
            start += secs
        starts = {sc["id"]: sc["start"] for sc in out_scenes}
        # subtitles: sent on a timer that runs with this container, or on one of
        # its CutScenes' own clocks
        timers = {t.id for t in ts if t.kind == "LevelTimer" and box is not None
                  and "ConditionalContainer_%d.isRun" % box.id in _expr(t.args[6] if len(t.args) > 6 else "")}
        subs = []
        for t in ts:
            if t.kind != "StatusMessage" or len(t.args) < 13 or t.args[11] is not True:
                continue
            send = _expr(t.args[6])
            m = re.search(r"(LevelTimer|CutScene)_(\d+)\.nTick", send)
            if not m:
                continue
            ref, rid = m.group(1), int(m.group(2))
            if ref == "LevelTimer" and rid not in timers:
                continue
            if ref == "CutScene" and rid not in starts:
                continue
            at = _seconds(send)
            if at is None:
                continue
            at += starts.get(rid, 0.0) if ref == "CutScene" else 0.0
            key_ = str(t.args[7] or "")
            subs.append({"at": round(at, 2), "dur": round(_num(t.args[12]), 2), "key": key_,
                         "text": texts.get(key_, "")})
        subs.sort(key=lambda s: s["at"])
        actors = []
        if box is not None:
            for t in ts[box.at + 1:]:
                if not any(p is box for p in _ancestors(t)):
                    break
                if t.kind in KINDS or t.kind.startswith("HumanSoldier") or t.kind in ("EditRigidObj", "Building"):
                    if isinstance(t.id, int) and t.id >= 0:
                        actors.append(t.id)
        cutscenes.append({"id": box.id if box is not None else None, "name": name, "role": role,
                          "when": cond, "skip": skip[0] if skip else None, "ends": ends,
                          "seconds": round(start, 2), "scenes": out_scenes, "subtitles": subs,
                          "actors": actors})

    # ---- vehicles
    drives = {}
    for t in ts:
        if t.kind == "AnimTask" and len(t.args) > 9:
            data = t.args[9:]
            pairs = list(zip(data[1::2], data[2::2]))
            ticks = sum(_num(v) for c, v in pairs if c == 32)
            drives.setdefault(t.args[6], []).append(
                {"id": t.id, "run": _expr(t.args[7]), "initial": t.args[8] is True,
                 "seconds": round(ticks / FREQ, 1), "x": _m(t.args[0]), "y": _m(t.args[1]), "z": _m(t.args[2])})
    rails = {}
    for t in ts:
        if t.kind == "SplineObj":
            pts = []
            for w in t.kids:
                if w.kind != "SplineObjWaypoint":
                    continue
                nums = [x for x in w.args if isinstance(x, (int, float)) and not isinstance(x, bool)]
                strs = [i for i, x in enumerate(w.args) if isinstance(x, str)]
                head = w.args[:strs[0]] if strs else w.args
                xyz = [x for x in head if isinstance(x, (int, float)) and not isinstance(x, bool)][-3:]
                if len(xyz) == 3:
                    pts.append([_m(xyz[0]), _m(xyz[1]), _m(xyz[2])])
            rails[t.id] = pts
    scene_of = {}
    for c in cutscenes:
        if c["id"] is not None:
            scene_of[c["id"]] = c["role"]
    vehicles = []
    for t in ts:
        kind = KINDS.get(t.kind)
        if kind is None or (kind == "train" and t.parent is not None and t.parent.kind == "Train"):
            continue
        a = t.args
        when, box = _when(t)
        box_ = _scene_box(t)
        v = {"id": t.id, "kind": kind, "name": t.name, "when": when}
        if box_ is not None and box_.id in scene_of:
            v["cutscene"] = box_.id
        if kind == "train":
            # Position is how far along its track it starts (signed, raw units)
            v.update({"model": a[3], "along": _m(a[0]), "track": a[2], "maxSpeed": _num(a[5]),
                      "carriages": [k.args[3] for k in t.kids if k.kind == "Train" and len(k.args) > 3],
                      "carriageIds": [k.id for k in t.kids if k.kind == "Train" and isinstance(k.id, int) and k.id >= 0]})
            pts = rails.get(a[2]) or []
            if pts:
                v["x"], v["y"], v["z"] = pts[0]
                v["rail"] = pts
        else:
            v.update({"x": _m(a[0]), "y": _m(a[1]), "z": _m(a[2]),
                      "rot": [round(_num(a[3]), 5), round(_num(a[4]), 5), round(_num(a[5]), 5)],
                      "model": a[10] if len(a) > 10 else ""})
            # thrust, speed x3, model, collision, Force Z, open door, then can fire
            if kind in ("car", "heli") and len(a) > 14:
                v["canFire"] = _expr(a[14])
            for k in t.kids:
                if k.kind == "CarAI" and len(k.args) >= 3:
                    g, r = k.args[1], k.args[2]
                    route = ids.get(r)
                    if isinstance(g, int) and g >= 0 and route is not None and route.kind == "PatrolPath":
                        v["ai"] = {"graph": g, "route": r,
                                   "nodes": [c.args[1] for c in route.kids if c.kind == "PatrolPathCommand"
                                             and len(c.args) >= 2 and c.args[0] in (2, 3)]}
                    else:
                        v["parked"] = True      # a stand-in until the real one drives
        if t.id in drives:
            v["drives"] = drives[t.id]
        vehicles.append(v)
    return {"vehicles": vehicles, "cutscenes": cutscenes, "complete": complete}
