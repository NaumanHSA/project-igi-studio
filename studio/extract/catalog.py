# Builds the editor's inventory from every shipped level:
#   structures  every building and prop model, with a readable name, size,
#               the levels using it and a category (fences & walls, security...)
#   weapons     every weapon/item and ammo type found as a pickup or on a guard
#   enemies     every AI type, with the models and weapons it is seen with
#
#   python studio/extract/catalog.py        (after extract_levels.py and extract_models.py)
#
# Structure names, best first: the map computer's own label for a building using
# that model, the level designer's task name ("SmallGarage" -> "Small Garage"),
# then the model's name from IGIModels.txt ("WOODEN_CRATE" -> "Wooden Crate").
import collections, json, pathlib, re, statistics
from studio import paths
# This module is a script: it does its work as it is read, the way it always
# has. Run it (python -m studio.extract.catalog), do not import it. The guard below
# turns an accidental import into a clear error instead of a surprise.
if __name__ != "__main__":
    raise ImportError("studio.extract.catalog is a script: run it, do not import it")

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = paths.data()

models = json.load((DATA / "models.json").open())
sizes, labels = models["sizes"], models.get("labels", {})


def pretty(s):
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s or "")
    s = re.sub(r"[_\s]+", " ", s).strip()
    s = re.sub(r"\s*\d+$", "", s)                     # "WALLS3" -> "WALLS"
    return s.title() if s.isupper() or s.islower() else s


# first match wins, so the specific rules come before the broad ones
CATEGORIES = [
    ("underground", "Underground & tunnels", r"UNDERGROUND|TUNNEL|ELEVATOR|\bLIFT|STRAIGHT|\bTURN\b|JUNCTION|FAN ROOM|WINCH|METAL DOOR BASE"),
    ("doors",       "Doors & hatches",       r"DOOR|HATCH"),
    ("security",    "Security & military",   r"GUN ?POST|SANDBAGS? POST|MACHINE GUN"),
    ("fences",      "Fences, walls & gates", r"FENCE|WALL|GATE|DIVIDER|SANDBAG|BARRIER|FILLER ?PLATE"),
    ("vehicles",    "Vehicles & helipads",   r"HELI|TRAIN|WAGON|CABLE CAR|APC|T80|TRUCK|JEEP|FORKLIFT|PLANE|\bMIG|BOAT|\bCAR\b|PULLEY|LIMO|VEHICLE|WHEEL"),
    ("roads",       "Roads, bridges & walkways", r"ROAD|BRIDGE|WALKWAY|OVERPASS|RAMP|RAIL|TRACK|STAIRS|LADDER"),
    ("towers",      "Towers, masts & radar", r"TOWER|MAST|PYLON|ANTEN|RADAR|DOME"),
    ("security",    "Security & military",   r"SECURITY|BARRACK|GUARD|CHECKPOINT|BUNKER|AMMUNITION|AMMO BUILDING|ARMOU?RED|\bHQ|MILITARY|SNIPER|GUNNER|NUCLEAR|SECURE"),
    ("military",    "Military equipment",    r"MISSILE|\bSAM\b|SHELL|MINEFIELD|TARGET|GUN STAND|LASER|LAUNCHER|TERMINATOR"),
    ("industrial",  "Industrial & storage",  r"WAREHOUSE|GARAGE|FUEL|CONTAINER|POWER|GENERATOR|FACTORY|LOADING|SHELTER|HANG[AE]R|DEPOT|STORAGE|SILO|PUMP|COMM|RADIO|COOLING|PLATFORM"),
    ("crates",      "Crates, barrels & boxes", r"CRATE|BARREL|\bBOX|CASE|PALLET|SACK|DRUM|OILSKIN|COLBOX"),
    ("furniture",   "Furniture & electronics", r"DESK|CHAIR|BED|LOCKER|CABINET|TABLE|SHELF|SOFA|COMPUTER|MAINFRAME|PHONE|MONITOR|FUSEBOX|\bTV|CONSOLE|BOARD|SWITCH|FILING|DEVICE|DECOR|\bFAN\b|VENDING|SODA|MACHINE|KEYBOARD|TOILET|SINK|C4|BOMB|RACK"),
    ("signs",       "Signs, fixtures & clutter", r"SIGN|SPEAKER|HOLDER|JOINT|SCAFFOLD|PLANK|TRASH|SHOWER"),
    ("lights",      "Lights, poles & wires", r"LIGHT|POLE|LAMP|WIRE|CABLE"),
    ("nature",      "Trees, rocks & nature",  r"TREE|BUSH|ROCK|STONE|PLANT|GRASS|\bLOG"),
    ("houses",      "Houses & civilian",     r"HOUSE|HUT|CANTINA|OFFICE|STOREY|VILLAGE|RUIN|FORTRESS|CHURCH|CROSS|SHACK|ROOM|BUILDING"),
]


