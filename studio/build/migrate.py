# Turn a mission slot built the old way (Apply on top of Apply) into a custom
# mission: its base level plus a plan that rebuilds it.
#
#   python studio/build/migrate.py --slot 15 [--level-json F --graphs-json F]
#                                [--extra-plan F] [--name "Mission 15"] [--dry-run]
#
# The slot's level data (as extracted into editor/data, or an older copy of it)
# is compared with its base level:
#   objects the base does not have      -> placements (exact duplicates once)
#   base objects moved                  -> edits
#   base objects gone                   -> removeRefs
#   navmesh nodes moved / removed / new -> nodeEdits and new nodes, except the
#                                          ones Apply makes itself (inside placed
#                                          buildings, under their floors)
# Patrol stops on nodes Apply added inside a building become "t:<building>:<i>".
import collections, json, math, pathlib, re, sys

from studio.build import navtemplates as NT
from studio.server import missions as MS
from studio.build import slots as SL
from studio import protect
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = paths.data()


def arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def migrate(slot_json, slot_graphs, base_level, extra=None):
    base = json.load((DATA / ("level%d.json" % base_level)).open())
    base_graphs = json.load((DATA / ("graphs%d.json" % base_level)).open())
    sizes = json.load((DATA / "models.json").open())["sizes"]
    tpl = json.load((DATA / "navtemplates.json").open())
    notes = []

    def template_for(model):
        t = tpl["models"].get(model)
        if t is None and model in tpl.get("aliases", {}):
            t = tpl["models"].get(tpl["aliases"][model])
        return t

    base_refs = collections.Counter(o.get("ref") for o in base["objects"] if o.get("ref"))
    seen, added, kept_refs = collections.Counter(), [], collections.Counter()
    for o in slot_json["objects"]:
        r = o.get("ref")
        if not r:
            continue
        seen[r] += 1
        if seen[r] > base_refs.get(r, 0):
            added.append(o)
        else:
            kept_refs[r] += 1

    plan = MS.empty_plan()
    uid_n = [0]

    def uid(prefix):
        uid_n[0] += 1
        return "%s%03d" % (prefix, uid_n[0])

    # objects the slot added - an exact copy of one already taken is a duplicate
    taken = set()
    buildings = []
    for o in added:
        key = o["ref"]
        if o["type"] != "soldier" and key in taken:
            notes.append("dropped a duplicate %s at %.1f, %.1f" % (o.get("name") or o.get("modelName") or o["qtype"], o["x"], o["y"]))
            continue
        taken.add(key)
        if o["qtype"] == "EditRigidObj" or o["type"] in ("building", "prop"):
            p = {"uid": uid("b"), "type": "building", "kind": "object", "model": o["model"],
                 "name": o.get("name") or o.get("modelName") or o["model"],
                 "x": o["x"], "y": o["y"], "z": o["z"], "gamma": o.get("gamma") or 0}
            plan["placements"].append(p)
            buildings.append(p)
        elif o["qtype"] in ("GunPickup", "AmmoPickup"):
            plan["placements"].append({"uid": uid("i"), "type": "pickup", "kind": "pickup", "pickupId": o["model"],
                                       "name": o.get("name") or o["model"], "x": o["x"], "y": o["y"],
                                       "z": o["z"], "gamma": o.get("gamma") or 0, "count": o.get("count")})
        elif o["type"] == "soldier":
            plan["placements"].append({"uid": uid("s"), "type": "soldier", "kind": "soldier", "ai": o.get("ai"),
                                       "model": o.get("model"), "weapon": o.get("weapon"), "name": o.get("name") or "Guard",
                                       "graph": str(o.get("graph")) if o.get("graph") is not None else None,
                                       "x": o["x"], "y": o["y"], "z": o["z"], "gamma": o.get("gamma") or 0,
                                       "_patrol_ids": list(o.get("patrol") or [])})
        else:
            notes.append("could not carry over a %s (%s)" % (o["qtype"], o.get("name")))

    def in_building(b, x, y, z, margin=0.3):
        sz = sizes.get(b["model"]) or {}
        if not sz.get("body"):
            return False
        dz = z - b["z"]
        if not (sz.get("z0", 0) - 0.6 <= dz <= sz.get("z0", 0) + sz.get("h", 0) + 0.6):
            return False
        return NT.inside(sz["body"], *NT.to_model(b, x, y), margin)

    def world_of_template(b, i):
        t = template_for(b["model"])
        n = t["nodes"][i]
        g = b.get("gamma") or 0
        c, s = math.cos(g), math.sin(g)
        return (b["x"] + n[0] * c - n[1] * s, b["y"] + n[0] * s + n[1] * c, b["z"] + n[2])

    # the base's own objects: moved ones become edits, missing ones removals
    by_id = {o["id"]: o for o in slot_json["objects"] if o.get("id", -1) >= 0}
    for o in base["objects"]:
        r = o.get("ref")
        if not r:
            continue
        if kept_refs.get(r, 0) > 0:
            kept_refs[r] -= 1
            same = by_id.get(o.get("id")) if o.get("id", -1) >= 0 else None
            if same and o["type"] == "soldier" and same.get("patrol") != o.get("patrol") and same.get("ref") == r:
                plan["edits"].append({"ref": r, "type": "soldier", "patrol": same.get("patrol") or []})
            continue
        moved = by_id.get(o.get("id")) if o.get("id", -1) >= 0 else None
        if moved and moved.get("qtype") == o.get("qtype"):
            plan["edits"].append({"ref": r, "type": o["type"], "x": moved["x"], "y": moved["y"],
                                  "z": moved["z"], "gamma": moved.get("gamma")})
        else:
            plan["removeRefs"].append(r)

    # navmesh: what the user did by hand, not what Apply does by itself
    new_nodes = {}              # (graph, node id in the slot) -> plan node uid
    for gid, bg in base_graphs.items():
        sg = slot_graphs.get(gid)
        if not sg:
            continue
        bn = {n["id"]: n for n in bg["nodes"]}
        sn = {n["id"]: n for n in sg["nodes"]}

        def auto(n):
            # inside a placed building, or on its doorstep: Apply's own interior nodes
            return any(in_building(b, n["x"], n["y"], n["z"], 2.5 if template_for(b["model"]) else 0.3)
                       for b in buildings)
        for i, n in bn.items():
            if i not in sn:
                if not auto(n):
                    plan["nodeEdits"].append({"graph": gid, "id": i, "action": "remove"})
            elif math.dist((n["x"], n["y"], n["z"]), (sn[i]["x"], sn[i]["y"], sn[i]["z"])) > 0.3 and not auto(sn[i]):
                m = sn[i]
                plan["nodeEdits"].append({"graph": gid, "id": i, "action": "move", "x": m["x"], "y": m["y"], "z": m["z"]})
        for i, n in sn.items():
            if i not in bn and not auto(n):
                u = uid("n")
                plan["nodes"].append({"uid": u, "graph": gid, "x": n["x"], "y": n["y"], "z": n["z"]})
                new_nodes[(gid, i)] = u

    # patrol stops: base nodes stay ids; nodes Apply put in a building are named by the building
    for s in [p for p in plan["placements"] if p["type"] == "soldier"]:
        gid = s.get("graph")
        bn = {n["id"]: n for n in (base_graphs.get(gid) or {}).get("nodes", [])}
        sn = {n["id"]: n for n in (slot_graphs.get(gid) or {}).get("nodes", [])}
        route = []
        for i in s.pop("_patrol_ids"):
            if i in bn:                     # a base node (moved or not) keeps its id
                route.append(i)
                continue
            if (gid, i) in new_nodes:       # a node the user added
                route.append("n:" + new_nodes[(gid, i)])
                continue
            n = sn.get(i)
            ref = None
            if n:
                for b in buildings:
                    t = template_for(b["model"])
                    if not t or not in_building(b, n["x"], n["y"], n["z"], margin=2.5):
                        continue
                    d, k = min((math.dist(world_of_template(b, k), (n["x"], n["y"], n["z"])), k) for k in range(len(t["nodes"])))
                    if d < 0.8:
                        ref = "t:%s:%d" % (b["uid"], k)
                        break
            if ref:
                route.append(ref)
            else:
                notes.append("%s: dropped patrol stop %s (no such node any more)" % (s["name"], i))
        s["patrol"] = route

    for p in (extra or {}).get("placements", []):
        q = dict(p)
        q["uid"] = uid("x")
        plan["placements"].append(q)
        notes.append("added %s from the last plan" % (p.get("name") or p.get("type")))
    return plan, notes


