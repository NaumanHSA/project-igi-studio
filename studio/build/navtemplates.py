# Interior navmesh of every building the game ships with one.
#
# Building floors are not in a building's collision mesh. The engine stands a
# soldier on the navmesh, so a building with no nodes inside leaves its guards
# standing in the foundation, feet under the floor. The same missing nodes are
# why a guard walks through its walls: the links that pass under it lead
# straight through.
#
# For each building model, the shipped instance with the richest interior
# donates it, in model space:
#   nodes   position, facing, radius, material, criteria (STAIR/DOOR)
#   edges   the links between them, with the engine's own link weights
#   porch   nodes just outside a doorway that join the inside to the yard
#   exits   the nodes a placed copy is linked to the outdoor graph through
#   floors  the heights people stand at inside (ground, first floor, ...)
#
#   python studio/build/navtemplates.py [--game <the pristine install>]
#       -> editor/data/navtemplates.json
import collections, json, math, pathlib, sys

from studio.build import graphs as GE
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = paths.data()
SCALE = 4096.0
MARGIN = 0.3        # metres around the footprint that still count as inside
PORCH = 2.5         # a doorway's outside node lies within this of the walls
FLOOR_GAP = 0.6     # node heights closer than this are the same floor


def inside(body, mx, my, margin):
    return any(r[0] - margin <= mx <= r[0] + r[2] + margin and
               r[1] - margin <= my <= r[1] + r[3] + margin for r in body)


def to_model(o, x, y):
    c, s = math.cos(o["gamma"]), math.sin(o["gamma"])
    dx, dy = x - o["x"], y - o["y"]
    return dx * c + dy * s, -dx * s + dy * c


def floors_of(heights):
    """Cluster node heights into floors: [[dz, count], ...] lowest first.

    A floor's height is the one most of its nodes share, so a doorstep node or
    two next to it does not drag it down."""
    groups = []
    for z in sorted(heights):
        if groups and z - groups[-1][-1] <= FLOOR_GAP:
            groups[-1].append(z)
        else:
            groups.append([z])
    out = []
    for g in groups:
        common = collections.Counter(round(z * 20) for z in g).most_common(1)[0][0]
        at = [z for z in g if round(z * 20) == common]
        out.append([round(sum(at) / len(at), 2), len(g)])
    return out


def level_graphs(game, lv):
    """{gid: (Graph, origin)} for the level's parseable graphs."""
    meta = json.load((DATA / ("graphs%d.json" % lv)).open())
    out = {}
    for gid, g in meta.items():
        p = game / "missions" / "location0" / ("level%d" % lv) / "graphs" / ("graph%s.dat" % gid)
        if not p.exists() or not g.get("origin"):
            continue
        try:
            out[gid] = (GE.Graph(str(p)), g["origin"])
        except GE.GraphError:
            pass
    return out


def interior(o, size, graph, origin):
    """The part of a graph inside one building instance, or None."""
    body = size.get("body") or []
    z0, h = size.get("z0", 0.0), size.get("h", 0.0)
    reach = math.hypot(size["w"], size["d"]) / 2 + math.hypot(size.get("cx", 0), size.get("cy", 0)) + PORCH
    world = {}
    for n in graph.nodes:
        x = n["x"] / SCALE + origin["x"]
        y = n["y"] / SCALE + origin["y"]
        z = n["z"] / SCALE + origin["z"]
        if (x - o["x"]) ** 2 + (y - o["y"]) ** 2 <= reach * reach:
            world[n["id"]] = (x, y, z, n)
    inner = {}
    for i, (x, y, z, n) in world.items():
        mx, my = to_model(o, x, y)
        dz = z - o["z"]
        if z0 - 0.5 <= dz <= z0 + h + 0.5 and inside(body, mx, my, MARGIN):
            inner[i] = (mx, my, dz, n)
    if not inner:
        return None
    adj = collections.defaultdict(set)
    for a, b, _ in graph.edges:
        adj[a].add(b)
        adj[b].add(a)
    porch = {}
    for i in inner:
        for j in adj[i]:
            if j in inner or j in porch or j not in world:
                continue
            x, y, z, n = world[j]
            mx, my = to_model(o, x, y)
            if inside(body, mx, my, PORCH) and abs(z - o["z"] - inner[i][2]) <= 1.5:
                porch[j] = (mx, my, z - o["z"], n)
    keep = dict(inner)
    keep.update(porch)
    # exits: a porch node, or an inside node with a link out that is not a porch
    exits = set(porch)
    for i in inner:
        if any(j not in keep for j in adj[i]):
            exits.add(i)
    ids = sorted(keep)
    index = {i: k for k, i in enumerate(ids)}
    nodes = []
    for i in ids:
        mx, my, dz, n = keep[i]
        g = (n.get("gamma", 0.0) - o["gamma"]) % (2 * math.pi)
        nodes.append([round(mx, 3), round(my, 3), round(dz, 3), round(g, 4),
                      round(n.get("radius", 0.5), 3), n.get("material", 1),
                      n.get("criteria") or "", 1 if i in porch else 0])
    edges = []
    for a, b, t in graph.edges:
        if a in index and b in index:
            ca = graph.edge_cost.get((a, b))
            cb = graph.edge_cost.get((b, a))
            edges.append([index[a], index[b], t,
                          None if ca is None else round(ca, 2),
                          None if cb is None else round(cb, 2)])
    floors = floors_of([v[2] for i, v in inner.items() if "STAIR" not in (v[3].get("criteria") or "")]
                       or [v[2] for v in inner.values()])
    return {"nodes": nodes, "edges": edges, "exits": sorted(index[i] for i in exits),
            "floors": floors, "inner": len(inner), "ids": ids}


