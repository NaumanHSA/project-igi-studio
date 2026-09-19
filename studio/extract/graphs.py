# Parses IGI 1 navigation graph .dat files into node positions.
#
#   python studio/extract/graphs.py [--levels 1,2] [--game <game>] [--out <folder>]
#
# Format ported from project-igi-editor's source/parsers/graph_parser.cpp:
#   u32  magic            0xFFEEDDCC
#   u16  sig 0x04E6 @4    MaxNodes, payload i32 at +8
#   30                    header size
#   MaxNodes^2 * 8        adjacency table
#   then node records:    sig 0x04CE id(i32@+8) len 12
#                         sig 0x0495 x(f64@+8) y(f64@+16) z(f64@+24) len 32
#                         sig 0x049C gamma, 0x0423 radius, ... (not needed here)
# Signatures are big-endian u16; payloads little-endian.
#
# Node coordinates come out in raw QSC units and are converted to GAME units
# (/4096) to match everything else in the editor.
import json, os, re, struct, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
from studio.build import graphs as GE
from studio import paths
# This module is a script: it does its work as it is read, the way it always
# has. Run it (python -m studio.extract.graphs), do not import it. The guard below
# turns an accidental import into a clear error instead of a surprise.
if __name__ != "__main__":
    raise ImportError("studio.extract.graphs is a script: run it, do not import it")
argv = sys.argv
GAME = pathlib.Path(argv[argv.index("--game") + 1] if "--game" in argv else str(paths.game()))
OUT = ROOT / argv[argv.index("--out") + 1] if "--out" in argv else paths.data()
LEVELS = ([int(x) for x in argv[argv.index("--levels") + 1].split(",")]
          if "--levels" in argv else list(range(1, 15)))
SCALE = 4096.0

MAGIC = 0xFFEEDDCC
SIG_MAX_NODES = 0x04E6
SIG_NODE_ID = 0x04CE
SIG_NODE_POS = 0x0495


def sig(buf, off):
    return (buf[off] << 8) | buf[off + 1] if off + 2 <= len(buf) else -1


def parse_graph(path):
    b = path.read_bytes()
    if len(b) < 30:
        return None, "too small"
    if struct.unpack_from("<I", b, 0)[0] != MAGIC:
        return None, "bad magic"
    if sig(b, 4) != SIG_MAX_NODES:
        return None, "no MaxNodes signature"
    max_nodes = struct.unpack_from("<i", b, 12)[0]
    if not (0 < max_nodes <= 4096):
        return None, "implausible MaxNodes %d" % max_nodes

    # The adjacency table at offset 30 is the engine's own routing answer:
    # maxNodes^2 entries of {int32 next-hop, float32 cost}, indexed by node id.
    # next == -1 means there is no route, which is exactly what produces
    # "Error in graph NNNN routenet, Node #A to #B" at level load.
    # 99% of pairs route, so only the exceptions are worth storing.
    def next_hop(i, j):
        off = 30 + (i * max_nodes + j) * 8
        return struct.unpack_from("<i", b, off)[0] if off + 4 <= len(b) else -1

    start = 30 + max_nodes * max_nodes * 8
    nodes = []
    if start < len(b):
        off = start
        while off + 12 <= len(b) and sig(b, off) == SIG_NODE_ID:
            nid = struct.unpack_from("<i", b, off + 8)[0]
            off += 12
            if off + 32 > len(b) or sig(b, off) != SIG_NODE_POS:
                break
            x = struct.unpack_from("<d", b, off + 8)[0]
            y = struct.unpack_from("<d", b, off + 16)[0]
            z = struct.unpack_from("<d", b, off + 24)[0]
            off += 32
            nodes.append({"id": nid,
                          "x": round(x / SCALE, 2),
                          "y": round(y / SCALE, 2),
                          "z": round(z / SCALE, 2)})
            # skip forward to the next node record; field layout after position
            # varies, so resync on the next NODE_ID signature
            nxt = off
            while nxt + 2 <= len(b) and sig(b, nxt) != SIG_NODE_ID:
                nxt += 1
                if nxt - off > 4096:
                    nxt = len(b)
                    break
            off = nxt

    ids = [n["id"] for n in nodes]
    no_route, isolated = [], []
    for a in ids:
        bad = [c for c in ids if c != a and next_hop(a, c) == -1]
        if len(bad) > len(ids) * 0.8:
            isolated.append(a)          # reaches almost nothing: unusable
        else:
            no_route.extend([a, c] for c in bad)
    # drop pairs that only fail because the other end is isolated
    iso = set(isolated)
    no_route = [p for p in no_route if p[1] not in iso]
    return {"maxNodes": max_nodes, "nodes": nodes,
            "isolated": isolated, "noRoute": no_route}, None


total_nodes = 0
for lv in LEVELS:
    gdir = GAME / "missions" / "location0" / ("level%d" % lv) / "graphs"
    if not gdir.is_dir():
        print("level %-2d  no graphs dir" % lv)
        continue
    lvfile = OUT / ("level%d.json" % lv)
    origins = {}
    if lvfile.exists():
        origins = json.load(lvfile.open()).get("graphOrigins", {})
    out = {}
    for f in sorted(gdir.glob("graph*.dat")):
        m = re.fullmatch(r"graph(\d+)\.dat", f.name)
        if not m:
            continue
        g, err = parse_graph(f)
        if err:
            print("   %-18s %s" % (f.name, err))
            continue
        gid = m.group(1)
        # links between nodes, and which nodes are stairs or doors, from the
        # full parser - the editor draws links and walks guards along them
        try:
            full = GE.Graph(str(f))
            g["edges"] = [[a, c] for a, c, _ in full.edges]
            crit = {n["id"]: n["criteria"] for n in full.nodes if n.get("criteria")}
            for n in g["nodes"]:
                if n["id"] in crit:
                    n["c"] = crit[n["id"]]
            g["editable"] = True
        except GE.GraphError:
            g["edges"], g["editable"] = [], False
        o = origins.get(gid)
        if o:
            for n in g["nodes"]:
                n["x"] = round(n["x"] + o["x"], 2)
                n["y"] = round(n["y"] + o["y"], 2)
                n["z"] = round(n["z"] + o["z"], 2)
            g["origin"] = o
        else:
            g["origin"] = None
            g["relative"] = True
        out[gid] = g
        total_nodes += len(g["nodes"])
    p = OUT / ("graphs%d.json" % lv)
    json.dump(out, p.open("w"), separators=(",", ":"))
    got = sum(len(v["nodes"]) for v in out.values())
    print("level %-2d  %2d graphs  %5d nodes  %6.0f KB"
          % (lv, len(out), got, p.stat().st_size / 1024))

print("\n%d nodes parsed in total -> %s" % (total_nodes, OUT))
