# How the game's own levels are put together, measured: what an agent reads to learn
# what a good IGI level is like (read_guide, topics levels and level-<n>).
#
# It is made from the level data read out of the person's own game, and kept in their
# folder beside it (paths.home() / "guide"). It is never part of the repository.
import json, math, pathlib, statistics
from studio import paths

LINK = 70.0            # things this close, one by one, are one place
PEOPLE = "soldier"
WHAT = ("building", "door", "camera", "pickup", "vehicle", "terminal", "switch", "explodable")
VERSION = 3


def _load(f):
    with open(f, encoding="utf-8") as h:
        return json.load(h)


def live(objects):
    """What is in the level as it is played: not what only its cutscenes use."""
    return [o for o in objects if not o.get("cutscene")]


def places(objects, link=LINK):
    """The level's places: buildings and guards that stand together, as clusters. A
    thing joins a cluster if it is within link metres of anything in it."""
    pts = [o for o in objects if o.get("type") in ("building", PEOPLE, "camera")]
    seen, out = set(), []
    for i, start in enumerate(pts):
        if i in seen:
            continue
        seen.add(i)
        stack, members = [i], []
        while stack:
            j = stack.pop()
            members.append(pts[j])
            for k, o in enumerate(pts):
                if k not in seen and math.hypot(o["x"] - pts[j]["x"], o["y"] - pts[j]["y"]) <= link:
                    seen.add(k)
                    stack.append(k)
        out.append(members)
    return sorted(out, key=len, reverse=True)


def _summary(members, objects):
    cx = sum(o["x"] for o in members) / len(members)
    cy = sum(o["y"] for o in members) / len(members)
    r = max(math.hypot(o["x"] - cx, o["y"] - cy) for o in members)
    near = [o for o in objects if math.hypot(o["x"] - cx, o["y"] - cy) <= r + 10]
    count = lambda t, among: sum(1 for o in among if o.get("type") == t)
    names = [o["name"] for o in members if o.get("type") == "building" and o.get("name")]
    return {"x": round(cx), "y": round(cy), "radius_m": round(r), "guards": count(PEOPLE, members),
            "buildings": count("building", members), "cameras": count("camera", members),
            "doors": count("door", near), "pickups": count("pickup", near), "vehicles": count("vehicle", near),
            "names": sorted(set(names))[:5]}


def _spread(values):
    """How far they reach, leaving out the few that stand far off from all the rest: a
    level keeps some things well off its map."""
    v = sorted(values)
    if len(v) < 5:
        return v[-1] - v[0] if v else 0
    cut = max(1, len(v) // 50)
    return v[-cut - 1] - v[cut]


def measure(level):
    """The numbers of one level's data."""
    objects = live(level.get("objects") or [])
    people = [o for o in objects if o.get("type") == PEOPLE]
    player = next((o for o in objects if o.get("type") == "player"), None)
    types, weapons = {}, {}
    for o in people:
        types[o.get("ai") or "?"] = types.get(o.get("ai") or "?", 0) + 1
        weapons[o.get("weapon") or "?"] = weapons.get(o.get("weapon") or "?", 0) + 1
    gaps = []
    for i, o in enumerate(people):
        d = [math.hypot(o["x"] - q["x"], o["y"] - q["y"]) for j, q in enumerate(people) if j != i]
        if d:
            gaps.append(min(d))
    ps = [_summary(m, objects) for m in places(objects)]
    big = [p for p in ps if p["guards"] + p["buildings"] >= 3]
    between = []
    for i, p in enumerate(big):
        d = [math.hypot(p["x"] - q["x"], p["y"] - q["y"]) for j, q in enumerate(big) if j != i]
        if d:
            between.append(min(d))
    to_first = None
    if player and people:
        to_first = round(min(math.hypot(o["x"] - player["x"], o["y"] - player["y"]) for o in people))
    sets = level.get("objectiveSets") or []
    objectives = [s.get("text") for st in sets[:1] for s in st.get("slots") or [] if s.get("text")]
    count = lambda t: sum(1 for o in objects if o.get("type") == t)
    return {"size_m": [round(_spread(o["x"] for o in objects)), round(_spread(o["y"] for o in objects))],
            "guards": len(people), "cameras": count("camera"), "buildings": count("building"), "doors": count("door"),
            "pickups": count("pickup"), "vehicles": count("vehicle"), "terminals": count("terminal"), "props": count("prop"),
            "alarm_systems": len(level.get("alarms") or []), "types": types, "weapons": weapons,
            "nearest_guard_m": round(statistics.median(gaps)) if gaps else None, "first_guard_m": to_first,
            "places": big[:14], "between_places_m": round(statistics.median(between)) if between else None,
            "objectives": objectives}


def _names(d, top=6):
    return ", ".join("%s %d" % (k.replace("AITYPE_", "").replace("WEAPON_ID_", "").replace("_", " ").title(), v)
                     for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:top])