def categorise(*texts):
    t = " ".join(x for x in texts if x).upper().replace("_", " ")
    for key, title, pat in CATEGORIES:
        if re.search(pat, t):
            return key, title
    return "other", "Other"


GENERIC = re.compile(r"^(|object|building|static|for location.*|\d+)$", re.I)
seen = collections.defaultdict(lambda: {"levels": set(), "names": collections.Counter(),
                                        "raw": set(), "count": 0, "kinds": collections.Counter()})
weapons = collections.defaultdict(lambda: {"levels": set(), "as": set(), "counts": []})
enemies = collections.defaultdict(lambda: {"levels": set(), "models": collections.Counter(),
                                           "weapons": collections.Counter(), "count": 0})

for lv in range(1, 15):
    p = DATA / ("level%d.json" % lv)
    if not p.exists():
        continue
    level = json.load(p.open())
    lab = labels.get(str(lv), {})
    for o in level["objects"]:
        kind = o["type"]
        if kind == "soldier" and o.get("ai") and not o.get("cutscene"):
            e = enemies[o["ai"]]
            e["levels"].add(lv); e["count"] += 1
            if o.get("model"):
                e["models"][o["model"]] += 1
            if o.get("weapon"):
                e["weapons"][o["weapon"]] += 1
                w = weapons[o["weapon"]]; w["levels"].add(lv); w["as"].add("guard")
            continue
        if kind == "pickup" and o.get("model"):
            w = weapons[o["model"]]; w["levels"].add(lv); w["as"].add("pickup")
            if o.get("count"):
                w["counts"].append(o["count"])
            continue
        if kind not in ("building", "prop") or not o.get("model"):
            continue
        if re.match(r"COLBOX", o.get("modelName") or "", re.I):
            continue                            # invisible collision helpers
        rec = seen[o["model"]]
        rec["levels"].add(lv)
        rec["count"] += 1
        rec["kinds"][kind] += 1
        rec["raw"].add(o.get("modelName") or o["model"])
        title = lab.get(str(o.get("id")), {}).get("title")
        if title:
            rec["names"][title] += 100          # the game's own wording wins
        elif kind == "building" and o.get("name") and not GENERIC.match(o["name"]):
            rec["names"][pretty(o["name"])] += 1


def structures():
    out = []
    for model, rec in seen.items():
        raw = sorted(rec["raw"])[0]
        name = rec["names"].most_common(1)[0][0] if rec["names"] else pretty(raw)
        s = sizes.get(model, {})
        kind = rec["kinds"].most_common(1)[0][0]
        cat, _ = categorise(name, raw)
        out.append({"model": model, "name": name, "raw": raw, "kind": kind, "cat": cat,
                    "levels": sorted(rec["levels"]), "count": rec["count"],
                    "w": s.get("w"), "d": s.get("d"), "h": s.get("h")})
    by = collections.defaultdict(list)
    for r in out:
        by[r["name"]].append(r)
    for name, group in by.items():
        if len(group) > 1:
            for r in group:
                tag = pretty(r["raw"])
                r["name"] = "%s (%s)" % (name, tag) if tag.lower() != name.lower() else "%s %s" % (name, r["model"])
    names = collections.Counter(r["name"] for r in out)
    for r in out:
        if names[r["name"]] > 1:
            r["name"] = "%s %s" % (r["name"], r["model"])
    return sorted(out, key=lambda r: r["name"].lower())


