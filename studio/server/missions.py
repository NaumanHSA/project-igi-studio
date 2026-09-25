# Custom missions: a base (a built-in level as shipped, or its empty map) plus a
# plan of changes. Stored in missions/custom/<id>/:
#
#   mission.json   name, description, base, slot, plan, installed, applied (the
#                  plan as the game has it, from the last Apply)
#   cover.png      a picture of the map, saved by the editor
#   history/       earlier versions (the last 30 saves, and every Apply)
#
# Deleting moves the folder to missions/custom/.trash/, from where it can be
# restored. Built-in missions are never stored here - they are read-only.
import hashlib, json, math, pathlib, re, shutil, time, uuid
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
STORE = paths.missions() / "custom"
TRASH = STORE / ".trash"
PLAN_KEYS = ("placements", "nodes", "nodeEdits", "edits", "removeRefs", "removals", "objectives",
              "ground", "brush", "sculpt", "events", "paint", "textures")
LAYERS = ("brush", "sculpt")    # cells, not changes: a layer counts once
KEEP_HISTORY = 30
HISTORY_EVERY = 120          # seconds: saves closer together than this share a snapshot


def now():
    return int(time.time() * 1000)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "mission").lower()).strip("-")[:32] or "mission"


def _dir(mid):
    if not re.fullmatch(r"[a-z0-9-]{1,64}", mid or ""):
        raise ValueError("bad mission id %r" % mid)
    return STORE / mid


def empty_plan():
    return {k: [] for k in PLAN_KEYS}


def plan_hash(m):
    body = json.dumps({"base": m["base"], "plan": m["plan"], "name": m["name"],
                       "description": m.get("description", "")}, sort_keys=True)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]


def summary(m):
    p = m.get("plan") or {}
    inst = m.get("installed")
    return {"id": m["id"], "name": m["name"], "description": m.get("description", ""),
            "base": m["base"], "slot": m.get("slot"), "created": m.get("created"), "updated": m.get("updated"),
            "changes": sum((1 if p.get(k) else 0) if k in LAYERS else len(p.get(k) or []) for k in PLAN_KEYS),
            "guards": sum(1 for x in p.get("placements") or [] if x.get("type") == "soldier"),
            "cover": (_dir(m["id"]) / "cover.png").exists(),
            # a picture of the mission's own: the library's card and the game's list
            "picture": (_dir(m["id"]) / PICTURE).exists(),
            "installed": inst, "upToDate": bool(inst and inst.get("hash") == plan_hash(m))}


def list_missions(view=None):
    """Every mission, summed up. view(mission) may show each as something else
    first: as the connected game has it, say."""
    out = []
    if STORE.is_dir():
        for d in STORE.iterdir():
            f = d / "mission.json"
            if d.name.startswith(".") or not f.exists():
                continue
            try:
                m = json.load(f.open(encoding="utf-8"))
                out.append(summary(view(m) if view else m))
            except (OSError, ValueError, KeyError):
                continue
    return sorted(out, key=lambda r: -(r.get("updated") or 0))


def _lying(item):
    """A pickup of the mission's own that lies on its side, heading in alpha - as
    apply_plan.pickup_pose: not ammo, a grenade or a mine."""
    return bool(item) and not item.startswith("AMMO_ID_") and item not in ("WEAPON_ID_GRENADE", "WEAPON_ID_PROXIMITYMINE")


_LEVEL_OBJS = {}


def _level_objects(level):
    if level not in _LEVEL_OBJS:
        try:
            meta = json.load((paths.data() / ("level%d.json" % int(level))).open(encoding="utf-8"))
            _LEVEL_OBJS[level] = {o["ref"]: o for o in meta.get("objects", []) if o.get("ref")}
        except (OSError, ValueError, TypeError):
            _LEVEL_OBJS[level] = {}
    return _LEVEL_OBJS[level]


