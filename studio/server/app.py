# Serves the Project IGI Studio editor locally and applies plans straight into the game.
#
#   python -m studio           then open http://localhost:8765
#
# The published Artifact version of the editor cannot do this: a sandboxed page
# may not write to disk or run a compiler, and its CSP blocks calls to localhost
# too. Served from here the page is same-origin, so the Apply button works.
#
# The same plotter.html runs in both places - it probes /api/status at start and
# only shows Apply and Settings when a server answers.
#
# Missions: GET /api/library (built-in + custom missions, game slots, trash)
#   POST   /api/missions                     create {name, description, base:{level, kind}, from}
#   GET    /api/missions/<id>                the whole mission
#   PUT    /api/missions/<id>                save {plan, name, description, cover (PNG data URL)}
#   DELETE /api/missions/<id>                to the trash {removeFromGame}
#   POST   /api/missions/<id>/duplicate      {name}
#   POST   /api/missions/<id>/apply          build from the pristine base + plan, install in its slot
#   POST   /api/missions/<id>/applyjob       the same as a job to poll; {test: {x, y, z, gamma, launch}}
#                                            builds with the player starting there, and starts the game
#   POST   /api/launch                       start IGI.exe (the working game)
#   GET    /api/missions/<id>/runs[/<run>]   play-throughs the live view recorded; POST saves one,
#                                            DELETE .../runs/<run> removes one
#   POST   /api/missions/<id>/uninstall      take its slot out of the game (kept in backups)
#   POST   /api/slots/order                  {order: [slot numbers]} the studio's missions in the game, renumbered
#                                            in that order from 15 up
#   POST   /api/slots/<n>/remove             take out a slot the studio made that no mission here holds
#   GET    /api/recoverable, POST /api/recover   missions in the game that this studio can take back in
#   GET    /api/missions/<id>/cover.png
#   GET    /api/missions/<id>/picture.png    the mission's own picture (PUT {picture: data URL or null})
#   GET    /api/music                        the game's music a mission can have
#   GET    /api/music/<id>.wav               one of them to listen to (byte ranges)
#   GET    /api/trash, POST /api/trash/<tid>/restore,
#          DELETE /api/trash/<tid> (for good), DELETE /api/trash (empty it)
# The AI designer (studio/server/ai.py):
#   GET/POST /api/ai/settings    the saved models, which one each role uses, pace...
#                                (a key only as "there is one")
#   GET    /api/ai/models        the chat models a server offers (?id=<saved model>)
#   POST   /api/ai/test          a one-line request (?id=<saved model>, else the designer's)
#   POST   /api/links            which walkway links a wall or fence cuts, as Apply tests them
#   POST   /api/ai/chat          one model turn, streamed back as JSON lines
#   GET    /api/missions/<id>/ai            the mission's chat threads
#   GET/PUT/DELETE /api/missions/<id>/ai/<thread>   one thread
#   GET /api/groups, POST (save), PUT /api/groups/<id> {name, cat, description}, DELETE:
#          the user's own items for the inventory ("Your items"), in missions/groups/
import base64, collections, hmac, json, os, pathlib, re, subprocess, sys, threading, time, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = pathlib.Path(__file__).resolve().parents[2]
EDITOR = ROOT / "editor"
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8765

# The desktop app starts this server for itself alone. It picks a free port
# (--port 0) and hands over a token nobody else knows, on stdin so that it never
# shows in a process list (--token-stdin). From then on every request has to
# carry that token in an X-Studio-Token header, which the app's window adds and
# nothing else on the machine can: not another program, and not a web page in a
# browser, which cannot set that header on a request to here without a CORS
# preflight this server never answers. Without a token (a checkout, run by hand)
# the server behaves as it always has.
TOKEN = None

from studio.qvm import compile as CQ
from studio.build import install as INST
from studio.build import music as MU
from studio.build import covers as CV
from studio.server import missions as MS
from studio import protect
from studio.build import slots as SL
from studio.extract import model3d as M3
from studio.server import ai as AI
from urllib.parse import urlparse, parse_qs
from studio import paths
from studio.qvm import source as qvm_source

def DEFAULTS():
    return {"gamePath": str(paths.setting("gamePath") or ""), "slot": paths.slot(),
            "pristinePath": str(paths.pristine()) if paths.setting("pristinePath") else ""}


