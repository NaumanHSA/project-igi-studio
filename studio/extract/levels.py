# Extracts every shipped IGI 1 level into JSON for the Project IGI Studio editor.
#
#   python -m studio extract levels [--levels 1,2,3] [--out <folder>]
#
# Per level it emits objects (in GAME coordinates, qsc/4096) plus, for each AI
# graph, the facts the engine actually enforces:
#   walkable - nodes some shipped patrol walks or runs to
#   edges    - consecutive walk/run pairs, i.e. routes known to resolve
# A node merely existing is not enough; walking to a look-at-only node gives
# "Error in graph NNNN routenet, Node #A to #B" at level load.
import json, os, re, sys, pathlib, collections
from studio import paths as studio_paths
from studio.qvm import source as qvm_source
# This module is a script: it does its work as it is read, the way it always
# has. Run it (python -m studio.extract.levels), do not import it. The guard below
# turns an accidental import into a clear error instead of a surprise.
if __name__ != "__main__":
    raise ImportError("studio.extract.levels is a script: run it, do not import it")

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODEL_NAMES = pathlib.Path(__file__).resolve().parent / "model_names.json"
MODELS_TXT = pathlib.Path(os.path.expandvars(r"%APPDATA%\QEditor\IGIModels.txt"))
SCALE = 4096.0

argv = sys.argv
LEVELS = ([int(x) for x in argv[argv.index("--levels") + 1].split(",")]
          if "--levels" in argv else list(range(1, 15)))
OUT = ROOT / argv[argv.index("--out") + 1] if "--out" in argv else studio_paths.data()
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- model names
# Names for the game's models. Ours by default, so nothing else has to be
# installed; a copy of the research file the names came from is read as well
# when one happens to be there, for anything we do not have yet.
models = {}
try:
    models.update(json.loads(MODEL_NAMES.read_text(encoding="utf-8"))["names"])
except (OSError, ValueError, KeyError):
    pass
if MODELS_TXT.exists():
    for line in MODELS_TXT.open(encoding="latin1"):
        if "=" in line:
            nm, mid = line.split("=", 1)
            mid = mid.strip()
            if re.fullmatch(r"\d{3}_\d{2}_\d", mid):
                models.setdefault(mid, nm.strip())

# The mission's objectives as the map computer lists them: one
# DefineComputerObjective holds up to 6 (text key, link task id, complete
# expression, failed expression). A level can have several - a later one takes
# over when its "Objectives Valid" expression becomes true (level 3 swaps the
# list once Priboi has moved). The texts live in the language files.
STR = r'"((?:[^"\\]|\\.)*)"'
R_OBJDEF = re.compile(r'Task_New\((-?\d+), "DefineComputerObjective", ' + STR + r', ')
R_OBJSLOT = re.compile(STR + r', (-?\d+), ' + STR + r', ' + STR)
OBJ_TEXTS = None


def objective_texts():
    """key -> text, from the game's objectives.res (the pristine install first)."""
    global OBJ_TEXTS
    if OBJ_TEXTS is None:
        OBJ_TEXTS = {}
        from studio.build import lang as lang_res
        for base in (str(studio_paths.pristine()), str(studio_paths.game())):
            d = pathlib.Path(base) / "language"
            if not d.is_dir():
                continue
            for lang in sorted(d.iterdir()):
                f = lang / "objectives.res"
                if f.exists():
                    try:
                        for k, v in lang_res.strings(f).items():
                            OBJ_TEXTS.setdefault(k, v)
                    except (OSError, ValueError):
                        pass
            if OBJ_TEXTS:
                break
    return OBJ_TEXTS