def worth_keeping(o, t):
    """Real interiors only: raised or sunken floors, stairs and doors, or a
    building with a few nodes inside. A node or two at ground level next to a
    truck or a lamp post is just the yard."""
    inner = [n for n in t["nodes"] if not n[7]]
    if any(abs(n[2]) > 0.15 for n in inner) or any(n[6] for n in inner):
        return True
    return o["type"] == "building" and len(inner) >= 3


def main(argv):
    game = pathlib.Path(argv[argv.index("--game") + 1] if "--game" in argv else str(paths.pristine()))
    sizes = json.load((DATA / "models.json").open())["sizes"]
    best = {}
    for lv in range(1, 15):
        lp = DATA / ("level%d.json" % lv)
        if not lp.exists():
            continue
        objs = json.load(lp.open())["objects"]
        graphs = level_graphs(game, lv)
        for o in objs:
            s = sizes.get(o.get("model"))
            if o.get("cutscene") or not s or not s.get("body"):
                continue
            if o["type"] != "building" and not (o["type"] == "prop" and s.get("h", 0) > 3):
                continue
            for gid, (g, origin) in graphs.items():
                t = interior(o, s, g, origin)
                if not t or not worth_keeping(o, t):
                    continue
                t["src"] = [lv, gid, o.get("id")]
                score = (t["inner"], len(t["edges"]))
                cur = best.get(o["model"])
                if cur is None or score > (cur["inner"], len(cur["edges"])):
                    best[o["model"]] = t
        print("level %2d: %d graphs, %d models with interiors so far" % (lv, len(graphs), len(best)))

    # A model with no instance of its own borrows from a twin: same family,
    # same size (the snow and desert variants of a building)
    alias = {}
    for m, s in sizes.items():
        if m in best or not s.get("body"):
            continue
        fam = m.split("_")[0]
        for k, t in best.items():
            ks = sizes[k]
            if k.split("_")[0] == fam and all(abs(ks.get(f, 0) - s.get(f, 0)) < 0.05 for f in ("w", "d", "h", "z0")):
                alias[m] = k
                break

    out = {"models": {}, "aliases": alias}
    for m, t in sorted(best.items()):
        out["models"][m] = {k: t[k] for k in ("src", "nodes", "edges", "exits", "floors")}
    dst = DATA / "navtemplates.json"
    dst.write_text(json.dumps(out, separators=(",", ":")))
    print("wrote %s: %d models (+%d twins), %d nodes, %s bytes" % (
        dst, len(best), len(alias), sum(len(t["nodes"]) for t in best.values()),
        format(dst.stat().st_size, ",")))
    for m in ("418_01_1", "409_01_1", "458_01_1", "400_20_1"):
        t = best.get(m)
        if t:
            print("   %-9s %-18s nodes %3d  porch %2d  exits %2d  floors %s" % (
                m, sizes[m].get("name", ""), len(t["nodes"]), sum(n[7] for n in t["nodes"]),
                len(t["exits"]), t["floors"]))


if __name__ == "__main__":
    main(sys.argv[1:])
