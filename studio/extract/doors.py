# The doors and lifts of the game's own buildings, read out of its levels, so
# the studio can place ones that work.
#
# A door in a level is a "Door" task, 23 fields:
#   id, "Door", name, x, y, z, stop x, stop y, slider, alpha, beta, gamma,
#   model, max angle, open time, pickable, pick time, locked, open, close,
#   sound open, sound close, sound moving
# The door slides to (stop x, stop y) in its own frame when it opens; the three
# angles are its orientation, and which of them carries its heading depends on
# the model (a door lying on its side carries it in alpha, as a rifle does).
# Nothing here is invented: a door the studio writes is the game's own numbers
# for that model, with its heading turned to where the user put it.
#
# What this writes (data/doors.json):
#   models   {model: {stop, slider, head (0 alpha, 2 gamma), fixed (the other two
#            angles), openTime, maxAngle, pickTime, locked, open, close, sounds,
#            seen}}    - one entry per door model the game uses
#   buildings {model: {doors: [{model, dx, dy, dz, dh}, ...],
#                      lifts: [{cabin, dx, dy, dz, dh, speed, stops, calls,
#                               inside}, ...],
#                      props: [{model, dx, dy, dz, dh}, ...]}}
#            - what belongs to a building, where it sits in the building's own
#            frame (metres, and dh radians from its heading), so placing the
#            building brings its doors and its lifts
#
# A lift is an "Elevator" task: its cabin model, the SplineObj whose waypoints
# are the floors it stops at, a call switch at each floor and one inside the
# cabin. The studio writes the same tasks back (studio/build/plan.py).
#
#   python -m studio.extract.doors [--game <the reference copy>] [--data <folder>] [--out <file>]
import collections, json, math, pathlib, re, sys

from studio.qvm import source as qvm_source

SCALE = 4096.0
TAU = math.pi * 2
HEAD_SIDE = 1.5708          # beta of a door that lies on its side: its heading is alpha
NEAR = 1.0                  # metres of slack round a building's footprint
CLUSTER = 1.2               # metres: the same doorway in another copy of a building
# not buildings: a collision box, the joint helper, and the like
SKIP_HOMES = {"colbox1", "colbox2", "colbox3", "colbox4", "joint_fixer"}
DOOR_HOME_H = 2.2             # metres: what a door can belong to is at least this tall
MOST_PROPS = 60              # the most a building brings with it (the Guard HQ brings 53;
                            # only the fortress walls and level 14's lift complex go past it)
NEAR_LIFT = 6.0             # metres: a lift shaft this close to a room is its own
LIFT_HOME_M2 = 30.0         # a lift belongs to something at least this big...
LIFT_HOME_H = 3.5           # ... and this tall: a building, not a crate
CALL_OUT, CALL_UP, CALL_IN = 2.6, 1.2, 1.1      # where a button we add ourselves goes
DOOR_MODELS = set()         # filled as the doors are read: a door is not a prop


def _tasks(src, name):
    """Every Task_New(... "name" ...) in the source, whole."""
    out = []
    for m in re.finditer(r'Task_New\(\s*-?\d+\s*,\s*"%s"\s*,' % name, src):
        depth, start = 0, src.index("(", m.start())
        for j in range(start, len(src)):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    out.append(src[m.start():j + 1])
                    break
    return out


def _args(task):
    inner = task[task.index("(") + 1:-1]
    return [a.strip() for a in re.split(r",(?![^()]*\))", inner)]


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# An expression that names another task by id ("Switch_211.isLastPressed") is
# that level's own wiring: it means nothing in a mission of ours, so it is left
# out and the door gets the plain timed close instead.
NAMES_TASK = re.compile(r"[A-Za-z]+_\d+\.")
TIMED_CLOSE = "this.nDoorOpenTicks > 6*GAME_FREQUENCY"


def _expr(e):
    e = (e or "").strip()
    return "" if NAMES_TASK.search(e) else e


def _str(v):
    v = (v or "").strip()
    return v[1:-1] if len(v) >= 2 and v[0] == '"' and v[-1] == '"' else v