def ccw_lying(plan, level):
    """Plans before 2026-09-18 kept a lying weapon's alpha as its heading, which
    turns the other way from every other heading (the map's "anticlockwise"
    turned a rifle clockwise). Converted once, so every pose stays as the game
    has it; plan["ccwLying"] marks a converted plan. True when it changed."""
    if not isinstance(plan, dict) or plan.get("ccwLying"):
        return False
    tau = 2 * math.pi
    for p in plan.get("placements") or []:
        if p.get("type") == "pickup" and p.get("gamma") and _lying(p.get("pickupId") or p.get("model") or ""):
            p["gamma"] = round((-float(p["gamma"])) % tau, 5)
    for e in plan.get("edits") or []:
        if e.get("type") != "pickup" or e.get("gamma") is None:
            continue
        o = _level_objects(level).get(e.get("ref")) or {}
        a = o.get("orient")
        if a and len(a) == 3 and abs(float(a[1]) - 1.5708) < 0.05:
            g0 = float(o.get("gamma") or 0)
            e["gamma"] = round((2 * g0 - float(e["gamma"])) % tau, 5)
    plan["ccwLying"] = True
    return True


def load(mid):
    m = json.load((_dir(mid) / "mission.json").open(encoding="utf-8"))
    # applied before the snapshot was kept, and unchanged since: its plan is what the game has
    if "applied" not in m and m.get("installed") and m["installed"].get("hash") == plan_hash(m):
        m["applied"] = json.loads(json.dumps(m["plan"]))
    if isinstance(m.get("plan"), dict) and not m["plan"].get("ccwLying"):
        was = plan_hash(m)
        lv = (m.get("base") or {}).get("level")
        ccw_lying(m["plan"], lv)
        if isinstance(m.get("applied"), dict):
            ccw_lying(m["applied"], lv)
        # the game has the same poses as before: still up to date if it was
        if m.get("installed") and m["installed"].get("hash") == was:
            m["installed"]["hash"] = plan_hash(m)
        _write(m)
    return m


def _write(m, snapshot=False):
    d = _dir(m["id"])
    d.mkdir(parents=True, exist_ok=True)
    f = d / "mission.json"
    text = json.dumps(m, indent=1)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(f)
    h = d / "history"
    h.mkdir(exist_ok=True)
    snaps = sorted(h.glob("*.json"))
    last = int(snaps[-1].stem.split("-")[0]) if snaps else 0
    if snapshot or m["updated"] - last >= HISTORY_EVERY * 1000:
        (h / ("%d%s.json" % (m["updated"], "-apply" if snapshot else ""))).write_text(text, encoding="utf-8")
        plain = [s for s in sorted(h.glob("*.json")) if not s.stem.endswith("-apply")]
        for old in plain[:-KEEP_HISTORY]:
            old.unlink()
    return m


PICTURE = "picture.png"         # the mission's own picture, 336 x 248 (the game takes 168 x 124)


def _picture_print(m):
    """The fingerprint of the mission's own picture, from the file itself: a plan
    saved by an editor that had not heard of it keeps it all the same."""
    f = _dir(m["id"]) / PICTURE
    st = m["plan"].setdefault("settings", {})
    if f.exists():
        st["picture"] = hashlib.sha1(f.read_bytes()).hexdigest()[:12]
    else:
        st.pop("picture", None)


def set_picture(mid, png):
    """The mission's own picture (PNG bytes), or none (None). Its fingerprint goes
    in the plan's settings, so a mission whose picture changed has something to
    apply. Returns the mission."""
    m = load(mid)
    f = _dir(mid) / PICTURE
    if png:
        if png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) > 4_000_000:
            raise ValueError("the picture must be a PNG of up to 4 MB")
        f.write_bytes(png)
    elif f.exists():
        f.unlink()
    _picture_print(m)
    m["updated"] = now()
    _write(m)
    return m