def load_config():
    cfg = DEFAULTS()
    f = paths.config_file()
    if f.exists():
        try:
            cfg.update(json.load(f.open(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    f = paths.config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def game_state(cfg):
    raw = str(cfg["gamePath"] or "").strip()
    g = pathlib.Path(raw) if raw else None
    slot = g / "missions" / "location0" / ("level%d" % cfg["slot"]) if g else None
    ready = bool(g) and (g / "missions" / "location0").is_dir()
    return {
        "gamePath": raw,
        "pristinePath": cfg.get("pristinePath"),
        "slot": cfg["slot"],
        "gameExe": bool(g) and (g / "IGI.exe").exists(),
        "version": __import__("studio").__version__,
        "slotExists": bool(slot) and slot.is_dir(),
        "compiler": CQ.available(),
        "missions": True,
        "ready": ready,                 # false means the setup has not run yet
        # a game was chosen and its folder is not there any more: a drive
        # unplugged, the game moved or uninstalled. Missions are unaffected.
        "gameMissing": bool(raw) and not ready,
        "levelsFrom": str(paths.levels(cfg["gamePath"])),
        "canEdit": (paths.levels(cfg["gamePath"]) / "missions" / "location0").is_dir()
                   and _data_ready(),
        "dataReady": _data_ready(),
    }


def setup_state(cfg, find=False):
    """What the first run screen shows: the game, its build, and our copy of it."""
    from studio.setup import detect, snapshot, verify
    raw = str(cfg["gamePath"] or "").strip()
    g = pathlib.Path(raw) if raw else None
    out = {"ok": True, "ready": False, "game": raw, "home": str(paths.home()),
           "settings": str(paths.config_file()),
           "gameMissing": bool(g) and not (g / "missions" / "location0").is_dir()}
    if g and (g / "missions" / "location0").is_dir():
        r = verify.check(g)
        out.update(ready=r["ok"], missing=r["missing"], levels=r["levels"],
                   custom=r.get("custom") or [], fingerprint=r.get("fingerprint"),
                   build=r.get("profileName"), nearest=r.get("nearest"),
                   differs=r.get("differs"))
    snap = snapshot.info()
    if snap:
        out["snapshot"] = {"path": str(paths.snapshot()), "files": snap["files"],
                           "bytes": snap["bytes"], "made": snap["made"],
                           "stale": bool(g) and snapshot.stale(g)}
    elif out.get("ready"):
        items, total = snapshot.plan(g)
        out["snapshot"] = {"path": str(paths.snapshot()), "files": len(items),
                           "bytes": total, "made": None, "stale": None}
    from studio.setup import data as DATA
    di = DATA.info()
    out["data"] = {"path": str(paths.data()), "ready": DATA.ready(),
                   "built": (di or {}).get("built"), "seconds": (di or {}).get("seconds")}
    if find or not out["ready"]:
        out["found"] = detect.find()
    return out


class SetupProgress(object):
    """Turns the reference copy's and the level data build's own log into a
    percentage and a list of steps, for the setup screen to draw.

    The steps are weighted by how long they really take on a typical machine:
    the ground heights are most of the data build, the copy most of the rest.
    """
    COPY, CHECK = 16.0, 6.0          # the reference copy and its check

    def __init__(self, say, reference=True, data=True):
        from studio.setup import data as DATA
        self.say = say
        self.steps = []
        weights = {"levels": 3, "graphs": 2, "models": 2, "catalog": 1, "terrain": 40,
                   "ground": 5, "meshes": 5, "navtemplates": 2, "doors": 2, "library": 1}
        if reference:
            self.steps += [{"key": "copy", "label": "Copying the game's own levels", "w": self.COPY},
                           {"key": "check", "label": "Checking the copy, file by file", "w": self.CHECK}]
        if data:
            for name, _m, _r, what, _x in DATA.STEPS:
                self.steps.append({"key": name, "label": what[:1].upper() + what[1:],
                                   "w": float(weights.get(name, 2))})
        total = sum(st["w"] for st in self.steps) or 1.0
        acc = 0.0
        for st in self.steps:
            st["from"], acc = acc / total * 100.0, acc + st["w"]
            st["to"] = acc / total * 100.0
            st["state"], st["detail"] = "todo", ""
        self.by = {st["key"]: st for st in self.steps}
        self.pct = 1.0
        self._emit()

    def _start(self, key, detail=""):
        for st in self.steps:
            if st["key"] == key:
                st["state"], st["detail"] = "now", detail
                break
            if st["state"] != "done":
                st["state"] = "done"

    def _part(self, key, frac):
        st = self.by.get(key)
        if st:
            self.pct = max(self.pct, st["from"] + (st["to"] - st["from"]) * max(0.0, min(1.0, frac)))

    def _emit(self):
        self.say("PCT %d" % int(self.pct))
        self.say("STEPS " + json.dumps([{k: st.get(k, "") for k in ("key", "label", "state", "detail")}
                                        for st in self.steps]))

    def log(self, text):
        t = str(text)
        low = t.strip().lower()
        m = re.match(r"^copying (\d+) files", low)
        if m and "copy" in self.by:
            self._start("copy", "%s files" % m.group(1))
        m = re.match(r"^(\d+) of (\d+)$", low)
        if m and "copy" in self.by and self.by["copy"]["state"] == "now":
            self._part("copy", int(m.group(1)) / float(m.group(2)))
            self.by["copy"]["detail"] = "%s of %s files" % (m.group(1), m.group(2))
        if low.startswith("checking the copy") and "check" in self.by:
            self._start("check")
            self._part("copy", 1.0)
            total = re.search(r"of (\d+) files", self.by["copy"]["detail"] or "")
            self.by["copy"]["detail"] = "%s files" % total.group(1) if total else ""
        m = re.match(r"^checked (\d+) of (\d+)$", low)
        if m and "check" in self.by:
            self._part("check", int(m.group(1)) / float(m.group(2)))
            self.by["check"]["detail"] = "%s of %s files" % (m.group(1), m.group(2))
        if low.startswith("reference ready") and "check" in self.by:
            m2 = re.search(r"(\d+) checked", low)
            self.by["check"]["state"], self.by["check"]["detail"] = "done", ("%s files" % m2.group(1)) if m2 else ""
            self._part("check", 1.0)
        m = re.match(r"^stage (\d+) of (\d+): (.*)$", low)
        if m:
            k = int(m.group(1)) - 1
            keys = [st["key"] for st in self.steps if st["key"] not in ("copy", "check")]
            if 0 <= k < len(keys):
                self._start(keys[k])
                self._part(keys[k], 0.0)
                self.say("STAGE " + t.strip()[6:] if t.strip().lower().startswith("stage ") else t)
        # within a step, the extractors print a line per level: count them
        m = re.match(r"^level\s+(\d+)\b", low)
        if m:
            cur = next((st for st in self.steps if st["state"] == "now"
                        and st["key"] not in ("copy", "check")), None)
            if cur is not None:
                seen = cur.setdefault("_levels", set())
                seen.add(int(m.group(1)))
                self._part(cur["key"], len(seen) / 14.0)
                cur["detail"] = "level %d of 14" % len(seen)
        m = re.match(r"^(\w+) done in (\d+)s$", low)
        if m and m.group(1) in self.by:
            st = self.by[m.group(1)]
            st["state"], st["detail"] = "done", "%ss" % m.group(2)
            self._part(m.group(1), 1.0)
        if not low.startswith("stage "):
            self.say(t)
        self._emit()

    def finish(self):
        for st in self.steps:
            st["state"] = "done"
        self.pct = 100.0
        self._emit()
        self.say("STAGE done")


def setup_game(body):
    """Connect the studio to a copy of the game.

    In order: check the folder, copy the levels a mission is rebuilt from into
    the studio's own folder, verify that copy file by file, and only then save
    the setting. A game is never connected without its reference, because from
    then on the studio writes into it.
    """
    from studio.setup import snapshot, verify
    want = (body.get("path") or "").strip()
    if not want:
        return {"ok": False, "error": "no folder given"}
    r = verify.check(want)
    if not r["ok"]:
        return {"ok": False, "error": "that folder cannot be used as the game",
                "missing": r["missing"], "path": r["path"]}

    def work(say=print):
        from studio.setup import data as DATA
        track = SetupProgress(say, reference=True, data=True)
        # another copy of the game (another build, or the same one after a switch
        # from a different build): every file is copied again, not only the ones
        # whose size changed, or a same-sized file of the old game would stay
        same = (snapshot.info() or {}).get("levels") == snapshot.base_fingerprint(r["path"])
        info = snapshot.make(r["path"], log=track.log, force=not same)
        DATA.build(r["path"], log=track.log)
        paths.save({"gamePath": r["path"], "pristinePath": "", "protectedPaths": []})
        track.finish()
        return {"ok": True, "reference": info, **setup_state(load_config())}

    return {"ok": True, "job": run_job(work)}


def setup_snapshot():
    """Copy the parts a mission is rebuilt from, as a job the page can follow."""
    from studio.setup import snapshot, verify
    cfg = load_config()
    game = pathlib.Path(cfg["gamePath"] or "")
    if not (game / "missions" / "location0").is_dir():
        return {"ok": False, "error": "the game has not been found yet"}
    named = cfg.get("pristinePath")
    source = pathlib.Path(named) if named and verify.check(named, deep=False)["ok"] else game

    def work(say=print):
        track = SetupProgress(say, reference=True, data=False)
        info = snapshot.make(source, log=track.log)
        track.finish()
        return {"ok": True, **info}

    return {"ok": True, "job": run_job(work)}


def _data_ready():
    from studio.setup import data as DATA
    return DATA.ready()


def setup_data():
    """Build the level data again, as a job the page can follow."""
    from studio.setup import data as DATA
    game = pathlib.Path(load_config()["gamePath"] or "")
    if not (game / "missions" / "location0").is_dir():
        return {"ok": False, "error": "the game is not there, and the level data is read out of it"}

    def work(say=print):
        track = SetupProgress(say, reference=False, data=True)
        info = DATA.build(game, log=track.log)
        track.finish()
        return {"ok": True, **info}

    return {"ok": True, "job": run_job(work)}


def setup_repair(body):
    """Put drifted built-in missions back from an untouched copy."""
    from studio.setup import repair
    cfg = load_config()
    only = body.get("files") or None
    if not body.get("apply"):
        return {"ok": True, "differences": repair.differences(cfg["gamePath"], deep=True)}
    done = repair.repair(cfg["gamePath"], only=only)
    return {"ok": True, "restored": done,
            "differences": repair.differences(cfg["gamePath"], deep=True)}


def recoverable(cfg):
    """Missions the game holds that the studio does not.

    Every Apply writes the whole mission, plan and all, into the slot's marker
    in the game. So a studio folder that was lost, or moved to another
    machine, can be filled again from the game itself.
    """
    game = cfg["gamePath"]
    known = {m["id"] for m in MS.list_missions()}
    out = []
    try:
        for sl in SL.list_slots(game):
            mk = sl.get("marker") or {}
            mission = mk.get("mission")
            if sl["custom"] and mission and mission.get("id") and mission["id"] not in known:
                out.append({"slot": sl["level"], "id": mission["id"], "name": mission.get("name") or mission["id"],
                            "base": (mission.get("base") or {}).get("level"),
                            "updated": mission.get("updated")})
    except OSError:
        pass
    return out


def recover(cfg, body):
    """Put those missions back into the studio's own folder."""
    want = set(body.get("ids") or [])
    game = cfg["gamePath"]
    done, failed = [], []
    for item in recoverable(cfg):
        if want and item["id"] not in want:
            continue
        mk = SL.read_marker(game, item["slot"]) or {}
        mission = mk.get("mission")
        try:
            MS.write_recovered(mission)
            done.append(item["id"])
        except Exception as e:
            failed.append({"id": item["id"], "error": str(e)})
    return {"ok": not failed, "recovered": done, "failed": failed,
            "missions": MS.list_missions()}


def held_by_game(cfg):
    """{mission id: (slot, marker)} for every mission the connected game holds,
    or None when there is no game to ask (not connected, or its folder is gone).

    The game is the truth of which slot holds which mission. A mission keeps the
    number of the slot it was last applied to, but that is only true of the game
    it was applied to: switch to another copy of the game and that number is
    somebody else's slot, or no slot at all. Every slot the studio fills carries
    a marker naming its mission, so the game can always be asked."""
    game = str(cfg.get("gamePath") or "")
    if not game or not (pathlib.Path(game) / "missions" / "location0").is_dir():
        return None
    held = {}
    for sl in SL.list_slots(game):
        mk = sl.get("marker") or {}
        if sl["custom"] and mk.get("missionId"):
            held.setdefault(mk["missionId"], (sl["level"], mk))
    return held


def in_game(m, held):
    """The mission as the connected game has it: its slot there and what was
    applied there, or not in this game at all. Without a game to ask, as recorded."""
    if held is None:
        return m
    m = dict(m)
    got = held.get(m["id"])
    if not got:
        m["slot"], m["installed"], m["applied"] = None, None, None
        return m
    n, mk = got
    theirs = mk.get("mission") or {}
    m["slot"] = n
    m["installed"] = mk.get("installed") or theirs.get("installed")
    if "applied" in theirs:
        m["applied"] = theirs["applied"]
    return m


def load_in_game(mid, cfg=None):
    return in_game(MS.load(mid), held_by_game(cfg or load_config()))


def library(cfg):
    """Everything the mission library shows."""
    data = paths.data()
    try:
        builtins = json.load((data / "builtins.json").open(encoding="utf-8"))
        needs_setup = False
    except (OSError, ValueError):
        # the built-in missions are read out of the game when it is connected;
        # before that there are none to show, and the page says why
        builtins, needs_setup = {"missions": [], "groups": []}, True
    held = held_by_game(cfg)
    mine = MS.list_missions(view=lambda m: in_game(m, held))
    known = {m["id"] for m in mine}
    game = cfg["gamePath"]
    return {"builtins": builtins["missions"], "groups": builtins["groups"], "missions": mine,
            "slots": game_slots(game, known), "trash": len(MS.list_trash()), "needsSetup": needs_setup,
            "game": {"running": game_running(), "unlockedTo": _unlocked_to(game)}}


def _unlocked_to(game):
    try:
        from studio.build import unlock
        return unlock.active(game) if game else None
    except Exception:
        return None


def game_slots(game, known):
    """Every mission the game holds past its own fourteen, in the game's order,
    as the game lists it: whether the studio made it, whether this studio holds
    it, and whether its marker carries the whole mission (so it can be added)."""
    out = []
    if not game:
        return out
    try:
        for sl in SL.list_slots(game):
            if not sl["custom"]:
                continue
            mk = sl.get("marker") or {}
            d = SL.read_definition(game, sl["level"]) or {}
            mid = mk.get("missionId")
            whole = isinstance(mk.get("mission"), dict) and bool((mk["mission"] or {}).get("plan"))
            out.append({"level": sl["level"], "name": d.get("name") or mk.get("name") or "",
                        "description": d.get("description") or "", "next": d.get("next"),
                        "base": d.get("base") or mk.get("base"), "studio": sl["marker"] is not None,
                        "missionId": mid, "managed": mid in known,
                        # an Apply wrote it all: it can be added to this studio's missions
                        "recoverable": bool(mid) and mid not in known and whole,
                        "installed": mk.get("installed")})
    except OSError:
        pass
    return out


def slots_order(body):
    """POST /api/slots/order {order: [slot numbers, first to last]}."""
    cfg = load_config()
    game = cfg["gamePath"]
    if game_running():
        return {"ok": False, "error": "close the game first: it holds its missions open while it runs"}
    log = []
    try:
        moves = SL.order_slots(game, body.get("order") or [], log=log.append)
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "log": log}
    with _surf_lock:
        _surfaces.clear()
    _HEIGHTS.clear()
    return {"ok": True, "moves": {str(a): b for a, b in moves.items()}, "log": log}


def slot_remove(n):
    """POST /api/slots/<n>/remove: take a mission the studio made out of the game,
    when this studio does not hold it (a mission this studio holds is removed
    from its own card). Kept in backups, as every removal is."""
    cfg = load_config()
    game = cfg["gamePath"]
    if game_running():
        return {"ok": False, "error": "close the game first: it holds its missions open while it runs"}
    mk = SL.read_marker(game, n) or {}
    if mk.get("missionId") and mk["missionId"] in {m["id"] for m in MS.list_missions()}:
        return {"ok": False, "error": "mission %d is one of your missions: remove it from its card" % n}
    log = []
    SL.remove_slot(game, n, log=log.append)
    return {"ok": True, "log": log}


def _data_url_png(u):
    m = re.match(r"data:image/png;base64,(.*)$", u or "", re.S)
    return base64.b64decode(m.group(1)) if m else None


def mission_cleanup(cfg, mid):
    """What to tidy in a mission's plan: placed objects hovering above the bare
    ground under them, and objects placed twice in exactly the same spot.

    The ground is the level as the mission leaves it (_PlanWorld): an empty map
    without the level's buildings, and the mission's own buildings in it, each
    object measured against everything but itself. A desk on the floor of a
    barracks the mission placed stands on that floor; measured against the bare
    level it seemed to hover as high as the floor (0.58 m), and so did the
    doors in its doorways, with nothing to be done about it."""
    from studio.build import surface as SF
    m = MS.load(mid)
    plan = m.get("plan") or {}
    placements = plan.get("placements") or []
    body = {"level": int(m["base"]["level"]), "empty": (m.get("base") or {}).get("kind") == "empty",
            "removeRefs": plan.get("removeRefs") or [],
            "edits": [e for e in (plan.get("edits") or []) if isinstance(e, dict) and e.get("x") is not None],
            "objects": [{"model": p.get("model"), "name": p.get("name"), "x": p["x"], "y": p["y"], "z": p["z"],
                         "gamma": p.get("gamma") or 0, "ref": "own:%s" % p.get("uid")}
                        for p in placements if p.get("type") == "building" and p.get("model")]}
    floating, seen, dups = [], {}, []
    with _PlanWorld(cfg, body) as surf:
        sizes = surf._sizes
        for p in placements:
            if p.get("type") not in ("building", "pickup"):
                continue
            key = (p.get("type"), p.get("model") or p.get("pickupId"), round(p["x"], 2), round(p["y"], 2),
                   round(p["z"], 2), round(p.get("gamma") or 0, 3))
            if key in seen:
                dups.append({"uid": p.get("uid"), "name": p.get("name"), "type": p["type"], "x": p["x"], "y": p["y"],
                             "sameAs": seen[key]})
                continue
            seen[key] = p.get("uid")
            src, z = surf.height(p["x"], p["y"], p["z"], reach_up=0.02, skip="own:%s" % p.get("uid"))
            if z is None or src != "terrain":
                continue                       # only bare ground is certain enough to act on
            rest = z + (0.5 if p["type"] == "pickup" else SF.seat_of(sizes, p.get("model")))
            gap = p["z"] - rest
            if 0.05 < gap < 0.6:
                floating.append({"uid": p.get("uid"), "name": p.get("name"), "type": p["type"],
                                 "x": p["x"], "y": p["y"], "z": p["z"], "rest": round(rest, 3), "gap": round(gap, 3)})
    return {"floating": sorted(floating, key=lambda r: -r["gap"]), "duplicates": dups}


def mission_check(cfg, mid):
    """What the pre-Apply check list needs from the server: which models Apply
    would copy in from other levels and how big they are, plus the objects that
    hover over bare ground or were placed twice."""
    from studio.build import models as MI
    m = load_in_game(mid, cfg)
    plan = m.get("plan") or {}
    game = pathlib.Path(cfg["gamePath"])
    loc0 = game / "missions" / "location0"
    base = int(m["base"]["level"])
    target = loc0 / ("level%d" % base)
    if m.get("slot"):
        mk = SL.read_marker(cfg["gamePath"], m["slot"]) or {}
        if mk.get("missionId") == mid and SL.slot_dir(cfg["gamePath"], m["slot"]).exists():
            target = SL.slot_dir(cfg["gamePath"], m["slot"])
    wanted = [p.get("model") for p in plan.get("placements") or [] if p.get("type") in ("soldier", "building")]
    wanted += [e.get("model") for e in plan.get("edits") or [] if e.get("model")]
    imports = MI.estimate(target, [w for w in wanted if w], loc0)
    imports["into"] = target.name
    return dict(mission_cleanup(cfg, mid), imports=imports)


# Where the build will put everything: a dry run of the build (nothing is
# installed) whose heights.json the editor adopts, so what it shows - the map,
# the 3D close-up - is what the game gets. Cached by the plan's content.
_HEIGHTS = {}
_heights_lock = threading.Lock()


def mission_heights(cfg, mid):
    m = load_in_game(mid, cfg)
    key = MS.plan_hash(m)
    with _heights_lock:
        if _HEIGHTS.get(mid, (None,))[0] == key:
            return _HEIGHTS[mid][1]
        game = pathlib.Path(cfg["gamePath"])
        out = paths.work() / "plan-heights"
        out.mkdir(parents=True, exist_ok=True)
        plan = {"name": m["name"], "base": m["base"]}
        plan.update(m["plan"])
        pf = out / "plan.json"
        pf.write_text(json.dumps(plan), encoding="utf-8")
        args = [sys.executable, "-m", "studio.build.plan", "--plan", str(pf), "--out", str(out),
                "--game", str(game)]
        n = m.get("slot")
        if n:
            mk = SL.read_marker(str(game), n) or {}
            if mk.get("missionId") == mid and SL.slot_dir(str(game), n).exists():
                args += ["--slot-dir", str(SL.slot_dir(str(game), n))]
        hf = out / "heights.json"
        for stale in (hf, out / "walkways.json"):
            if stale.exists():
                stale.unlink()
        try:
            gen = subprocess.run(args, capture_output=True, text=True, cwd=str(ROOT), timeout=180,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            verdict = build_verdict(gen.returncode, gen.stdout, gen.stderr)
        except subprocess.TimeoutExpired:
            verdict = {"ok": None, "errors": [], "warnings": ["the dry run of the build took too long"], "notes": []}
        res = json.loads(hf.read_text(encoding="utf-8")) if hf.exists() else {"placements": {}, "edits": {}}
        wf = out / "walkways.json"
        res["walkways"] = json.loads(wf.read_text(encoding="utf-8")) if wf.exists() else None
        res["hash"] = key
        res["build"] = verdict
        _HEIGHTS[mid] = (key, res)
        return res


# What Apply would say, from the same dry run: the build's own verdict, so the
# check list (and the AI designer's check_mission) reports what Apply refuses,
# not a guess at it. errors: why the plan would be rejected; warnings: what the
# build changes or leaves out on its own; notes: what it did that the plan did
# not say (a guard moved onto another walkway graph, a node with no links).
NOTE = re.compile(r"now on that graph|linked to \[\]|left out|removed node|joined again")


def build_verdict(code, out, err):
    lines = (out or "").splitlines()
    errors = [l.strip()[2:].strip() for l in lines if l.startswith("   x ")]
    warnings = [l.strip()[2:].strip() for l in lines if l.startswith("  ! ")]
    notes = [l.strip() for l in lines if NOTE.search(l) and not l.startswith(("   x ", "  ! "))]
    if code and not errors:
        tail = [l for l in (err or "").splitlines() if l.strip()][-3:] or [l for l in lines if l.strip()][-2:]
        errors = [" / ".join(tail)[:400] or "the build stopped (exit %s)" % code]
    return {"ok": not code, "errors": errors[:30], "warnings": warnings[:30], "notes": notes[:30]}


GROUPS = paths.missions() / "groups"


def groups_list():
    """Saved groups (reusable sets of objects), newest first."""
    out = []
    for f in GROUPS.glob("*.json"):
        try:
            out.append(json.load(f.open(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda g: -g.get("created", 0))


# The inventory's "Your items": what the user (or the AI designer) keeps to
# place again in any mission, each under one of these.
ITEM_CATS = ("areas", "buildings", "characters", "objects", "weapons", "security")


def group_save(b):
    name = str(b.get("name") or "").strip()[:80]
    data = b.get("data")
    if not name or not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("an item needs a name and what it holds")
    gid = "%s-%s" % (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "group",
                     base64.b32encode(os.urandom(4)).decode().lower().rstrip("=")[:6])
    g = {"id": gid, "name": name, "summary": str(b.get("summary") or "")[:200],
         "created": int(time.time() * 1000), "data": data}
    # made by the AI designer: a structure of parts, or a character
    if b.get("kind") in ("blueprint", "character"):
        g["kind"] = b["kind"]
    if b.get("description"):
        g["description"] = str(b.get("description"))[:300]
    if b.get("cat") in ITEM_CATS:
        g["cat"] = b["cat"]
    GROUPS.mkdir(parents=True, exist_ok=True)
    (GROUPS / (gid + ".json")).write_text(json.dumps(g, indent=1), encoding="utf-8")
    return g


def group_update(gid, b):
    """Rename an item of the user's, or put it under another category."""
    if not re.fullmatch(r"[a-z0-9-]+", gid or ""):
        raise ValueError("bad group id")
    f = GROUPS / (gid + ".json")
    if not f.exists():
        raise FileNotFoundError(gid)
    g = json.load(f.open(encoding="utf-8"))
    if b.get("name") is not None:
        name = str(b["name"]).strip()[:80]
        if not name:
            raise ValueError("an item needs a name")
        g["name"] = name
    if b.get("cat") is not None:
        if b["cat"] not in ITEM_CATS:
            raise ValueError("no such category: %s" % b["cat"])
        g["cat"] = b["cat"]
    if b.get("description") is not None:
        g["description"] = str(b["description"])[:300]
    f.write_text(json.dumps(g, indent=1), encoding="utf-8")
    return g


def group_delete(gid):
    if not re.fullmatch(r"[a-z0-9-]+", gid or ""):
        raise ValueError("bad group id")
    f = GROUPS / (gid + ".json")
    if not f.exists():
        raise FileNotFoundError(gid)
    f.unlink()


_live = None


def live_reader():
    """One reader of the running game for the whole server (Windows only)."""
    global _live
    if _live is None:
        from studio.server import live_pos
        _live = live_pos.LiveReader()
    return _live


def live_calibrate(b):
    r = live_reader()
    start = (float(b["x"]), float(b["y"]), float(b["z"]))
    box = tuple(b["box"]) if b.get("box") else None
    r.status, r.message = "scanning", "looking for your position in the game's memory..."
    threading.Thread(target=r.calibrate, args=(start, box, bool(b.get("manual"))), daemon=True).start()
    return dict(r.state(), status="scanning", message="looking for your position in the game's memory...")


_surfaces = {}
_surf_lock = threading.Lock()


def surface_for(cfg, lv):
    """The level's walkable surfaces, built once and kept until the next Apply."""
    from studio.build import surface as SF
    key = (str(paths.levels(cfg["gamePath"])), lv)
    with _surf_lock:
        if key not in _surfaces:
            data = paths.data()
            level_dir = paths.levels(cfg["gamePath"]) / "missions" / "location0" / ("level%d" % lv)
            qsc = qvm_source.level_qsc(lv, cfg["gamePath"])
            objects = json.load((data / ("level%d.json" % lv)).open())["objects"]
            sizes = json.load((data / "models.json").open())["sizes"]
            gp = data / ("graphs%d.json" % lv)
            nodes = [n for g in json.load(gp.open()).values() for n in g.get("nodes", [])] if gp.exists() else []
            _surfaces[key] = SF.Surface(level_dir, qsc, objects, sizes, nodes=nodes)
        return _surfaces[key]


class _PlanWorld:
    """The level's surfaces as a mission leaves them, for the length of one query:
    an empty map has none of the level's objects, removed objects are gone, moved
    ones stand where they were moved, and the mission's own buildings count."""

    def __init__(self, cfg, body):
        self.s = surface_for(cfg, int(body.get("level") or cfg["slot"]))
        self.body = body

    def __enter__(self):
        s, b = self.s, self.body
        _surf_lock.acquire()
        self.keep = s.objects
        gone = set(b.get("removeRefs") or [])
        moved = {e["ref"]: e for e in (b.get("edits") or []) if e.get("ref") and e.get("x") is not None}
        objs = [] if b.get("empty") else [(o, r) for o, r in s.objects
                                          if o.get("ref") not in gone and o.get("ref") not in moved]
        if not b.get("empty"):
            for o, _ in self.keep:
                e = moved.get(o.get("ref"))
                if e:
                    c = dict(o)
                    c.update({k: e[k] for k in ("x", "y", "z", "gamma") if e.get(k) is not None})
                    objs.append((c, s.radius(c)))
        for o in b.get("objects") or []:
            if o.get("model") in s._sizes:
                objs.append((dict(o, type="building"), s.radius(o)))
        s.objects = objs
        return s

    def __exit__(self, *exc):
        self.s.objects = self.keep
        _surf_lock.release()


def links_cut(cfg, body):
    """For each pair [a, b] of walkway points (world metres, feet), the solid thing
    a guard walking from one to the other would pass through, or None: the test
    Apply puts every new walkway link to (graphs.add_node's link_ok), on the
    level as the mission leaves it."""
    out = []
    with _PlanWorld(cfg, body) as s:
        for pr in (body.get("pairs") or [])[:4000]:
            a, b = tuple(float(v) for v in pr[:3]), tuple(float(v) for v in pr[3:6])
            o = s.blocked(a, b)
            out.append(None if o is None else str(o.get("name") or o.get("model") or "something solid"))
    return out


def ground_at(cfg, body):
    """Where each point comes to rest: [{z, on}] - a guard's feet, a pickup, a
    model's origin. The editor asks whenever something is placed or moved."""
    world = _PlanWorld(cfg, body)
    out = []
    with world as s:
        for pt in body.get("points") or []:
            z, on = s.rest(pt.get("kind") or "soldier", float(pt["x"]), float(pt["y"]),
                           None if pt.get("z") is None else float(pt["z"]), pt.get("model"), skip=pt.get("ref"),
                           gamma=float(pt.get("gamma") or 0))
            spread = (s.last or {}).get("spread")
            out.append({"z": None if z is None else round(z, 3), "on": on,
                        "spread": None if spread is None else round(spread, 2)})
    return out


def surfaces_at(cfg, body):
    """Every height something could stand on at a point: the ground, the tops of
    tables, crates, shelves and platforms (the level's and the plan's own), and
    the floors nodes stand on. Nearest first is up to the editor."""
    lv = int(body.get("level") or cfg["slot"])
    x, y = float(body["x"]), float(body["y"])
    s = surface_for(cfg, lv)
    gone = set(body.get("removeRefs") or [])
    moved = {e["ref"]: e for e in (body.get("edits") or []) if e.get("ref")}
    if body.get("empty"):
        gone |= {o.get("ref") for o, _ in s.objects}
    out = []
    if s.terrain is not None:
        t = s.terrain.z(x, y)
        if t is not None:
            out.append({"kind": "ground", "z": t, "label": "ground"})
    for o, r in s.objects:
        if o.get("ref") in gone or o.get("ref") in moved:
            continue
        for _, z, _ in s.tops(o, x, y, r):
            out.append({"kind": "top", "z": z, "label": o.get("modelName") or o.get("model"), "model": o.get("model")})
    extra = list(body.get("objects") or [])
    for ref, e in moved.items():
        base = next((o for o, _ in s.objects if o.get("ref") == ref), None)
        if base is not None:
            c = dict(base)
            c.update({k: e[k] for k in ("x", "y", "z", "gamma") if e.get(k) is not None})
            extra.append(c)
    for o in extra:
        if not o.get("model") or o.get("model") not in s._sizes:
            continue
        for _, z, _ in s.tops(o, x, y):
            out.append({"kind": "top", "z": z, "label": o.get("modelName") or o.get("name") or o.get("model"),
                        "model": o.get("model")})
    for nx, ny, nz in s.nodes:
        if (nx - x) ** 2 + (ny - y) ** 2 <= 2.5 ** 2:
            out.append({"kind": "floor", "z": nz, "label": "floor"})
    # one entry per height (5 cm), the most telling label winning
    rank = {"top": 0, "floor": 1, "ground": 2}
    best = {}
    for c in out:
        k = round(c["z"] * 20)
        if k not in best or rank[c["kind"]] > rank[best[k]["kind"]]:
            best[k] = dict(c, z=round(c["z"], 3))
    return sorted(best.values(), key=lambda c: c["z"])


class Handler(SimpleHTTPRequestHandler):
    # without a charset the browser guesses Windows-1252 and every em dash in
    # the page shows up as "â€""
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".html": "text/html; charset=utf-8",
                      ".js": "text/javascript; charset=utf-8",
                      ".json": "application/json; charset=utf-8"}

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(EDITOR), **kw)

    def parse_request(self):
        if not super().parse_request():
            return False
        if TOKEN and not hmac.compare_digest(self.headers.get("X-Studio-Token", ""), TOKEN):
            self.send_error(403, "This studio answers only its own window")
            return False
        return True

    def translate_path(self, path):
        # The editor asks for data/... relative to the page. That data is made
        # from the person's own game and kept in their folder, so it is served
        # from there, not from beside the code.
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/data/") or clean == "/data":
            rel = clean[len("/data"):].lstrip("/")
            target = (paths.data() / rel).resolve()
            base = paths.data().resolve()
            if target == base or base in target.parents:
                return str(target)
            return str(base / "__outside__")          # a ../ trick gets a 404
        return super().translate_path(path)

    def log_message(self, fmt, *args):
        # args[0] is an HTTPStatus, not the request line, when logging an error
        if "/api/" in str(args[0] if args else ""):
            sys.stderr.write("   %s\n" % (fmt % args))

    # ------------------------------------------------------------------ helpers
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # ------------------------------------------------------------------ routes
    def end_headers(self):
        # level data is rewritten every time a plan is applied, so a cached copy
        # is worse than no copy - the editor would show the mission as it was
        # before the build
        if self.path.endswith((".json", ".js", ".html")):
            self.send_header("Cache-Control", "no-store, must-revalidate")
        # The page loads nothing that is not its own, and talks to nothing but
        # this server: no script from elsewhere, and no request that could carry
        # a mission (or a key) off the machine. The AI's calls leave through the
        # server's own proxy. Inline scripts stay allowed until the editor's
        # main script is split into files.
        if self.path.split("?", 1)[0].endswith((".html", "/")):
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                             "font-src 'self'; connect-src 'self'; worker-src 'self' blob:; "
                             "object-src 'none'; base-uri 'none'; form-action 'none'; "
                             "frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _game(self):
        g = load_config().get("gamePath")
        if not g:
            raise FileNotFoundError("the studio has not been pointed at the game yet")
        return g

    def _send_track(self, tid):
        """A track as a WAV, whole or the byte range the player asks for (it
        seeks by asking for one)."""
        head, f, off, n = MU.preview(self._game(), tid)
        total = len(head) + n
        a, b = 0, total - 1
        rng = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                a = int(rng.group(1))
                b = min(total - 1, int(rng.group(2))) if rng.group(2) else total - 1
            else:
                a = max(0, total - int(rng.group(2)))
            if a > b or a >= total:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % total)
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, total))
        else:
            self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b - a + 1))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        pos = a
        if pos < len(head):
            self.wfile.write(head[pos:min(len(head), b + 1)])
            pos = len(head)
        with open(f, "rb") as fh:
            fh.seek(off + pos - len(head))
            left = b + 1 - pos
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def _mission_route(self):
        """(mission id, action) for /api/missions/<id>[/<action>]."""
        m = re.match(r"^/api/missions/([a-z0-9-]+)(?:/([a-z.]+))?/?(?:\?.*)?$", self.path)
        return (m.group(1), m.group(2)) if m else (None, None)

    def _guard(self, fn):
        try:
            return fn()
        except protect.ProtectedPath as e:
            return self._json({"ok": False, "error": str(e), "protected": True}, 403)
        except FileNotFoundError as e:
            return self._json({"ok": False, "error": "not found: %s" % e}, 404)
        except (ValueError, FileExistsError) as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            return self._json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)

    def _thread_route(self):
        """(mission id, thread id or None) for /api/missions/<id>/ai[/<thread>]."""
        m = re.match(r"^/api/missions/([a-z0-9-]+)/ai(?:/([a-z0-9-]+))?/?(?:\?.*)?$", self.path)
        return (m.group(1), m.group(2)) if m else (None, None)

    def do_PUT(self):
        gm = re.match(r"^/api/groups/([a-z0-9-]+)$", self.path)
        if gm:
            return self._guard(lambda: self._json({"ok": True, "group": group_update(gm.group(1), self._body())}))
        tm, tid = self._thread_route()
        if tm and tid:
            return self._guard(lambda: self._json({"ok": True, **AI.save_thread(MS.STORE, tm, tid, self._body())}))
        mid, action = self._mission_route()
        if mid and action == "ai":
            return self._guard(lambda: self._json({"ok": AI.save_chat(MS.STORE, mid, self._body())}))
        if not mid or action:
            return self.send_error(404)

        def go():
            b = self._body()
            m = MS.save(mid, plan=b.get("plan"), name=b.get("name"), description=b.get("description"),
                        cover_png=_data_url_png(b.get("cover")), applied=b.get("applied"))
            if "picture" in b:
                m = MS.set_picture(mid, _data_url_png(b["picture"]) if b["picture"] else None)
            # a renamed mission that is in the game is renamed in the game's list too
            if b.get("name") is not None or b.get("description") is not None:
                cfg = load_config()
                n = ((held_by_game(cfg) or {}).get(mid) or (None,))[0]
                if n:
                    SL.write_definition(cfg["gamePath"], n, m["base"]["level"], m["name"], m.get("description"))
            return self._json({"ok": True, "mission": MS.summary(in_game(m, held_by_game(load_config())))})
        return self._guard(go)

    def do_DELETE(self):
        tm, tid = self._thread_route()
        if tm and tid:
            return self._guard(lambda: self._json({"ok": AI.delete_thread(MS.STORE, tm, tid)}))
        rm, rid = self._run_route()
        if rm and rid:
            return self._guard(lambda: (MS.delete_run(rm, rid), self._json({"ok": True}))[1])
        gm = re.match(r"^/api/groups/([a-z0-9-]+)$", self.path)
        if gm:
            return self._guard(lambda: (group_delete(gm.group(1)), self._json({"ok": True}))[1])
        # the trash: one mission for good, or all of them
        tr = re.match(r"^/api/trash/([a-z0-9-]+--\d+)$", self.path)
        if tr:
            return self._guard(lambda: (MS.purge(tr.group(1)), self._json({"ok": True}))[1])
        if re.match(r"^/api/trash/?$", self.path):
            return self._guard(lambda: self._json({"ok": True, "gone": MS.purge_all()}))
        mid, action = self._mission_route()
        if not mid or action:
            return self.send_error(404)

        def go():
            n = int(self.headers.get("Content-Length") or 0)
            b = json.loads(self.rfile.read(n) or b"{}") if n else {}
            cfg = load_config()
            m = load_in_game(mid, cfg)
            log = []
            if m.get("slot") and b.get("removeFromGame", True):
                mk = SL.read_marker(cfg["gamePath"], m["slot"]) or {}
                if mk.get("missionId") == mid and SL.slot_dir(cfg["gamePath"], m["slot"]).exists():
                    SL.remove_slot(cfg["gamePath"], m["slot"], log=log.append)
            tid = MS.delete(mid)
            return self._json({"ok": True, "trashId": tid, "log": log})
        return self._guard(go)

    # ---- the 3D close-up: textured models and their textures, read from the
    # pristine install (studio/extract/model3d.py) - read-only, cached decoded PNGs
    def _query(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _assets(self):
        cfg = load_config()
        return M3.library(cfg["gamePath"])

    def _model3d(self):
        q = self._query()
        m = self._assets().model(q.get("name", ""), int(q.get("level") or 0))
        if m is None:
            return self._json({"ok": False, "error": "no such model"}, 404)
        return self._json({"ok": True, "model": m})

    def _modeltextures(self):
        """GET /api/modeltextures?name=X&level=N: the textures a model is drawn
        with, in the order its render groups use them (the mission's own
        textures go in the place of these)."""
        q = self._query()
        lib = self._assets()
        name = q.get("name", "")
        home = lib.home_of(name, int(q.get("level") or 0))      # an imported model's own level
        names = lib.textures_of(name, home)
        return self._json({"ok": True, "textures": list(names), "home": home})

    def _groundtex(self):
        """GET /api/groundtex?level=N&mat=M: a ground material's own texture, as the
        level's terrain.tex has it (the first of the set the material is drawn with
        most), for the Paint tool's preview. Read from the pristine install."""
        q = self._query()
        body = ground_texture(int(q.get("level") or 0), int(q.get("mat") or 0))
        if not body:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _texture(self):
        q = self._query()
        try:
            r = self._assets().texture(q.get("name", ""), int(q.get("level") or 0), int(q.get("size") or 512))
        except Exception:
            r = None
        if not r:
            return self.send_error(404)
        body = r[0]
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _run_route(self):
        """(mission id, run id or "") for /api/missions/<id>/runs[/<run id>]."""
        m = re.match(r"^/api/missions/([a-z0-9-]+)/runs(?:/(\d+))?/?$", self.path)
        return (m.group(1), m.group(2) or "") if m else (None, None)

    def do_GET(self):
        rm, rid = self._run_route()
        if rm:
            if rid:
                return self._guard(lambda: self._json({"ok": True, "run": MS.load_run(rm, rid)}))
            return self._guard(lambda: self._json({"ok": True, "runs": MS.list_runs(rm)}))
        if self.path.startswith("/api/model3d"):
            return self._guard(self._model3d)
        if self.path.startswith("/api/modeltextures"):
            return self._guard(self._modeltextures)
        if self.path.startswith("/api/texture"):
            return self._texture()
        if self.path.startswith("/api/groundtex"):
            return self._groundtex()
        if self.path.startswith("/api/library"):
            return self._guard(lambda: self._json({"ok": True, **library(load_config())}))
        if re.match(r"^/api/music/?(?:\?.*)?$", self.path):
            return self._guard(lambda: self._json({"ok": True, "tracks": MU.tracks(self._game())}))
        mu = re.match(r"^/api/music/([a-z0-9]+)\.wav(?:\?.*)?$", self.path)
        if mu:
            return self._guard(lambda: self._send_track(mu.group(1)))
        if self.path.startswith("/api/trash"):
            return self._guard(lambda: self._json({"ok": True, "trash": MS.list_trash()}))
        mid, action = self._mission_route()
        if mid and action in ("cover.png", "picture.png"):
            f = MS.STORE / mid / action
            if not f.exists():
                return self.send_error(404)
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        tm, tid = self._thread_route()
        if tm and tid:
            return self._guard(lambda: self._json({"ok": True, "thread": AI.load_thread(MS.STORE, tm, tid)}))
        if tm:
            return self._guard(lambda: self._json({"ok": True, "threads": AI.list_threads(MS.STORE, tm)}))
        if self.path.startswith("/api/ai/settings"):
            return self._json({"ok": True, **AI.public(load_config())})
        if self.path.startswith("/api/ai/models"):
            role = "light" if "role=light" in self.path else "main"
            mid = (parse_qs(urlparse(self.path).query).get("id") or [None])[0]
            return self._guard(lambda: self._json({"ok": True, "models": AI.models(load_config(), role, mid)}))
        if mid and action == "cleanup":
            return self._guard(lambda: self._json({"ok": True, **mission_cleanup(load_config(), mid)}))
        if mid and action == "check":
            return self._guard(lambda: self._json({"ok": True, **mission_check(load_config(), mid)}))
        if mid and action == "heights":
            return self._guard(lambda: self._json({"ok": True, **mission_heights(load_config(), mid)}))
        if mid and not action:
            return self._guard(lambda: self._json({"ok": True, "mission": load_in_game(mid)}))
        jm = re.match(r"^/api/jobs/([a-z0-9]+)$", self.path)
        if jm:
            job = JOBS.get(jm.group(1))
            if job is not None:
                job["elapsed"] = round(time.time() - job["started"], 1)
            if not job:
                return self._json({"ok": False, "error": "no such job"}, 404)
            return self._json(dict(job, ok=True, elapsed=round(time.time() - job["started"], 1)))
        if self.path.startswith("/api/live"):
            return self._guard(lambda: self._json({"ok": True, **live_reader().read()}))
        if self.path.startswith("/api/groups"):
            return self._guard(lambda: self._json({"ok": True, "groups": groups_list()}))
        if self.path.startswith("/api/recoverable"):
            return self._guard(lambda: self._json({"ok": True, "missions": recoverable(load_config())}))
        if self.path.startswith("/api/setup/check"):
            # is this folder a copy of the game? (Settings, Game: before connecting it)
            def check():
                from studio.setup import verify
                want = (parse_qs(urlparse(self.path).query).get("path") or [""])[0].strip()
                if not want:
                    return self._json({"ok": False, "error": "no folder given"})
                r = verify.check(want)
                cur = str(load_config().get("gamePath") or "")
                same = bool(cur) and os.path.normcase(os.path.abspath(cur)) == os.path.normcase(os.path.abspath(want))
                return self._json({"ok": True, "usable": r["ok"], "path": r["path"], "missing": r["missing"],
                                   "levels": r.get("levels"), "custom": r.get("custom") or [], "build": r.get("profileName"),
                                   "nearest": r.get("nearest"), "differs": r.get("differs"),
                                   "exe": (pathlib.Path(want) / "IGI.exe").exists(), "current": same})
            return self._guard(check)
        if self.path.startswith("/api/setup"):
            find = "find=1" in self.path
            return self._guard(lambda: self._json(setup_state(load_config(), find)))
        if self.path.startswith("/api/status"):
            return self._json({"ok": True, **game_state(load_config())})
        if self.path.startswith("/api/config"):
            return self._json({k: v for k, v in load_config().items() if k != "ai"})
        return super().do_GET()

    def _ai_chat(self):
        """One model turn, streamed as JSON lines while it comes (see ai_proxy)."""
        body = self._body()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.close_connection = True
        state = {"open": True}

        def emit(e):
            if not state["open"]:
                return
            try:
                self.wfile.write((json.dumps(e) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                state["open"] = False           # the editor pressed Stop
        try:
            AI.chat(load_config(), body, emit, alive=lambda: state["open"])
        except Exception as e:
            emit({"t": "error", "message": "%s: %s" % (type(e).__name__, e)})

    def do_POST(self):
        try:
            if self.path.startswith("/api/ai/chat"):
                return self._ai_chat()
            if self.path.startswith("/api/ai/settings"):
                body = self._body()
                try:
                    cfg = AI.update(load_config(), body)
                except ValueError as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
                save_config(cfg)
                return self._json({"ok": True, **AI.public(cfg), "savedId": body.get("_savedId")})
            if self.path.startswith("/api/ai/test"):
                mid = (parse_qs(urlparse(self.path).query).get("id") or [None])[0]
                ok, msg = AI.test(load_config(), "light" if "role=light" in self.path else "main", mid)
                return self._json({"ok": ok, "message": msg})
            if self.path.startswith("/api/config"):
                cfg = load_config()
                body = self._body()
                if "gamePath" in body and str(body["gamePath"]).strip() != str(cfg.get("gamePath") or "").strip():
                    # a game is only ever connected through the setup, which makes
                    # the studio's reference copy of it first (POST /api/setup/game)
                    return self._json({"ok": False, "error": "a game is connected through the setup, which "
                                       "copies its levels first: Settings, Game, Change"}, 409)
                if "slot" in body:
                    cfg["slot"] = int(body["slot"])
                save_config(cfg)
                return self._json({"ok": True, **game_state(cfg)})

            if self.path.startswith("/api/apply"):
                return self._json({"ok": False, "error": "Apply now builds a mission from its base level: "
                                   "reload the editor and apply from the mission"}, 410)

            if re.match(r"^/api/missions/?$", self.path):
                def create():
                    b = self._body()
                    base = b.get("base") or {}
                    m = MS.create(b.get("name") or "Untitled mission", base.get("level") or 1,
                                  base.get("kind") or "copy", b.get("description") or "", copy_from=b.get("from"))
                    if b.get("music") is not None:
                        if b["music"] and not MU.TRACK_ID.match(str(b["music"])):
                            raise ValueError("no such track: %r" % b["music"])
                        m["plan"].setdefault("settings", {})
                        if b["music"]:
                            m["plan"]["settings"]["music"] = str(b["music"])
                        else:
                            m["plan"]["settings"].pop("music", None)
                        m = MS.save(m["id"], plan=m["plan"])
                    if b.get("picture"):
                        m = MS.set_picture(m["id"], _data_url_png(b["picture"]))
                    return self._json({"ok": True, "mission": m})
                return self._guard(create)

            m = re.match(r"^/api/trash/([a-z0-9-]+--\d+)/restore$", self.path)
            if m:
                return self._guard(lambda: self._json({"ok": True, "mission": MS.restore(m.group(1))}))

            mid, action = self._mission_route()
            if mid and action == "duplicate":
                def dup():
                    b = self._body()
                    src = MS.load(mid)
                    c = MS.create(b.get("name") or src["name"] + " copy", src["base"]["level"], copy_from=mid)
                    return self._json({"ok": True, "mission": c})
                return self._guard(dup)
            if mid and action == "apply":
                def sync():
                    lines = []
                    res = apply_mission(mid, say=lambda x: lines.append(str(x)[6:] if str(x).startswith("STAGE ") else str(x)))
                    res["log"] = lines
                    return self._json(res)
                return self._guard(sync)
            if mid and action == "applyjob":
                def aj():
                    t = (self._body() or {}).get("test")
                    t = t if isinstance(t, dict) and all(k in t for k in ("x", "y", "z")) else None
                    return self._json({"ok": True, "job": run_job(apply_mission, mid, t)["id"]})
                return self._guard(aj)
            if mid and action == "uninstall":
                def un():
                    cfg = load_config()
                    mm = load_in_game(mid, cfg)
                    log = []
                    mk = (SL.read_marker(cfg["gamePath"], mm["slot"]) or {}) if mm.get("slot") else {}
                    if mk.get("missionId") == mid and SL.slot_dir(cfg["gamePath"], mm["slot"]).exists():
                        SL.remove_slot(cfg["gamePath"], mm["slot"], log=log.append)
                    return self._json({"ok": True, "mission": MS.summary(MS.mark_uninstalled(mid)), "log": log})
                return self._guard(un)

            if re.match(r"^/api/groups/?$", self.path):
                return self._guard(lambda: self._json({"ok": True, "group": group_save(self._body())}))
            rm, rid = self._run_route()
            if rm and not rid:
                return self._guard(lambda: self._json({"ok": True, **MS.save_run(rm, self._body())}))
            if re.match(r"^/api/slots/order/?$", self.path):
                return self._guard(lambda: self._json(slots_order(self._body())))
            sm = re.match(r"^/api/slots/(\d+)/remove/?$", self.path)
            if sm:
                return self._guard(lambda: self._json(slot_remove(int(sm.group(1)))))
            if self.path.startswith("/api/recover"):
                return self._guard(lambda: self._json(recover(load_config(), self._body())))
            if self.path.startswith("/api/setup/game"):
                return self._guard(lambda: self._json(setup_game(self._body())))
            if self.path.startswith("/api/setup/data"):
                return self._guard(lambda: self._json(setup_data()))
            if self.path.startswith("/api/setup/snapshot"):
                return self._guard(lambda: self._json(setup_snapshot()))
            if self.path.startswith("/api/setup/repair"):
                return self._guard(lambda: self._json(setup_repair(self._body())))
            if self.path.startswith("/api/launch"):
                return self._guard(lambda: self._json(launch_game(load_config())))
            if self.path.startswith("/api/live/calibrate"):
                return self._guard(lambda: self._json({"ok": True, **live_calibrate(self._body())}))
            if self.path.startswith("/api/live/stop"):
                def stop():
                    r = live_reader()
                    with r.lock:
                        r.reset()
                    return self._json({"ok": True, **r.state()})
                return self._guard(stop)

            if self.path.startswith("/api/ground"):
                return self._json({"ok": True, "points": ground_at(load_config(), self._body())})

            if self.path.startswith("/api/links"):
                return self._json({"ok": True, "cut": links_cut(load_config(), self._body())})

            if self.path.startswith("/api/surfaces"):
                return self._json({"ok": True, "surfaces": surfaces_at(load_config(), self._body())})

            self.send_error(404)
        except Exception as e:
            self._json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)



# ------------------------------------------------------------------ jobs
# Apply takes a while (copying a level, building, compiling, importing models),
# so it runs in the background and the editor polls it for progress.
JOBS = {}
STAGES = [("copying level", 8), ("building the level script", 20), ("plan \"", 40), ("compiling and installing", 55),
          ("importing family", 62), ("imported ", 68), ("terrain.hmp", 72), ("mission strings", 76),
          ("installed objects.qvm", 82), ("ai script", 86), ("graphs:", 90), ("checking the installed", 94),
          ("done - launch", 100)]


def run_job(fn, *args):
    jid = base64.b32encode(os.urandom(5)).decode().lower().rstrip("=")
    job = {"id": jid, "lines": [], "stage": "starting", "detail": "", "pct": 2, "done": False, "result": None,
           "started": time.time()}
    JOBS[jid] = job

    def say(x):
        x = str(x)
        # structured progress from a job that knows better than the keywords
        if x.startswith("PCT "):
            try:
                job["pct"] = max(job["pct"], min(100, int(float(x[4:]))))
            except ValueError:
                pass
            return
        if x.startswith("STEPS "):
            try:
                job["steps"] = json.loads(x[6:])
            except ValueError:
                pass
            return
        text = x[6:] if x.startswith("STAGE ") else x
        low = text.lower()
        for key, pct in STAGES:
            if key in low and pct > job["pct"]:
                job["pct"] = pct
        if x.startswith("STAGE "):
            job["stage"], job["detail"] = text, ""
        else:
            job["lines"].append(text)
            if text.strip():
                job["detail"] = text.strip()

    def go():
        try:
            res = fn(*args, say=say)
        except protect.ProtectedPath as e:
            res = {"ok": False, "error": str(e), "protected": True}
        except Exception as e:
            res = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        res["log"] = job["lines"]
        job["result"], job["done"], job["pct"] = res, True, 100 if res.get("ok") else job["pct"]
        job["stage"] = "done" if res.get("ok") else "failed"
    threading.Thread(target=go, daemon=True).start()
    # forget jobs finished more than an hour ago
    for k in [k for k, v in JOBS.items() if v["done"] and time.time() - v["started"] > 3600]:
        JOBS.pop(k, None)
    return job


_GROUND_SETS = {}


def ground_texture(level, mat):
    """PNG of a ground material's texture (256 x 256), cached in cache/ground."""
    from studio.extract import ground as BG
    cache = paths.cache() / "ground" / ("level%d_%d.png" % (level, mat))
    if cache.exists():
        return cache.read_bytes()
    cfg = load_config()
    tdir = paths.levels(cfg["gamePath"]) / "missions" / "location0" / ("level%d" % level) / "terrain"
    if not (tdir / "terrain.tex").exists():
        return None
    if level not in _GROUND_SETS:
        _GROUND_SETS[level] = BG.material_sets(tdir, level)
    b, n, w, h, offs = BG.read_textures(tdir / "terrain.tex")
    use = {st: k for st, k in (_GROUND_SETS[level].get(mat) or {}).items() if st * 3 < n}
    t = (max(use, key=lambda st: use[st]) * 3) if use else min(mat * 3, n - 1)
    if t >= len(offs):
        return None
    off, step = offs[t], max(1, w // 256)
    W, H = w // step, h // step
    rgba = bytearray(W * H * 4)
    for j in range(H):
        for i in range(W):
            o = off + ((j * step) * w + i * step) * 4
            k = (j * W + i) * 4
            rgba[k], rgba[k + 1], rgba[k + 2], rgba[k + 3] = b[o + 2], b[o + 1], b[o], 255
    png = M3._png(W, H, bytes(rgba))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(png)
    return png


def _player_ref(level):
    """The level's player start, by the reference an edit names it with."""
    try:
        meta = json.loads((paths.data() / ("level%d.json" % int(level))).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return next((o for o in meta.get("objects", []) if o.get("type") == "player" and o.get("ref")), None)


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq IGI.exe", "/NH"], capture_output=True, text=True,
                             creationflags=0x08000000).stdout
        return "igi.exe" in out.lower()
    except OSError:
        return False


def keep_unlocked(every=5.0):
    """The game keeps its settings in memory and writes them back when it closes,
    and finishing a mission sets how far its list goes as well: either can take
    away the missions the studio unlocked. So whenever the game is not running -
    when the studio starts, and each time the game closes - the list is made to
    reach the last mission in the game again, and each of the studio's missions
    leads on to the next (slots made by an older version were not linked)."""
    from studio.build import unlock
    was = None
    while True:
        now = game_running()
        if not now and was is not False:
            try:
                game = load_config().get("gamePath")
                if game and (pathlib.Path(game) / "missions" / "location0").is_dir():
                    say = lambda x: print("  " + x, flush=True)
                    SL.relink(str(game), say)
                    unlock.reach_all(str(game), log=say)
            except Exception as e:
                print("  the game's mission list was left as it was: %s" % e, flush=True)
        was = now
        time.sleep(every)


def launch_game(cfg, say=print):
    """Start IGI.exe in the working game's folder (never the pristine one)."""
    game = pathlib.Path(cfg["gamePath"])
    exe = game / "IGI.exe"
    if not exe.exists():
        return {"ok": False, "error": "IGI.exe is not in %s" % game}
    if game_running():
        say("the game is already running: leave the mission and pick it again to load the new build")
        return {"ok": True, "running": True}
    # the game writes its settings back when it closes, which can undo how far
    # its mission list goes: set it again before it starts
    try:
        from studio.build import unlock
        unlock.reach_all(str(game), log=say)
    except Exception as e:
        say("the game's mission list was left as it was: %s" % e)
    subprocess.Popen([str(exe)], cwd=str(game), creationflags=0x00000008 | 0x00000200)   # detached, own group
    say("starting the game")
    return {"ok": True, "started": True}


def apply_mission(mid, test=None, say=print):
    """Build a mission from its pristine base plus its whole plan and install it
    in the mission's own slot. Nothing is built on top of an earlier build, so
    applying twice gives the same game, and nothing applied is ever lost.
    test {x, y, z, gamma, launch}: a test build, the player starting there (the
    saved plan keeps its own start), and the game started after it."""
    cfg = load_config()
    game = cfg["gamePath"]
    if not game:
        return {"ok": False, "error": "the studio has not been pointed at the game yet"}
    if not (pathlib.Path(game) / "missions" / "location0").is_dir():
        return {"ok": False, "error": "the game folder %s is not there any more, so nothing was "
                                      "written. Your missions are safe in %s. Point the studio at "
                                      "the game again when it is back." % (game, paths.home())}
    # Nothing is written to the game until the studio holds its own copy of the
    # levels a mission is rebuilt from. It is made when the game is connected;
    # if it is not there, it is made now, before anything else happens.
    from studio.setup import snapshot as SNAP
    if not SNAP.ready():
        say("STAGE making the studio's own copy of the game's levels")
        try:
            info = SNAP.make(game, log=say)
            say("reference: %d files, %.0f MB, checked" % (info["files"], info["bytes"] / 1e6))
        except (IOError, OSError, ValueError) as e:
            return {"ok": False, "error": "the reference copy of the game could not be made, so "
                                          "nothing was written: %s" % e}
    from studio.setup import data as DATA
    if not DATA.ready():
        say("STAGE building the level data")
        try:
            DATA.build(game, log=say)
        except (OSError, RuntimeError) as e:
            return {"ok": False, "error": "the level data could not be built, so nothing was "
                                          "written: %s" % e}
    # the slot this game holds the mission in (the number it had in another copy
    # of the game means nothing here), or a new one
    m = load_in_game(mid, cfg)
    base = int(m["base"]["level"])
    n = m.get("slot")
    if n:
        d = SL.slot_dir(game, n)
        mk = SL.read_marker(game, n) or {}
        if not d.exists():
            say("slot level%d is gone from the game - making it again" % n)
            n = None
        elif mk.get("missionId") != mid:
            return {"ok": False, "error": "slot level%d belongs to another mission" % n}
        elif int(mk.get("base") or base) != base:
            return {"ok": False, "error": "slot level%d was made from level %s, this mission is based on level %d"
                                         % (n, mk.get("base"), base)}
    pl = _player_ref(base) if test else None
    if test and not pl:
        return {"ok": False, "error": "this level has no player start to move"}
    created = not n
    if created:
        n = SL.free_slot(game)
        say("STAGE copying level %d into a new mission slot (level%d)" % (base, n))
        SL.create_slot(game, n, base, m["name"], m.get("description"), mid, log=say)
    else:
        SL.write_definition(game, n, base, m["name"], m.get("description"))
    # A slot made for this Apply goes again if the mission never gets into it:
    # left in, the game would list the bare base level under the mission's name.
    try:
        res = _build_into(m, mid, game, base, n, test, pl, say)
    except BaseException:
        if created:
            try:
                SL.discard_slot(game, n, log=say)
            except Exception as e:
                say("the new slot level%d could not be taken out again: %s" % (n, e))
        raise
    if created and not res.get("ok") and not res.get("installed"):
        SL.discard_slot(game, n, log=say)
        res["discarded"] = n
    return res


def _build_into(m, mid, game, base, n, test, pl, say):
    """The build and install of apply_mission, into slot n."""
    cfg = load_config()
    slot = SL.slot_dir(game, n)
    build = MS.STORE / mid / "build-plan.json"
    plan = {"name": m["name"], "base": m["base"]}
    plan.update(m["plan"])
    applied = None
    if test:
        start = {"ref": pl["ref"], "type": "player", "qtype": pl.get("qtype") or "HumanPlayer", "id": pl.get("id", -1),
                 "name": "Player spawn", "x": round(float(test["x"]), 3), "y": round(float(test["y"]), 3),
                 "z": round(float(test["z"]), 3), "gamma": round(float(test.get("gamma") or 0), 5)}
        plan["edits"] = [e for e in (plan.get("edits") or []) if e.get("ref") != pl["ref"]] + [start]
        applied = {k: plan[k] for k in m["plan"]}
        applied["edits"] = plan["edits"]
        say("a test build: the player starts at %.1f, %.1f" % (start["x"], start["y"]))
    build.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    say("mission \"%s\": level %d %s, %d change(s), into mission slot %d" % (
        m["name"], base, "empty map" if m["base"]["kind"] == "empty" else "as shipped",
        MS.summary(m)["changes"], n))
    stage = paths.work() / "plan"
    say("STAGE building the level script: placing, flattening, routing, objectives")
    gen = subprocess.run(
        [sys.executable, "-m", "studio.build.plan",
         "--plan", str(build), "--out", str(stage), "--game", str(game), "--slot-dir", str(slot)],
        capture_output=True, text=True, cwd=str(ROOT))
    for line in (gen.stdout or "").splitlines():
        say(line)
    if gen.returncode != 0:
        for line in (gen.stderr or "").splitlines():
            say(line)
        return {"ok": False, "error": "plan rejected"}
    say("STAGE compiling and installing into the game")
    try:
        INST.install_level(stage, game, n, log=say)
    except CQ.CompileError as e:
        say(str(e))
        return {"ok": False, "error": "compile failed"}
    # its music (game_music.wav, which the level plays by that name) and its
    # picture in the game's mission list
    st = (m["plan"].get("settings") or {})
    try:
        MU.install(game, n, st.get("music") or None, base, log=say)
    except (OSError, ValueError) as e:
        say("the mission's music was left as it was: %s" % e)
    try:
        pic = MS.STORE / mid / MS.PICTURE
        CV.set_cover(game, n, pic.read_bytes() if pic.exists() else None, log=say)
    except (OSError, ValueError, RuntimeError, protect.ProtectedPath) as e:
        say("the mission's picture in the game's list was left as it was: %s" % e)
    with _surf_lock:
        _surfaces.clear()
    m = MS.mark_installed(mid, n, applied=applied,
                          test={"x": test["x"], "y": test["y"], "at": int(time.time() * 1000)} if test else None)
    # the game folder carries the mission itself: it can be recovered from there
    mk = SL.read_marker(game, n) or {}
    mk.update({"missionId": mid, "base": base, "name": m["name"], "installed": m["installed"], "mission": m})
    SL.write_marker(game, n, mk)
    say("STAGE checking the installed mission")
    ids, problems = INST.verify_level(stage, game, n)
    if problems:
        for x in problems:
            say("PROBLEM: " + x)
        return {"ok": False, "installed": True, "slot": n, "error": problems[0], "mission": MS.summary(m)}
    say("verified: %d HumanAI task(s), all have a script" % len(ids))
    say("done - launch the game and pick \"%s\" (mission %d)" % (m["name"], n))
    launched = launch_game(cfg, say) if test and test.get("launch") else None
    return {"ok": True, "slot": n, "mission": MS.summary(m), "applied": m.get("applied"), "test": bool(test),
            "launched": launched}


def main():
    global TOKEN
    if "--token-stdin" in sys.argv:
        TOKEN = sys.stdin.readline().strip() or None
        if not TOKEN or len(TOKEN) < 32:
            raise SystemExit("--token-stdin: no usable token on stdin")
    cfg = load_config()
    # a key an older version saved in plain text moves to the encrypted store
    if AI.migrate(cfg):
        save_config(cfg)
    st = game_state(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    port = srv.server_address[1]          # the one the system chose when asked for 0
    print("Project IGI Studio")
    print("  serving %s" % EDITOR)
    print("  game    %s   %s" % (cfg["gamePath"] or "(not set up yet)",
                                 "found" if st["ready"] else "NOT FOUND"))
    print("  your folder  %s" % paths.home())
    print("\n  http://localhost:%d%s\n" % (port, "   (its own window only)" if TOKEN else ""))
    # the line the desktop app waits for, before it opens its window
    print("STUDIO_READY port=%d" % port, flush=True)
    if "--no-browser" not in sys.argv and not TOKEN:
        threading.Timer(0.6, lambda: webbrowser.open("http://localhost:%d/plotter.html" % port)).start()
    threading.Thread(target=keep_unlocked, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