def doors_of(src):
    """Every door of one level: position in metres, its slide, its angles, its
    model and how it opens."""
    out = []
    for t in _tasks(src, "Door"):
        a = _args(t)
        if len(a) < 23:
            continue
        out.append({"x": _num(a[3]) / SCALE, "y": _num(a[4]) / SCALE, "z": _num(a[5]) / SCALE,
                    "stop": [round(_num(a[6]), 3), round(_num(a[7]), 3)], "slider": round(_num(a[8]), 3),
                    "orient": [round(_num(a[9]), 4), round(_num(a[10]), 4), round(_num(a[11]), 4)],
                    "model": _str(a[12]), "maxAngle": _num(a[13]), "openTime": _num(a[14]),
                    "pickable": _str(a[15]).upper() == "TRUE", "pickTime": _num(a[16]),
                    "locked": _expr(_str(a[17])), "open": _expr(_str(a[18])), "close": _expr(_str(a[19])),
                    "liftFloor": _lift_floor(_str(a[18])),
                    "sounds": [_str(a[20]), _str(a[21]), _str(a[22])]})
    return out


def _task_by_id(src, tid):
    """The whole Task_New(...) with this id, or None."""
    m = re.search(r'Task_New\(\s*%d\s*,\s*"([A-Za-z0-9_]+)"' % tid, src)
    if not m:
        return None
    for t in _tasks(src, m.group(1)):
        if re.match(r'Task_New\(\s*%d\s*,' % tid, t):
            return t
    return None


def _switch_at(src, tid, cache={}):
    """(x, y, z, heading) of a Switch task, in metres."""
    key = (id(src), tid)
    if key not in cache:
        t = _task_by_id(src, tid)
        a = _args(t) if t else None
        cache[key] = (_num(a[3]) / SCALE, _num(a[4]) / SCALE, _num(a[5]) / SCALE,
                      _num(a[8])) if a and len(a) > 8 else None
    return cache[key]


def _spline_points(task):
    """Every waypoint of a SplineObj task, in metres."""
    pts = []
    for w in re.finditer(r'Task_New\(-?\d+, "SplineObjWaypoint", "[^"]*", ((?:-?[\d.eE+-]+, ){6,12})"', task or ""):
        nums = [float(v) for v in w.group(1).rstrip(", ").split(", ")]
        x, y, z = nums[-3:]
        pts.append((x / SCALE, y / SCALE, z / SCALE))
    return pts


def lifts_of(src):
    """Every lift of one level: where it stands, its cabin, the floors it stops
    at, and the switches that call it."""
    out = []
    for t in _tasks(src, "Elevator"):
        a = _args(t)
        if len(a) < 20:
            continue
        x, y, z = _num(a[3]) / SCALE, _num(a[4]) / SCALE, _num(a[5]) / SCALE
        stops = _spline_points(_task_by_id(src, int(_num(a[10]))) or "")
        # the switches the expressions name: the call buttons, and the one inside
        outside, inside = [], None
        # the button inside the cabin is written into the lift itself
        m = re.search(r'Task_New\(\s*(-?\d+)\s*,\s*"Switch"', t)
        cab_id = int(m.group(1)) if m and int(m.group(1)) >= 0 else None
        if cab_id is not None:
            inside = _switch_at(src, cab_id)
        # the call buttons: every other switch the lift names, in any of its fields
        for sid in dict.fromkeys(int(n) for n in re.findall(r"Switch_(\d+)", t)):
            if sid == cab_id:
                continue
            sw = _switch_at(src, sid)
            if sw is not None:
                outside.append(sw)
        out.append({"x": x, "y": y, "z": z, "gamma": _num(a[8]), "cabin": _str(a[9]),
                    "speed": _num(a[14], 5.0), "stops": stops, "calls": outside, "inside": inside,
                    "enable": _str(a[18]) if len(a) > 18 else ""})
    return out


LIFT_DOOR = re.compile(r"Elevator_\d+\.vFloor\s*==\s*(\d+)")


def _lift_floor(open_expr):
    """The floor a lift door belongs to, from the game's own wiring ("the door
    opens when the cabin is at floor 2"), or None for an ordinary door."""
    m = LIFT_DOOR.search(open_expr or "")
    return int(m.group(1)) if m else None