def create(name, base_level, kind="copy", description="", copy_from=None):
    base_level = int(base_level)
    if not 1 <= base_level <= 14:
        raise ValueError("a mission is based on a built-in level (1-14)")
    if kind not in ("copy", "empty"):
        raise ValueError("kind must be copy or empty")
    plan = empty_plan()
    if copy_from:
        src = load(copy_from)
        base_level, kind = src["base"]["level"], src["base"]["kind"]
        plan = json.loads(json.dumps(src["plan"]))
        description = description or src.get("description", "")
    mid = "%s-%s" % (_slug(name), uuid.uuid4().hex[:6])
    t = now()
    m = {"id": mid, "name": (name or "Untitled mission").strip()[:60], "description": (description or "")[:200],
         "base": {"level": base_level, "kind": kind}, "slot": None, "created": t, "updated": t,
         "plan": plan, "installed": None}
    _write(m, snapshot=True)
    if copy_from and (_dir(copy_from) / "cover.png").exists():
        shutil.copyfile(_dir(copy_from) / "cover.png", _dir(mid) / "cover.png")
    if copy_from and (_dir(copy_from) / PICTURE).exists():
        shutil.copyfile(_dir(copy_from) / PICTURE, _dir(mid) / PICTURE)
    return m


def write_recovered(mission):
    """Put a mission the game was holding back into the studio's own folder.

    Every Apply writes the whole mission into its slot's marker in the game,
    so a studio folder that was lost can be filled again from there. An id
    that is already here is never overwritten: the copy here is the newer one
    by definition, because the game only ever gets what was applied.
    """
    if not isinstance(mission, dict) or not mission.get("id") or not mission.get("plan"):
        raise ValueError("that slot does not carry a whole mission")
    mid = str(mission["id"])
    if (_dir(mid) / "mission.json").exists():
        raise FileExistsError("there is already a mission called %s here" % mid)
    m = dict(mission)
    m["recovered"] = now()
    m.setdefault("created", m["recovered"])
    m["updated"] = m.get("updated") or m["recovered"]
    _write(m, snapshot=True)
    return m


def save(mid, plan=None, name=None, description=None, cover_png=None, applied=None):
    m = load(mid)
    if plan is not None:
        m["plan"] = {k: plan.get(k) or [] for k in PLAN_KEYS}
        m["plan"]["failOnAlarm"] = bool(plan.get("failOnAlarm"))
        # whether the plan has already taken over the level's own objectives
        m["plan"]["objBase"] = bool(plan.get("objBase"))
        # a lying weapon's heading turns like every other (see ccw_lying); a plan
        # from an editor opened before that keeps the old way, and is converted
        m["plan"]["ccwLying"] = bool(plan.get("ccwLying"))
        # a time limit, rain or snow, haze (apply_plan.py _settings), its music (music.py)
        m["plan"]["settings"] = plan.get("settings") if isinstance(plan.get("settings"), dict) else {}
        _picture_print(m)
    # the editor took over heights the game already has (its height sync): the
    # record of what is in the game takes them too; when that is the whole plan,
    # the game is still up to date with it
    if isinstance(applied, dict) and m.get("installed") and isinstance(m.get("applied"), dict):
        m["applied"] = applied
        if not m["installed"].get("test") and \
                json.dumps(applied, sort_keys=True) == json.dumps(m["plan"], sort_keys=True):
            m["installed"]["hash"] = plan_hash(m)
        if not m["plan"]["ccwLying"]:
            ccw_lying(m["plan"], (m.get("base") or {}).get("level"))
    if name is not None:
        m["name"] = name.strip()[:60] or m["name"]
    if description is not None:
        m["description"] = description[:200]
    m["updated"] = now()
    _write(m)
    if cover_png:
        (_dir(mid) / "cover.png").write_bytes(cover_png)
    return m


# ---------------------------------------------------------------- runs
# A play-through recorded by the live view: missions/custom/<id>/runs/<start>.json
# {"id", "started", "pts": [[seconds, x, y, z], ...]}. Saved again as it grows.
def _runs(mid):
    return _dir(mid) / "runs"


def save_run(mid, run):
    rid = str(int(run.get("started") or now()))
    if not re.fullmatch(r"\d{10,16}", rid):
        raise ValueError("bad run id")
    pts = [[round(float(p[0]), 2), round(float(p[1]), 2), round(float(p[2]), 2), round(float(p[3]), 2)]
           for p in (run.get("pts") or []) if isinstance(p, list) and len(p) >= 4][:20000]
    d = _runs(mid)
    d.mkdir(parents=True, exist_ok=True)
    (d / (rid + ".json")).write_text(json.dumps({"id": rid, "started": int(rid), "pts": pts}), encoding="utf-8")
    return {"id": rid, "n": len(pts)}