def level_page(n, info, m):
    env = info.get("environment") or {}
    L = ["# Level %d: %s" % (n, info.get("name") or ""), "",
         "%s. %s, %s. Measured from the level as your game has it." % (info.get("description") or "", env.get("label") or "", env.get("when") or ""), "",
         "- What it has covers about %d x %d m" % tuple(m["size_m"]),
         "- People: %d guards. Types: %s" % (m["guards"], _names(m["types"]) or "none"),
         "- Weapons: %s" % (_names(m["weapons"]) or "none"),
         "- %d buildings, %d doors, %d cameras in %d alarm system(s), %d pickups, %d vehicles, %d terminals, %d props" % (
             m["buildings"], m["doors"], m["cameras"], m["alarm_systems"], m["pickups"], m["vehicles"], m["terminals"], m["props"]),
         "- From each guard to the next nearest: %s m, as a median" % m["nearest_guard_m"],
         "- From the player's start to the first guard: %s m" % m["first_guard_m"], ""]
    if m["objectives"]:
        L += ["## Objectives", ""] + ["%d. %s" % (i + 1, t) for i, t in enumerate(m["objectives"])] + [""]
    if m["places"]:
        L += ["## Its places", "", "Things that stand together, biggest first. Between one and the next: about %s m." % m["between_places_m"], "",
              "| At (x, y) | Across | Guards | Buildings | Doors | Cameras | Pickups | Named |", "|---|---|---|---|---|---|---|---|"]
        for p in m["places"]:
            L.append("| %d, %d | %d m | %d | %d | %d | %d | %d | %s |" % (p["x"], p["y"], p["radius_m"] * 2, p["guards"], p["buildings"], p["doors"],
                                                                         p["cameras"], p["pickups"], ", ".join(p["names"]) or ""))
        L += ["", "To see one: open_mission with level %d, then screenshot_map or screenshot_3d at its x and y. To use it: select_things there, copy, paste_copied in your mission." % n]
    return "\n".join(L) + "\n"


def _range(values):
    v = sorted(x for x in values if x is not None)
    if not v:
        return "none"
    return "%d to %d, usually %d" % (v[0], v[-1], statistics.median(v))


def overview_page(rows):
    ps = [p for _, _, m in rows for p in m["places"]]
    small = [p for p in ps if p["guards"] > 0]
    L = ["# How the game's own levels are built", "",
         "Measured from the 14 levels as your game has them. Use these as a sense of scale: a mission far outside them will feel unlike the game.", "",
         "## A whole level", "",
         "- Guards: %s" % _range(m["guards"] for _, _, m in rows),
         "- Buildings: %s" % _range(m["buildings"] for _, _, m in rows),
         "- Security cameras: %s" % _range(m["cameras"] for _, _, m in rows),
         "- Alarm systems: %s" % _range(m["alarm_systems"] for _, _, m in rows),
         "- Pickups: %s" % _range(m["pickups"] for _, _, m in rows),
         "- Objectives: %s" % _range(len(m["objectives"]) for _, _, m in rows),
         "- Separate places in a level: %s" % _range(len(m["places"]) for _, _, m in rows),
         "- What it has covers, the longer way: %s m" % _range(max(m["size_m"]) for _, _, m in rows),
         "- From the player's start to the first guard: %s m" % _range(m["first_guard_m"] for _, _, m in rows), "",
         "## One place in a level", "",
         "- Guards: %s" % _range(p["guards"] for p in small),
         "- Buildings: %s" % _range(p["buildings"] for p in ps),
         "- Across: %s m" % _range(p["radius_m"] * 2 for p in ps),
         "- From one place to the next: %s m" % _range(m["between_places_m"] for _, _, m in rows),
         "- From one guard to the nearest other: %s m" % _range(m["nearest_guard_m"] for _, _, m in rows), "",
         "## The levels", "",
         "| Level | Name | Land | Covers (m) | Guards | Buildings | Cameras | Places |", "|---|---|---|---|---|---|---|---|"]
    for n, info, m in rows:
        env = info.get("environment") or {}
        L.append("| %d | %s | %s, %s | %d x %d | %d | %d | %d | %d |" % (n, info.get("name") or "", env.get("label") or "", env.get("when") or "",
                                                                        m["size_m"][0], m["size_m"][1], m["guards"], m["buildings"], m["cameras"], len(m["places"])))
    L += ["", "read_guide with topic level-3, for example, says what one level has, place by place."]
    return "\n".join(L) + "\n"


def folder():
    return paths.home() / "guide"


def build(data=None, out=None):
    """Writes the pages. Returns how many levels it read."""
    data = pathlib.Path(data or paths.data())
    out = pathlib.Path(out or folder())
    try:
        infos = {m["level"]: m for m in _load(data / "builtins.json").get("missions") or []}
    except (OSError, ValueError):
        infos = {}
    rows = []
    for n in range(1, 15):
        f = data / ("level%d.json" % n)
        if not f.exists():
            continue
        try:
            rows.append((n, infos.get(n) or {}, measure(_load(f))))
        except (OSError, ValueError, KeyError, TypeError) as e:
            print("level %d could not be measured: %s" % (n, e))
    if not rows:
        return 0
    out.mkdir(parents=True, exist_ok=True)
    for n, info, m in rows:
        (out / ("level-%d.md" % n)).write_text(level_page(n, info, m), encoding="utf-8")
    (out / "levels.md").write_text(overview_page(rows), encoding="utf-8")
    (out / ".version").write_text(str(VERSION), encoding="utf-8")
    return len(rows)


def ensure():
    """The pages, made if they are missing or older than the level data."""
    out = folder()
    page = out / "levels.md"
    try:
        marks = paths.data() / "builtins.json"
        fresh = page.exists() and (out / ".version").read_text(encoding="utf-8").strip() == str(VERSION) \
            and (not marks.exists() or page.stat().st_mtime >= marks.stat().st_mtime)
    except OSError:
        fresh = False
    if not fresh:
        build()


if __name__ == "__main__":
    print("%d levels measured" % build())