def _head_of(orient):
    """(which angle carries the heading, the heading, the two fixed angles)."""
    alpha, beta, gamma = orient
    if abs(beta - HEAD_SIDE) < 0.05:          # on its side: alpha turns it
        return 0, -alpha % TAU, [round(beta, 4), round(gamma, 4)]
    return 2, gamma % TAU, [round(alpha, 4), round(beta, 4)]


def _box(o, sizes):
    """A building's footprint: (half width, half depth, height, its heading, the
    middle's offset, and how far the model reaches below its origin)."""
    s = sizes.get(o.get("model")) or {}
    if not s.get("w"):
        return None
    return (s["w"] / 2.0 + NEAR, s.get("d", s["w"]) / 2.0 + NEAR, s.get("h") or 6.0, o.get("gamma") or 0.0,
            s.get("cx") or 0.0, s.get("cy") or 0.0, s.get("z0") or 0.0)


def _inside(o, box, x, y, z):
    """Is this point inside the building's footprint, from the bottom of the
    model (a cellar is the building's too: the underground security building
    reaches 6.1 m down, its cells 4.7 m) to a little above its top?"""
    hw, hd, h, g, cx, cy, z0 = box
    dx, dy = x - o["x"], y - o["y"]
    c, s = math.cos(-g), math.sin(-g)
    lx, ly = dx * c - dy * s - cx, dx * s + dy * c - cy
    return abs(lx) <= hw and abs(ly) <= hd and min(-3.0, z0 - 1.0) <= z - o["z"] <= h + 3.0


def variants(sizes):
    """{model: [the models that are the same building with another skin]}. Same
    family (the first number), same size to a few centimetres."""
    fams = collections.defaultdict(list)
    for m, s in sizes.items():
        f = m.split("_")[0]
        if s.get("w") and s.get("d"):
            fams[f].append(m)
    out = {}
    for f, ms in fams.items():
        for m in ms:
            a = sizes[m]
            same = [q for q in ms if all(abs((sizes[q].get(k) or 0) - (a.get(k) or 0)) <= 0.2
                                         for k in ("w", "d", "h"))]
            if len(same) > 1:
                out[m] = same
    return out