def main(argv):
    n = int(arg(argv, "--slot", 15))
    game = arg(argv, "--game", None) or str(paths.require_game())
    level_json = json.load(open(arg(argv, "--level-json", str(DATA / ("level%d.json" % n)))))
    graphs_json = json.load(open(arg(argv, "--graphs-json", str(DATA / ("graphs%d.json" % n)))))
    base_name = next(iter(sorted(SL.slot_dir(game, n).glob("*.dat")))).stem
    base_level = int(re.sub(r"\D", "", base_name))
    extra = json.load(open(arg(argv, "--extra-plan"))) if arg(argv, "--extra-plan") else None
    plan, notes = migrate(level_json, graphs_json, base_level, extra)
    counts = collections.Counter(p["type"] for p in plan["placements"])
    print("slot level%d is level %d plus: %s; %d edit(s), %d removal(s), %d node edit(s), %d new node(s)" % (
        n, base_level, dict(counts), len(plan["edits"]), len(plan["removeRefs"]), len(plan["nodeEdits"]), len(plan["nodes"])))
    for s in [p for p in plan["placements"] if p["type"] == "soldier"]:
        print("   guard %-28s patrol %s" % (s["name"], s["patrol"]))
    for x in notes:
        print("   - " + x)
    if "--dry-run" in argv:
        return
    m = MS.create(arg(argv, "--name", "Mission %d" % n), base_level, "copy",
                  description="Rebuilt from mission slot %d" % n)
    MS.save(m["id"], plan=plan)
    m = MS.load(m["id"])
    m["slot"] = n
    MS._write(m, snapshot=True)
    marker = SL.read_marker(game, n) or {}
    marker.update({"missionId": m["id"], "base": base_level, "adopted": MS.now()})
    SL.write_marker(game, n, marker)
    print("created custom mission %s (slot %d) - Apply it to rebuild the slot" % (m["id"], n))


if __name__ == "__main__":
    main(sys.argv[1:])