def list_runs(mid):
    out = []
    d = _runs(mid)
    if d.is_dir():
        for f in d.glob("*.json"):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            pts = r.get("pts") or []
            dist = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(pts, pts[1:]))
            out.append({"id": r.get("id"), "started": r.get("started"), "secs": pts[-1][0] if pts else 0,
                        "n": len(pts), "dist": round(dist, 1)})
    return sorted(out, key=lambda r: -(r.get("started") or 0))


def load_run(mid, rid):
    if not re.fullmatch(r"\d{10,16}", rid or ""):
        raise ValueError("bad run id")
    return json.loads((_runs(mid) / (rid + ".json")).read_text(encoding="utf-8"))


def delete_run(mid, rid):
    if not re.fullmatch(r"\d{10,16}", rid or ""):
        raise ValueError("bad run id")
    f = _runs(mid) / (rid + ".json")
    if f.exists():
        f.unlink()


def mark_installed(mid, slot, applied=None, test=None):
    """applied: the plan the game was built from, when it is not the saved one (a
    test build starts the player somewhere else); test: what that was."""
    m = load(mid)
    m["slot"] = slot
    m["installed"] = {"slot": slot, "hash": plan_hash(m), "at": now()}
    if test:
        m["installed"]["test"] = test
        m["installed"]["hash"] = "test"          # never up to date: the start differs
    # what the game now has: the editor shows what differs from it as changes
    m["applied"] = json.loads(json.dumps(applied if applied is not None else m["plan"]))
    return _write(m, snapshot=True)


def mark_uninstalled(mid):
    m = load(mid)
    m["slot"], m["installed"], m["applied"] = None, None, None
    return _write(m)


def delete(mid):
    d = _dir(mid)
    TRASH.mkdir(parents=True, exist_ok=True)
    dest = TRASH / ("%s--%d" % (mid, now()))
    d.rename(dest)
    return dest.name


def list_trash():
    out = []
    if TRASH.is_dir():
        for d in TRASH.iterdir():
            f = d / "mission.json"
            if f.exists():
                try:
                    m = json.load(f.open(encoding="utf-8"))
                    out.append(dict(summary_trash(m, d.name)))
                except (OSError, ValueError):
                    pass
    return sorted(out, key=lambda r: -r["deleted"])


def summary_trash(m, tid):
    return {"trashId": tid, "id": m["id"], "name": m["name"], "base": m["base"],
            "deleted": int(tid.rsplit("--", 1)[-1]) if "--" in tid else 0}


def purge(tid):
    """Take one mission out of the trash for good. Only the studio's own copy:
    a slot it once had in the game is the game's, and was dealt with when the
    mission was deleted."""
    if not re.fullmatch(r"[a-z0-9-]+--\d+", tid or ""):
        raise ValueError("bad trash id")
    d = TRASH / tid
    if not d.is_dir():
        raise FileNotFoundError(tid)
    shutil.rmtree(d)
    return True


def purge_all():
    """Empty the trash. Returns how many missions went."""
    n = 0
    if TRASH.is_dir():
        for d in sorted(TRASH.iterdir()):
            if d.is_dir() and "--" in d.name:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
    return n


def restore(tid):
    if not re.fullmatch(r"[a-z0-9-]+--\d+", tid or ""):
        raise ValueError("bad trash id")
    src = TRASH / tid
    mid = tid.rsplit("--", 1)[0]
    if (_dir(mid)).exists():
        mid = "%s-%s" % (mid.rsplit("-", 1)[0], uuid.uuid4().hex[:6])
    src.rename(_dir(mid))
    m = load(mid)
    m["id"], m["slot"], m["installed"], m["updated"] = mid, None, None, now()
    m["applied"] = None
    _write(m)
    return m