def build(game, data_dir, levels=range(1, 15), log=print):
    """Read every level's doors: what each door model does, and which doors
    belong to which building."""
    data_dir = pathlib.Path(data_dir)
    sizes = json.load((data_dir / "models.json").open(encoding="utf-8"))["sizes"]
    by_model = collections.defaultdict(list)
    slots = collections.defaultdict(list)
    lift_slots = collections.defaultdict(list)
    prop_slots = collections.defaultdict(list)
    hole_slots = collections.defaultdict(list)
    seen_buildings = collections.defaultdict(set)
    DOOR_MODELS.clear()
    for lv in levels:
        try:
            src = pathlib.Path(qvm_source.level_qsc(lv, game)).read_text(encoding="latin1")
        except (OSError, RuntimeError, ValueError) as e:
            log("  level %d: no script (%s)" % (lv, e))
            continue
        lf = data_dir / ("level%d.json" % lv)
        lvdata = json.load(lf.open(encoding="utf-8")) if lf.exists() else {}
        objs = lvdata.get("objects") or []
        homes = []
        for o in objs:
            if o.get("type") not in ("building", "prop") or o.get("x") is None or o.get("cutscene"):
                continue
            if o.get("model") in SKIP_HOMES:
                continue            # a collision box or a joint helper: not a building
            b = _box(o, sizes)
            if b and b[0] * b[1] > 4:
                homes.append((b[0] * b[1], o, b))
        homes.sort(key=lambda h: h[0])            # the smallest building that holds it wins
        ls = lifts_of(src)
        # a lift belongs to a building, never to a desk or a plank it stands by
        roomy = [(a, o, b) for a, o, b in homes if a >= LIFT_HOME_M2 and b[2] >= LIFT_HOME_H]
        for L in ls:
            g0 = None
            for _, o, b in roomy:
                if _inside(o, b, L["x"], L["y"], L["z"]):
                    g0 = o
                    break
            if g0 is None:
                # a shaft against a room's wall belongs to that room
                for _, o, b in roomy:
                    wide = (b[0] + NEAR_LIFT, b[1] + NEAR_LIFT) + b[2:]
                    if _inside(o, wide, L["x"], L["y"], L["z"]):
                        g0 = o
                        break
            if g0 is None:
                continue
            g = g0.get("gamma") or 0.0
            c, sn = math.cos(-g), math.sin(-g)

            def local(px, py, pz):
                dx, dy = px - g0["x"], py - g0["y"]
                return [round(dx * c - dy * sn, 2), round(dx * sn + dy * c, 2), round(pz - g0["z"], 2)]
            slot = {"cabin": L["cabin"], "speed": L["speed"],
                    "dx": local(L["x"], L["y"], L["z"])[0], "dy": local(L["x"], L["y"], L["z"])[1],
                    "dz": local(L["x"], L["y"], L["z"])[2], "dh": round((L["gamma"] - g) % TAU, 4),
                    "stops": [local(*p) for p in L["stops"]],
                    "calls": [local(s[0], s[1], s[2]) + [round((s[3] - g) % TAU, 4)] for s in L["calls"]],
                    "inside": (local(*L["inside"][:3]) + [round((L["inside"][3] - g) % TAU, 4)]) if L["inside"] else None,
                    "_of": (lv, g0.get("ref") or (g0["x"], g0["y"]))}
            lift_slots[g0["model"]].append(slot)
        for _, o, b in homes:
            for q in objs:
                if q is o or q.get("x") is None or q.get("cutscene"):
                    continue
                if q.get("type") not in ("prop", "building") or q.get("model") in SKIP_HOMES:
                    continue
                s2 = sizes.get(q.get("model")) or {}
                if not s2.get("w") or s2["w"] * s2.get("d", 0) > b[0] * b[1] * 0.6:
                    continue                  # as big as its home: not something inside it
                if not _inside(o, b, q["x"], q["y"], q["z"]):
                    continue
                g = o.get("gamma") or 0.0
                c, sn = math.cos(-g), math.sin(-g)
                dx, dy = q["x"] - o["x"], q["y"] - o["y"]
                prop_slots[o["model"]].append({"model": q["model"], "dx": round(dx * c - dy * sn, 2),
                                               "dy": round(dx * sn + dy * c, 2), "dz": round(q["z"] - o["z"], 2),
                                               "dh": round(((q.get("gamma") or 0.0) - g) % TAU, 4),
                                               "_of": (lv, o.get("ref") or (o["x"], o["y"]))})
        # the ground the game takes away for a building (DiscardTerrain, kept in
        # the level data as terrainHoles): each square to the smallest building
        # whose footprint holds its middle - a cellar's stairs, a lift's shaft
        for hx, hy, hs in lvdata.get("terrainHoles") or []:
            mx, my = hx + hs / 2.0, hy + hs / 2.0
            for _, o, b in roomy:
                if o.get("type") != "building" or not _inside(o, b, mx, my, o["z"]):
                    continue
                g = o.get("gamma") or 0.0
                c, sn = math.cos(-g), math.sin(-g)
                dx, dy = mx - o["x"], my - o["y"]
                hole_slots[o["model"]].append({"dx": round(dx * c - dy * sn, 2), "dy": round(dx * sn + dy * c, 2),
                                               "size": hs, "_of": (lv, o.get("ref") or (o["x"], o["y"]))})
                break
        ds = doors_of(src)
        for _, o, _b in homes:
            seen_buildings[o["model"]].add((lv, o.get("ref") or (o["x"], o["y"])))
        # a door is a building's, never a desk's or a bed's that happens to stand
        # by it (the underground security building's cellar door went to a desk):
        # the smallest home at least a door's height tall
        tall = [(a, o, b) for a, o, b in homes if b[2] >= DOOR_HOME_H]
        for d in ds:
            DOOR_MODELS.add(d["model"])
            by_model[d["model"]].append(d)
            for _, o, b in tall:
                if _inside(o, b, d["x"], d["y"], d["z"]):
                    head, dh, _ = _head_of(d["orient"])
                    g = o.get("gamma") or 0.0
                    c, sn = math.cos(-g), math.sin(-g)
                    dx, dy = d["x"] - o["x"], d["y"] - o["y"]
                    slots[o["model"]].append({"model": d["model"], "dx": round(dx * c - dy * sn, 2),
                                              "dy": round(dx * sn + dy * c, 2), "dz": round(d["z"] - o["z"], 2),
                                              "dh": round((dh - g) % TAU, 4),
                                              "liftFloor": d.get("liftFloor"),
                                              "_of": (lv, o.get("ref") or (o["x"], o["y"]))})
                    break
        log("  level %d: %d door(s)" % (lv, len(ds)))

    # a building seen in only one level borrows what its other skins were seen
    # with: the same shape has the same doorways and the same lift shaft
    same = variants(sizes)
    for store in (slots, lift_slots, hole_slots):
        was = {m: list(v) for m, v in store.items()}          # before any sharing
        for model, mine in was.items():
            for other in same.get(model, ()):
                if other != model:
                    store[other].extend(mine)
                    seen_buildings[other] |= seen_buildings.get(model, set())
    models = {}
    for model, ds in by_model.items():
        head, _, _ = _head_of(ds[0]["orient"])
        def common(pick):
            c = collections.Counter(json.dumps(pick(d)) for d in ds)
            return json.loads(c.most_common(1)[0][0])

        def field(name):
            return common(lambda d: d[name])
        models[model] = {"stop": field("stop"), "slider": field("slider"),
                         "head": head, "fixed": common(lambda d: _head_of(d["orient"])[2]),
                         "maxAngle": field("maxAngle"), "openTime": field("openTime"),
                         "pickTime": field("pickTime"), "close": field("close") or TIMED_CLOSE,
                         "sounds": field("sounds"), "seen": len(ds)}
    # A building's own doors: one real copy of it, taken as it was built, rather
    # than an average of its copies - the same doorway sits a little differently
    # from level to level, and an average can put a door half inside a wall. The
    # copy with the most doors wins; the others only say how often each doorway
    # is there (in / of).
    out_slots = {}
    for model, ss in slots.items():
        if model in SKIP_HOMES:
            continue
        copies = max(1, len(seen_buildings.get(model) or ()))
        by_copy = collections.defaultdict(list)
        for d in ss:
            by_copy[d["_of"]].append(d)
        if not by_copy:
            continue
        best = max(by_copy.values(), key=lambda ds: (len(ds), -sum(abs(d["dz"]) for d in ds)))
        keep = []
        for d in best:
            # how many copies have a door about here
            n = sum(1 for c in by_copy.values()
                    if any(abs(q["dx"] - d["dx"]) <= CLUSTER and abs(q["dy"] - d["dy"]) <= CLUSTER
                           and abs(q["dz"] - d["dz"]) <= CLUSTER for q in c))
            keep.append({"model": d["model"], "dx": d["dx"], "dy": d["dy"], "dz": d["dz"],
                         "dh": d["dh"], "in": n, "of": copies,
                         "liftFloor": d.get("liftFloor") if d.get("liftFloor") is not None else None})
        # two of the same door in one doorway is a level's own slip, not a double
        # door (a real double door is two leaves facing opposite ways)
        tidy = []
        for d in keep:
            if any(k["model"] == d["model"] and abs(k["dx"] - d["dx"]) < 0.6 and abs(k["dy"] - d["dy"]) < 0.6
                   and abs(k["dz"] - d["dz"]) < 0.6 and _turn(k["dh"], d["dh"]) < 0.3 for k in tidy):
                continue
            tidy.append(d)
        if tidy:
            out_slots[model] = sorted(tidy, key=lambda q: (q["dz"], q["dx"], q["dy"]))
    # what stands inside a building: one real copy of it, as it was furnished
    out_props = {}
    for model, ps in prop_slots.items():
        if model in SKIP_HOMES:
            continue
        by_copy = collections.defaultdict(list)
        for q in ps:
            by_copy[q["_of"]].append(q)
        best = max(by_copy.values(), key=len)
        keep = [{k: v for k, v in q.items() if k != "_of"} for q in best][:MOST_PROPS]
        if keep:
            out_props[model] = keep

    # the lifts of a building: one entry per shaft (the same lift in another copy
    # of the building is the same shaft)
    out_lifts = {}
    for model, ls in lift_slots.items():
        if model in SKIP_HOMES:
            continue
        keep = []
        for L in ls:
            # the same shaft, whichever floor its cabin starts at in each copy
            # (Eagle's Nest's two lift buildings: one waits at the top, one below)
            if any(abs(L["dx"] - k["dx"]) <= CLUSTER and abs(L["dy"] - k["dy"]) <= CLUSTER for k in keep):
                continue
            if len(L.get("stops") or []) < 2:
                continue                      # a lift with nowhere to go
            L = {k: v for k, v in L.items() if k != "_of"}
            # the game works a few of its lifts another way (a cutscene, a
            # trigger); one of ours always has buttons, or it could never be used
            # a button at every floor: the game's own where it has them, one of
            # ours at the floors it worked another way
            calls = list(L.get("calls") or [])
            for st in L["stops"]:
                if not any(abs(c[2] - st[2]) <= 3.0 for c in calls):
                    calls.append([st[0] + CALL_OUT, st[1], st[2] + CALL_UP, 0.0])
            L["calls"] = calls
            if not L.get("inside"):
                L["inside"] = [L["dx"] + CALL_IN, L["dy"], L["dz"] + CALL_UP, 0.0]
            keep.append(L)
        if keep:
            out_lifts[model] = keep
    # the ground a building opens: the squares of one real copy of it - of the
    # copies the game opens any ground for, the one it opens least (the Guard HQ
    # has a 32 m square in one level and two 16 m ones in another; level 3's
    # underground security building one 16 m square over its stairs)
    out_holes = {}
    for model, hs in hole_slots.items():
        if model in SKIP_HOMES:
            continue
        by_copy = collections.defaultdict(list)
        for h in hs:
            by_copy[h["_of"]].append(h)
        best = min(by_copy.values(), key=lambda hs: sum(h["size"] ** 2 for h in hs))
        out_holes[model] = [{k: v for k, v in h.items() if k != "_of"} for h in best]
    every = {}
    for model in set(out_slots) | set(out_lifts) | set(out_props) | set(out_holes):
        e = {}
        if out_slots.get(model):
            e["doors"] = out_slots[model]
        if out_lifts.get(model):
            e["lifts"] = out_lifts[model]
        # the cabins and doors of this building are not "things inside" it twice
        cabins = {L.get("cabin") for L in out_lifts.get(model) or []}
        props = [q for q in out_props.get(model) or []
                 if q["model"] not in cabins and q["model"] not in DOOR_MODELS]
        if props:
            e["props"] = props
        if out_holes.get(model):
            e["holes"] = out_holes[model]
        every[model] = e
    return {"v": 2, "models": models, "buildings": every}


def _turn(a, b):
    """How far apart two headings are, in radians (0 to pi)."""
    d = abs((a - b) % TAU)
    return min(d, TAU - d)


def _mean_angle(angles):
    x = sum(math.cos(a) for a in angles)
    y = sum(math.sin(a) for a in angles)
    return math.atan2(y, x) % TAU


def main(argv):
    from studio import paths
    game = argv[argv.index("--game") + 1] if "--game" in argv else str(paths.pristine())
    data = pathlib.Path(argv[argv.index("--data") + 1] if "--data" in argv else paths.data())
    out = pathlib.Path(argv[argv.index("--out") + 1] if "--out" in argv else data / "doors.json")
    d = build(game, data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, indent=1), encoding="utf-8")
    print("%d door model(s), %d building(s) with doors or lifts of their own (%d with lifts) -> %s"
          % (len(d["models"]), len(d["buildings"]),
             sum(1 for v in d["buildings"].values() if v.get("lifts")), out))


if __name__ == "__main__":
    main(sys.argv[1:])