def objectives_of(src):
    texts, out = objective_texts(), []
    for m in R_OBJDEF.finditer(src):
        j, depth = m.start(), 0
        while j < len(src):                     # the task's own brackets
            c = src[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = src[m.end():j]
        slots = []
        for key, link, done, failed in R_OBJSLOT.findall(body):
            if not key:
                continue
            slots.append({"key": key, "link": int(link), "done": done, "failed": failed,
                          "text": texts.get(key, "")})
        if slots:
            out.append({"id": int(m.group(1)), "valid": m.group(2), "slots": slots})
    return out


# ---------------------------------------------------------------- alarms
# An alarm system is one AlarmControl plus everything that names it by task id:
# cameras and buttons in its Trigger Expression (directly or through an
# SCameraControl), guards whose AI script calls SetAlarmControlID, and sirens,
# lights, sounds, doors and guard generators whose own expression tests
# AlarmControl_N.isAlarm. There is no area anywhere - the membership is the area.
R_ALARM_PART = re.compile(r'Task_New\((-?\d+), "(AlarmControl|SCameraControl|Siren|AlarmLight|Switch|'
                          r'ConditionalSound|GuardGenerator|EditVariable)", ')


def _task_end(text, start):
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


def _strings(seg):
    return [m.group(1) for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', seg)]


def alarms_of(src, soldiers_by_ai):
    """[{id, x, y, z, trigger, ...}] - every alarm system the level ships."""
    parts = []
    for m in R_ALARM_PART.finditer(src):
        seg = src[m.start():_task_end(src, m.start())]
        parts.append({"id": int(m.group(1)), "type": m.group(2), "seg": seg,
                      "str": _strings(seg),
                      "pos": [round(float(v) / SCALE, 2) for v in
                              re.findall(r"(-?[\d.]+), (-?[\d.]+), (-?[\d.]+)", seg)[0]]
                      if re.search(r"(-?[\d.]+), (-?[\d.]+), (-?[\d.]+)", seg) else [0, 0, 0]})
    controls = [p for p in parts if p["type"] == "AlarmControl"]
    cams = {p["id"]: p for p in parts if p["type"] == "SCameraControl"}
    out = []
    for c in controls:
        # ..., "On Expression", hack time, "Trigger Expression", "Alarm Expression"
        st = c["str"]
        on = st[6] if len(st) > 6 else ""
        trig = st[7] if len(st) > 7 else ""
        keep = st[8] if len(st) > 8 else ""
        src_ids = {"cameras": [], "cameraControls": [], "switches": [], "guards": [], "other": []}
        for cid in re.findall(r"SCamera_(\d+)\.isDetection", trig):
            src_ids["cameras"].append(int(cid))
        for cc in re.findall(r"SCameraControl_(\d+)\.isDetection", trig):
            src_ids["cameraControls"].append(int(cc))
            sub = cams.get(int(cc))
            if sub:
                expr = sub["str"][7] if len(sub["str"]) > 7 else ""
                src_ids["cameras"] += [int(x) for x in re.findall(r"SCamera_(\d+)\.isDetection", expr)]
                src_ids["guards"] += [int(x) for x in re.findall(r"HumanAI_(\d+)\.isDetection", expr)]
        for sw in re.findall(r"Switch_(\d+)\.is\w+", trig):
            src_ids["switches"].append(int(sw))
        for ai in re.findall(r"HumanAI_(\d+)\.isDetection", trig):
            src_ids["guards"].append(int(ai))
        mine = "AlarmControl_%d.isAlarm" % c["id"]
        effects = {"sirens": 0, "lights": 0, "sounds": 0, "doors": 0, "reinforcements": [], "messages": 0}
        for p in parts:
            if mine not in p["seg"] or p is c:
                continue
            if p["type"] == "Siren":
                effects["sirens"] += 1
            elif p["type"] == "AlarmLight":
                effects["lights"] += 1
            elif p["type"] == "ConditionalSound":
                effects["sounds"] += 1
            elif p["type"] == "GuardGenerator":
                n = re.search(r'", (\d+),\s*Task_New', p["seg"])
                effects["reinforcements"].append({"id": p["id"], "max": int(n.group(1)) if n else 1})
        effects["doors"] = len(re.findall(r'Task_New\(-?\d+, "Door"[^)]*%s' % re.escape(mine), src))
        effects["messages"] = len(re.findall(r'"%s[^"]*", "M\d+_MSG' % re.escape(mine), src))
        out.append({"id": c["id"], "x": c["pos"][0], "y": c["pos"][1], "z": c["pos"][2],
                    "model": st[2] if len(st) > 2 else "", "on": on, "trigger": trig, "keeps": keep,
                    "hackTime": float(re.findall(r'", ([\d.]+), "', c["seg"])[-1]) if re.findall(r'", ([\d.]+), "', c["seg"]) else 4.0,
                    "sources": src_ids, "effects": effects,
                    "guards": sorted(soldiers_by_ai.get(c["id"], []))})
    return out


R_SOL = re.compile(r'Task_New\((-?\d+), "(HumanSoldier\w*)", "([^"]*)", '
                   r'(-?[\d.]+), (-?[\d.]+), (-?[\d.]+), (-?[\d.]+), "([^"]*)", (\d+)')
R_AI = re.compile(r'"HumanAI", "", "(AITYPE_[A-Z_0-9]+)", (\d+)\)')
R_AI_ID = re.compile(r'Task_New\((-?\d+), "HumanAI", "", "(AITYPE_[A-Z_0-9]+)", (\d+)\)')
R_PATH = re.compile(r'Task_New\((-?\d+), "PatrolPath", "')
# In an AI script, the path a guard walks when nothing is happening:
#   if(AIFunction_GetCurrentEventType() == AIEVENT_IDLE) { AIAction_Patrol(2407, ...
R_IDLE = re.compile(r'AIEVENT_IDLE\s*\)\s*\{\s*AIAction_Patrol\(\s*(\d+)')
R_ANY_PATROL = re.compile(r'AIAction_Patrol\(\s*(\d+)')


def idle_path(script):
    """Path id a guard walks when idle, per his AI script; None if he stands still."""
    if script is None:
        return "unknown"
    m = R_IDLE.search(script)
    if m:
        return int(m.group(1))
    # a script that never patrols on IDLE keeps the guard where he is, even if it
    # sends him somewhere on an alarm
    return None
R_GUN = re.compile(r'"Gun\w*", "", "(WEAPON_ID_[A-Z0-9]+)"')
R_CMD = re.compile(r'"PatrolPathCommand", "[^"]*", (\d+), (\d+)\)')
R_PLAYER = re.compile(r'Task_New\((\d+), "HumanPlayer", "([^"]*)", '
                      r'(-?[\d.]+), (-?[\d.]+), (-?[\d.]+), (-?[\d.]+), "([^"]*)"')
R_FLOW = re.compile(r'Task_New\(\d+, "LevelFlow"[^;]*?"([^"]*)", "([^"]*)", (TRUE|FALSE)')

R_CAM = re.compile(r', (-?[\d.eE+-]+), (-?[\d.eE+-]+), "([^"]*)", "([^"]*)", (-?\d+), (-?\d+), (-?\d+), '
                   r'(-?[\d.eE+-]+), (-?\d+), (-?\d+), (-?[\d.eE+-]+), "((?:[^"\\]|\\.)*)"')

STATIC = [("Building", "building"), ("EditRigidObj", "prop"), ("Door", "door"),
          ("Terminal", "terminal"), ("GunPickup", "pickup"), ("AmmoPickup", "pickup"),
          ("GenericPickup", "pickup"),
          ("SCamera", "camera"), ("ExplodeObject", "explodable"), ("Car", "vehicle"),
          ("Switch", "switch"), ("Heli", "vehicle")]



def ref(qtype, x, y, z):
    """A stable handle on one task: its type and its position exactly as written.

    Most statics have task id -1, so the id cannot tell them apart. The raw
    coordinate text can, and it lets the generator find the very same task again
    to move, re-arm or delete it - without renumbering anything.
    """
    return "%s@%s,%s,%s" % (qtype, x, y, z)


def cutscene_ranges(text):
    """Character ranges covered by a cutscene ConditionalContainer.

    Objects inside one only exist while that cutscene plays - level 1 has
    soldiers a long way outside the yard for exactly this reason, and showing
    them on the plan as if they were guards is misleading.
    """
    out, stack, i, instr = [], [], 0, False
    pat = re.compile(r'Task_New\((-?\d+), "(ConditionalContainer|Container)", "([^"]*)"')
    while i < len(text):
        c = text[i]
        if c == '"':
            instr = not instr
        elif not instr:
            if text.startswith("Task_New(", i):
                m = pat.match(text, i)
                stack.append([i, m.group(2), (m.group(3) or "").lower()] if m else None)
            elif c == "(" and stack and stack[-1] is None:
                pass
            elif c == ")" and stack:
                fr = stack.pop()
                if fr and fr[1] == "ConditionalContainer" and                    re.search(r"cutscene|intro|outro|opening|ending", fr[2]):
                    out.append((fr[0], i))
        i += 1
    return out


def in_cutscene(ranges, pos):
    return any(a <= pos <= b for a, b in ranges)


def load_ai_scripts(ai_dir):
    out = {}
    if ai_dir and pathlib.Path(ai_dir).is_dir():
        for f in pathlib.Path(ai_dir).glob("*.qsc"):
            if f.stem.lstrip("-").isdigit():
                out[int(f.stem)] = f.read_text(encoding="latin1")
    return out


def extract(level, src_path=None, ai_dir=None):
    path = pathlib.Path(src_path) if src_path else qvm_source.level_qsc(level)
    if not path.exists():
        return None
    ai_scripts = load_ai_scripts(ai_dir or path.parent / "ai")
    src = path.read_text(encoding="latin1")
    lines = src.split("\n")
    objects, blocks, cur = [], [], None
    cuts = cutscene_ranges(src)
    pos = 0

    for l in lines:
        m = R_SOL.search(l)
        if m:
            tid, qt, nm, x, y, z, g, model, team = m.groups()
            cur = {"id": int(tid), "type": "soldier", "qtype": qt, "name": nm,
                   "model": model, "modelName": models.get(model, model),
                   "x": round(float(x)/SCALE, 2), "y": round(float(y)/SCALE, 2),
                   "z": round(float(z)/SCALE, 2), "gamma": round(float(g), 4),
                   "team": int(team), "ai": None, "graph": None, "weapon": None,
                   "ref": ref(qt, x, y, z)}
            cur["cutscene"] = in_cutscene(cuts, pos + m.start())
            objects.append(cur)
            blocks.append({"o": cur, "cmds": [], "paths": [], "aid": None})
            pos += len(l) + 1
            continue
        if cur is not None and blocks:
            a = R_AI_ID.search(l)
            if a and cur["ai"] is None:
                blocks[-1]["aid"] = int(a.group(1))
                cur["ai"], cur["graph"] = a.group(2), int(a.group(3))
            w = R_GUN.search(l)
            if w and cur["weapon"] is None:
                cur["weapon"] = w.group(1)
            pp = R_PATH.search(l)
            if pp:
                blocks[-1]["paths"].append([int(pp.group(1)), []])
            for c, p in R_CMD.findall(l):
                blocks[-1]["cmds"].append((int(c), int(p)))
                if blocks[-1]["paths"]:
                    blocks[-1]["paths"][-1][1].append((int(c), int(p)))
        pos += len(l) + 1

    m = R_PLAYER.search(src)
    if m:
        tid, nm, x, y, z, g, model = m.groups()
        objects.append({"id": int(tid), "type": "player", "qtype": "HumanPlayer",
                        "name": "Player spawn", "model": model, "modelName": "Player",
                        "x": round(float(x)/SCALE, 2), "y": round(float(y)/SCALE, 2),
                        "z": round(float(z)/SCALE, 2), "gamma": round(float(g), 4),
                        "ref": ref("HumanPlayer", x, y, z)})   # so a mission can move the start

    # Static objects carry an Orientation (Real32x9, written as three angles)
    # rather than a single gamma, so a building's yaw is the LAST of the numbers
    # between its position and its model name. Types differ in how many numbers
    # sit in between - a Door adds stop X, stop Y and a slider - so take the
    # last one rather than counting fields per type.
    for qtype, kind in STATIC:
        pat = re.compile(r'Task_New\((-?\d+), "%s", "([^"]*)", (-?[\d.]+), (-?[\d.]+), '
                         r'(-?[\d.]+), ([-\d.,eE+ ]*?)"([^"]*)"' % qtype)
        for mm in pat.finditer(src):
            tid, nm, x, y, z, nums, model = mm.groups()
            parts = [v.strip() for v in nums.split(",") if v.strip()]
            try:
                yaw = float(parts[-1]) if parts else 0.0
            except ValueError:
                yaw = 0.0
            objects.append({"id": int(tid), "type": kind, "qtype": qtype, "name": nm,
                            "model": model, "modelName": models.get(model, model),
                            "x": round(float(x)/SCALE, 2), "y": round(float(y)/SCALE, 2),
                            "z": round(float(z)/SCALE, 2),
                            "gamma": round(yaw, 4), "ref": ref(qtype, x, y, z),
                            "cutscene": in_cutscene(cuts, mm.start())})
            # the whole orientation where it is more than a heading: a pickup
            # lying on its side is (heading, 1.5708, 0) - for the 3D close-up
            if len(parts) >= 3:
                try:
                    ang = [round(float(v), 4) for v in parts[-3:]]
                    if ang[0] or ang[1]:
                        objects[-1]["orient"] = ang
                except ValueError:
                    pass
            if qtype == "Switch":
                # the model follows the expression ("1") and a flag - the
                # studio's "model" stays the field an edit rewrites
                sm = re.match(r'\s*,\s*(?:TRUE|FALSE)\s*,\s*"([^"]*)"', src[mm.end():mm.end() + 64])
                if sm:
                    objects[-1]["mesh"] = sm.group(1)
            if qtype == "AmmoPickup":
                cnt = re.match(r'\s*,\s*(\d+)', src[mm.end():mm.end() + 16])
                if cnt:
                    objects[-1]["count"] = int(cnt.group(1))
            if qtype == "SCamera":
                # Holder Gamma, Holder Model, then the camera itself: tilt (alpha) and
                # pan (gamma) relative to the holder, its models, how far it sweeps
                # right and left (degrees) at what speed with what pause at each
                # end, and its view cone: vertical and horizontal angle, length (m)
                cm = R_CAM.match(src, mm.end())
                if cm:
                    a, g, cmodel, dmodel, right, left, speed, delay, fov_v, fov, rng, on = cm.groups()
                    objects[-1]["cam"] = {"pitch": round(float(a), 4), "pan": round(float(g), 4),
                                          "model": cmodel, "destroyed": dmodel,
                                          "right": int(right), "left": int(left), "speed": int(speed),
                                          "delay": float(delay), "fovV": int(fov_v), "fov": int(fov),
                                          "range": float(rng), "on": on.replace("\\n", " ").strip()[:200]}

    # ---- Fence tasks ---------------------------------------------------------
    # Not the same thing as a fence PROP. A "Fence" task is the engine's
    # interactive fence - the one the player can climb (the wooden fence tying
    # level 1's two small garages together at their corners), or with an
    # Electric Expression, one that shocks (level 6's compound). Declared as
    # Position, Gamma (a single angle, not an orientation), Model, Expression.
    pat = re.compile(r'Task_New\((-?\d+), "Fence", "([^"]*)", (-?[\d.eE+-]+), (-?[\d.eE+-]+), '
                     r'(-?[\d.eE+-]+), (-?[\d.eE+-]+), "([^"]*)", "((?:[^"\\]|\\.)*)"')
    for mm in pat.finditer(src):
        tid, nm, x, y, z, g, model, expr = mm.groups()
        expr = expr.replace("\\n", " ").strip()
        objects.append({"id": int(tid), "type": "fence", "qtype": "Fence", "name": nm,
                        "model": model, "modelName": models.get(model, model),
                        "x": round(float(x)/SCALE, 2), "y": round(float(y)/SCALE, 2),
                        "z": round(float(z)/SCALE, 2), "gamma": round(float(g), 4),
                        "electric": expr[:160] or None, "ref": ref("Fence", x, y, z),
                        "cutscene": in_cutscene(cuts, mm.start())})

    # ---- AIGraph origins ----------------------------------------------------
    # Node coordinates inside graphN.dat are offsets from this point, not
    # absolute: absolute = origin + offset.
    origins = {}
    for mm in re.finditer(r'Task_New\((\d+), "AIGraph", "[^"]*", '
                          r'(-?[\d.]+), (-?[\d.]+), (-?[\d.]+)', src):
        gid, x, y, z = mm.groups()
        origins[gid] = {"x": round(float(x)/SCALE, 2), "y": round(float(y)/SCALE, 2),
                        "z": round(float(z)/SCALE, 2)}

    # ---- per-graph routing facts -------------------------------------------
    graphs = {}
    for b in blocks:
        # The guard's own route, for drawing and animating it and for refusing a
        # node edit that would break it. Codes: 0 animation, 1 delay (ticks),
        # 2 walk to node, 3 run to node, 4 crouch, 5 look at node, 6 end,
        # 7 quit, 8 set speed (km/h).
        # A guard usually has several paths - one for idle, others for alarms.
        # Only the idle one is his patrol; the rest still name nodes he may use.
        # Which is which is decided by his AI script, not by file order.
        if b["cmds"]:
            b["o"]["pathNodes"] = sorted({p for c, p in b["cmds"] if c in (2, 3, 5)})
            # every path's walk order - alarm routes must stay routable too
            b["o"]["routes"] = {str(i): [p for c, p in cmds if c in (2, 3)] for i, cmds in b["paths"]
                                if any(c in (2, 3) for c, _ in cmds)}
        script = ai_scripts.get(b["aid"]) if b["aid"] is not None else None
        if script:
            ac = re.search(r"SetAlarmControlID\((\d+)\)", script)
            if ac:
                b["o"]["alarm"] = int(ac.group(1))
        pid = idle_path(script) if ai_scripts else "unknown"
        paths = dict((i, cmds) for i, cmds in b["paths"])
        if pid == "unknown":
            chosen = b["paths"][0][1] if b["paths"] else []
        else:
            chosen = paths.get(pid, [])
            if b["paths"]:
                # which PatrolPath task a rewritten patrol replaces ("none": he has
                # only alarm paths, so a new patrol is added beside them)
                b["o"]["idlePath"] = pid if pid is not None else "none"
        if chosen:
            b["o"]["patrolCmds"] = [[c, p] for c, p in chosen]
            b["o"]["patrol"] = [p for c, p in chosen if c in (2, 3)]
        elif b["paths"]:
            b["o"]["patrolCmds"] = []
            b["o"]["patrol"] = []
        g = b["o"]["graph"]
        if g is None:
            continue
        rec = graphs.setdefault(str(g), {"walkable": set(), "lookOnly": set(), "edges": set()})
        moves = [p for c, p in b["cmds"] if c in (2, 3)]
        looks = [p for c, p in b["cmds"] if c == 5]
        rec["walkable"] |= set(moves)
        rec["lookOnly"] |= set(looks)
        for a_, b_ in zip(moves, moves[1:]):
            if a_ != b_:
                rec["edges"].add((a_, b_))
    for g, rec in graphs.items():
        rec["lookOnly"] -= rec["walkable"]
        rec["walkable"] = sorted(rec["walkable"])
        rec["lookOnly"] = sorted(rec["lookOnly"])
        rec["edges"] = sorted([list(e) for e in rec["edges"]])

    # ids already taken, so the generator can pick free ones under the 4095 ceiling
    # which guards answer which alarm - from their own AI scripts, read above
    by_alarm = {}
    for o in objects:
        if o.get("type") == "soldier" and o.get("alarm") is not None and o.get("id", -1) >= 0:
            by_alarm.setdefault(o["alarm"], []).append(o["id"])

    used = sorted(set(int(v) for v in re.findall(r'Task_New\((\d+),', src)))

    flow = R_FLOW.search(src)
    xs = [o["x"] for o in objects]; ys = [o["y"] for o in objects]; zs = [o["z"] for o in objects]
    return {
        "level": level,
        "scale": int(SCALE),
        "bounds": {"minX": min(xs), "maxX": max(xs), "minY": min(ys), "maxY": max(ys),
                   "minZ": min(zs), "maxZ": max(zs)},
        "objects": objects,
        "graphs": graphs,
        "graphOrigins": origins,
        "usedIds": used,
        "maxId": max(used) if used else 0,
        "levelFlow": {"complete": flow.group(1), "failed": flow.group(2)} if flow else None,
        "objectiveSets": objectives_of(src),
        "alarms": alarms_of(src, by_alarm),
        # the map computer holds 32 of these in all; the numbered ones can be
        # written over by a mission's own objectives
        "hilights": {"total": len(re.findall(r'Task_New\(-?\d+, "ComputerHilight"', src)),
                     "numbered": len(re.findall(r'"COMPUTER:h_\d+\.spr"', src))},
    }


# --src lets a custom slot be extracted from its own decompiled script, so a
# mission you have already built shows up in the editor alongside the shipped
# levels instead of only existing in the game folder.
SRC = arg_src = (argv[argv.index("--src") + 1] if "--src" in argv else None)
AS_LEVEL = int(argv[argv.index("--as") + 1]) if "--as" in argv else None
AI_DIR = argv[argv.index("--ai") + 1] if "--ai" in argv else None
if SRC:
    LEVELS = [AS_LEVEL or 15]

index = []
if OUT.joinpath("index.json").exists():
    import json as _j
    try: index = _j.load(OUT.joinpath("index.json").open()).get("levels", [])
    except Exception: index = []
for lv in LEVELS:
    d = extract(lv, SRC, AI_DIR)
    if not d:
        print("level %-2d  SKIPPED (no objects.qsc)" % lv)
        continue
    p = OUT / ("level%d.json" % lv)
    json.dump(d, p.open("w"), separators=(",", ":"))
    counts = collections.Counter(o["type"] for o in d["objects"])
    index = [r for r in index if r.get("level") != lv]
    index.append({"level": lv, "objects": len(d["objects"]),
                  "graphs": sorted(d["graphs"].keys(), key=int),
                  "maxId": d["maxId"],
                  "bounds": d["bounds"], "file": "level%d.json" % lv})
    print("level %-2d  %4d objects  %2d graphs  maxId %4d  %6.0f KB   %s"
          % (lv, len(d["objects"]), len(d["graphs"]), d["maxId"],
             p.stat().st_size/1024, dict(counts)))

index.sort(key=lambda r: r["level"])
json.dump({"levels": index, "models": models}, (OUT / "index.json").open("w"),
          separators=(",", ":"))
print("\nwrote %s  (+ index.json)" % OUT)