WEAPON_NAMES = {
    "AK47": "AK-47", "M16A2": "M16A2", "SPAS12": "SPAS-12", "UZI": "Uzi", "UZIX2": "Dual Uzi",
    "MP5SD": "MP5SD", "DRAGUNOV": "Dragunov", "MINIMI": "Minimi", "JACKHAMMER": "Jackhammer",
    "DESERTEAGLE": "Desert Eagle", "COLT": "Colt", "GLOCK": "Glock", "RPG18": "RPG-18",
    "GRENADE": "Grenade", "FLASHBANG": "Flashbang", "PROXIMITYMINE": "Proximity mine",
    "MEDIPACK": "Medipack", "KNIFE": "Knife", "BINOCULARS": "Binoculars",
    "919": "9mm rounds", "556": "5.56mm rounds", "762": "7.62mm rounds", "12": "12 gauge shells",
    "44": ".44 rounds", "357": ".357 rounds", "127": "12.7mm rounds", "M203": "M203 grenades",
}
# weapons the game defines that no mission places or arms a guard with
KNOWN = ["WEAPON_ID_KNIFE", "WEAPON_ID_BINOCULARS", "WEAPON_ID_MP5SD", "WEAPON_ID_GLOCK",
         "AMMO_ID_762", "AMMO_ID_DRAGUNOV", "AMMO_ID_127", "AMMO_ID_FLASHBANG"]
DEFAULT_AMMO = {"AMMO_ID_919": 32, "AMMO_ID_556": 60, "AMMO_ID_762": 20, "AMMO_ID_DRAGUNOV": 20,
                "AMMO_ID_12": 16, "AMMO_ID_44": 14, "AMMO_ID_357": 12, "AMMO_ID_127": 100,
                "AMMO_ID_M203": 4, "AMMO_ID_GRENADE": 2, "AMMO_ID_FLASHBANG": 2,
                "AMMO_ID_PROXIMITYMINE": 2, "AMMO_ID_MEDIPACK": 1}


def weapon_rows():
    for k in KNOWN:
        weapons[k]
    out = []
    for wid, rec in weapons.items():
        if not re.fullmatch(r"(WEAPON|AMMO)_ID_[A-Z0-9_]+", wid):
            continue
        short = wid.split("_ID_", 1)[1]
        ammo = wid.startswith("AMMO_")
        label = WEAPON_NAMES.get(short, pretty(short))
        if ammo and short in ("MEDIPACK", "GRENADE", "FLASHBANG", "PROXIMITYMINE", "DRAGUNOV"):
            label = label + " ammo" if short == "DRAGUNOV" else label + " (refill)"
        group = ("ammo" if ammo else
                 "items" if short in ("MEDIPACK", "BINOCULARS") else
                 "explosives" if short in ("GRENADE", "FLASHBANG", "PROXIMITYMINE", "RPG18") else
                 "weapons")
        cnt = int(statistics.median(rec["counts"])) if rec["counts"] else DEFAULT_AMMO.get(wid)
        out.append({"id": wid, "label": label, "group": group, "levels": sorted(rec["levels"]),
                    "as": sorted(rec["as"]), "count": cnt})
    order = {"weapons": 0, "explosives": 1, "items": 2, "ammo": 3}
    return sorted(out, key=lambda r: (order[r["group"]], r["label"].lower()))


def enemy_rows():
    out = []
    for ai, rec in enemies.items():
        parts = ai.replace("AITYPE_", "").split("_")
        weapon = parts[-1] if parts[-1] in ("AK", "SPAS", "UZI", "PISTOL") else None
        role = " ".join(parts[:-1] if weapon else parts).title()
        role = {"Rpg": "RPG trooper"}.get(role, role)
        label = role + (" (%s)" % {"AK": "AK", "SPAS": "SPAS", "UZI": "Uzi", "PISTOL": "pistol"}[weapon] if weapon else "")
        special = ai in ("AITYPE_CIVILIAN", "AITYPE_EKK", "AITYPE_ANYA", "AITYPE_PRIBOI")
        out.append({"id": ai, "label": label, "special": special, "levels": sorted(rec["levels"]),
                    "count": rec["count"],
                    "models": [m for m, _ in rec["models"].most_common()],
                    "weapons": [w for w, _ in rec["weapons"].most_common()]})
    return sorted(out, key=lambda r: (r["special"], -r["count"]))


cat = {"structures": structures(), "weapons": weapon_rows(), "enemies": enemy_rows(),
       "categories": [{"key": k, "title": t} for k, t in dict((k, t) for k, t, _ in CATEGORIES).items()]
                     + [{"key": "other", "title": "Other"}]}
json.dump(cat, (DATA / "catalog.json").open("w"), separators=(",", ":"))
counts = collections.Counter(r["cat"] for r in cat["structures"])
print("catalog: %d structures, %d weapons/items, %d enemy types -> %s"
      % (len(cat["structures"]), len(cat["weapons"]), len(cat["enemies"]), DATA / "catalog.json"))
for c in cat["categories"]:
    print("   %-12s %3d" % (c["key"], counts.get(c["key"], 0)))
