# Reads, edits and writes IGI 1 navmesh graphs (graphN.dat).
#
#   python studio/build/graphs.py verify --graph <file>
#       Parse, rebuild the routing table from the edge list, re-serialise, and
#       compare byte-for-byte with the original. If this is not IDENTICAL we must
#       not write graphs - the engine would be reading something we invented.
#
#   python studio/build/graphs.py add --graph <file> --origin X,Y,Z --at X,Y,Z [--out F]
#       Add a node at a world position (game units), link it to nearby nodes on
#       the same floor, rebuild routing, write.
#
# FILE LAYOUT (every byte accounted for - verified on level 1 graph 4019)
#   0     u32 magic 0xFFEEDDCC
#   4     chunk 0x04E6, MaxNodes as i32 at 12
#   30    MaxNodes^2 routing entries {i32 pred, f32 cost}, indexed by node id.
#         pred[a][b] is the node just BEFORE b on the shortest path a->b, -1 if
#         there is none. Cost is 3D distance in raw units (metres * 4096).
#   then  one record per node, 6 chunks:
#           0x04CE id(i32)   0x0495 x,y,z(3 x f64, RELATIVE to the AIGraph task's
#           position, raw units)   0x049C gamma(f32)   0x0423 radius(f32)
#           0x0429 material(i32)   0x04E5 criteria(u8 len, string, NUL)
#   then  one record per undirected edge, 3 chunks:
#           0x044A node(i32)   0x04F6 node(i32)   0x0423 type(i32, always 1 seen)
#
# Every chunk is 2-byte big-endian signature + 6 fixed bytes + payload.
#
# The level script's AIGraph task carries "node count, capacity, edge count"
# (level 1 graph 4019: 264, 300, 876). Those must be patched to match whenever
# nodes are added - see graphdata_counts().
import heapq, math, os, re, shutil, struct, sys

SCALE = 4096.0
MAGIC = 0xFFEEDDCC
HEADER = 30
NO_ROUTE = b"\xff\xff\xff\xff\x00\x00\x80\xbf"      # pred -1, cost -1.0
SAME_FLOOR = 2.5                                    # metres of height difference allowed on a link

H = {  # 8-byte chunk prefixes, copied verbatim from shipped files
    "ID":     bytes.fromhex("04ce350700000505"),
    "POS":    bytes.fromhex("0495421d00000808"),
    "GAMMA":  bytes.fromhex("049c7e0f00000606"),
    "RADIUS": bytes.fromhex("0423301400000606"),
    "MAT":    bytes.fromhex("0429b61b00000505"),
    "CRIT":   bytes.fromhex("04e5d31b00000909"),
    "LINK1":  bytes.fromhex("044a100900000505"),
    "LINK2":  bytes.fromhex("04f6180900000505"),
    "LTYPE":  bytes.fromhex("0423a90d00000505"),
}


def _sig(b, o):
    return (b[o] << 8) | b[o + 1] if o + 2 <= len(b) else -1


_F32 = struct.Struct("<f")
_I32 = struct.Struct("<i")


def _f32(x):
    return _F32.unpack(_F32.pack(x))[0]


class GraphError(ValueError):
    pass


class Graph:
    def __init__(self, path):
        self.path = path
        self.raw = open(path, "rb").read()
        if struct.unpack_from("<I", self.raw, 0)[0] != MAGIC:
            raise GraphError("bad magic in %s" % path)
        self.max_nodes = struct.unpack_from("<i", self.raw, 12)[0]
        self.orig_max = self.max_nodes
        self.table_end = HEADER + self.max_nodes * self.max_nodes * 8
        self.nodes, self.edges = [], []          # edges: [a, b, type]
        self._parse()
        # The engine's own weight for every existing edge, read from the routing
        # table. Most are plain 3D distance, but edges touching STAIR and DOOR nodes
        # are weighted by rules we do not know - some are even shorter than the
        # straight line. Keeping the stored value means an untouched edge costs
        # exactly what the engine thinks it costs; only new edges use distance.
        self.edge_cost = {}
        for a, c, _ in self.edges:
            for u, v in ((a, c), (c, a)):
                off = HEADER + (u * self.max_nodes + v) * 8
                if off + 8 <= self.table_end:
                    pr, cost = struct.unpack_from("<if", self.raw, off)
                    if pr == u:
                        self.edge_cost[(u, v)] = cost

    def _parse(self):
        b, off = self.raw, self.table_end
        while off + 12 <= len(b) and _sig(b, off) == 0x04CE:
            n = {"id": struct.unpack_from("<i", b, off + 8)[0]}
            off += 12
            n["x"], n["y"], n["z"] = struct.unpack_from("<3d", b, off + 8); off += 32
            n["gamma"] = struct.unpack_from("<f", b, off + 8)[0]; off += 12
            n["radius"] = struct.unpack_from("<f", b, off + 8)[0]; off += 12
            n["material"] = struct.unpack_from("<i", b, off + 8)[0]; off += 12
            ln = b[off + 8]
            n["criteria"] = b[off + 9:off + 9 + ln].split(b"\0")[0].decode("latin1")
            off += 9 + ln
            self.nodes.append(n)
        while off + 36 <= len(b) and _sig(b, off) == 0x044A:
            a = struct.unpack_from("<i", b, off + 8)[0]
            c = struct.unpack_from("<i", b, off + 20)[0]
            t = struct.unpack_from("<i", b, off + 32)[0]
            self.edges.append([a, c, t])
            off += 36
        if off != len(b):
            raise GraphError("%d unparsed bytes at the end of %s - unknown layout, "
                             "refusing to edit" % (len(b) - off, os.path.basename(self.path)))

    # ------------------------------------------------------------------ routing
    def _pos(self):
        return {n["id"]: (n["x"], n["y"], n["z"]) for n in self.nodes}

    def adjacency(self):
        pos, adj = self._pos(), {n["id"]: [] for n in self.nodes}
        for a, c, _ in self.edges:
            if a in pos and c in pos:
                d = math.dist(pos[a], pos[c])
                adj[a].append((c, self.edge_cost.get((a, c), d)))
                adj[c].append((a, self.edge_cost.get((c, a), d)))
        return adj

    def build_table(self):
        adj = self.adjacency()
        weight = {(u, v): w for u in adj for v, w in adj[u]}
        n = self.max_nodes
        orig = self.raw[HEADER:self.table_end]
        if n != self.orig_max:
            # the graph grew: lay the original entries out in the bigger table
            on = self.orig_max
            grown = bytearray(NO_ROUTE * (n * n))
            for a in range(on):
                grown[a * n * 8:(a * n + on) * 8] = orig[a * on * 8:(a * on + on) * 8]
            orig = bytes(grown)
        # Start from the original bytes, not a blank table: pairs that have no
        # route in both (including the diagonal and unused id slots) keep exactly
        # what the engine wrote.
        out = bytearray(orig)
        for src in range(n):
            if src not in adj:
                # id no longer exists (or never did): nothing routes from it
                row = src * n * 8
                for dst in range(n):
                    i = row + dst * 8
                    if _I32.unpack_from(out, i)[0] != -1:
                        out[i:i + 8] = NO_ROUTE
                continue
            dist, pred, pq, done = {src: 0.0}, {}, [(0.0, src)], set()
            while pq:
                d, u = heapq.heappop(pq)
                if u in done:
                    continue
                done.add(u)
                for v, w in adj[u]:
                    nd = _f32(d + w)          # the engine accumulates in float32
                    if nd < dist.get(v, float("inf")):
                        dist[v], pred[v] = nd, u
                        heapq.heappush(pq, (nd, v))
            row = src * n * 8
            for dst in range(n):
                i = row + dst * 8
                op, oc = struct.unpack_from("<if", orig, i)
                if dst == src or dst not in pred:
                    if op != -1 and dst != src:
                        out[i:i + 8] = NO_ROUTE          # was routable, is not now
                    continue
                nd = dist[dst]
                # Keep the engine's own entry when it is still a correct answer.
                # Our costs agree with its to ~2 raw units but not bit-for-bit
                # (float summation order), so rewriting a correct entry would change
                # the file for nothing. "Still correct" means: same cost, and its
                # predecessor still exists, is still linked to dst, and still lies on
                # a shortest path. That last test matters once nodes can be moved or
                # removed - an equal-cost tie through a deleted node must not survive.
                if (op != -1 and abs(oc - nd) < 4.0 and (op, dst) in weight
                        and (op == src or op in dist)
                        and abs(dist.get(op, 0.0) + weight[(op, dst)] - nd) < 8.0):
                    continue
                struct.pack_into("<if", out, i, pred[dst], nd)
        return bytes(out)

    def isolated(self):
        adj = self.adjacency()
        return sorted(i for i, v in adj.items() if not v)

    # ------------------------------------------------------------------ writing
    def serialise(self, table=None):
        head = bytearray(self.raw[:HEADER])
        if self.max_nodes != self.orig_max:
            # capacity at 12, routing-table byte size at 26
            struct.pack_into("<i", head, 12, self.max_nodes)
            struct.pack_into("<I", head, 26, self.max_nodes * self.max_nodes * 8)
            if table is None:
                raise GraphError("a grown graph needs a rebuilt routing table")
        parts = [bytes(head), table if table is not None else self.raw[HEADER:self.table_end]]
        for n in self.nodes:
            crit = (n.get("criteria") or "").encode("latin1") + b"\0"
            parts += [H["ID"], struct.pack("<i", n["id"]),
                      H["POS"], struct.pack("<3d", n["x"], n["y"], n["z"]),
                      H["GAMMA"], struct.pack("<f", n.get("gamma", 0.0)),
                      H["RADIUS"], struct.pack("<f", n.get("radius", 0.5)),
                      H["MAT"], struct.pack("<i", n.get("material", 3)),
                      H["CRIT"], bytes([len(crit)]), crit]
        for a, c, t in self.edges:
            parts += [H["LINK1"], struct.pack("<i", a), H["LINK2"], struct.pack("<i", c),
                      H["LTYPE"], struct.pack("<i", t)]
        return b"".join(parts)

    def _free_id(self):
        used = {n["id"] for n in self.nodes}
        # Allocate above the highest id first. A vacant id in the middle might be
        # named by some old reference we cannot see; a brand-new id cannot.
        top = max(used) if used else 0
        for i in list(range(top + 1, self.max_nodes)) + [i for i in range(1, top) if i not in used]:
            return i
        return None

    def grow(self, need):
        """Make room for `need` more nodes, in the 100-node steps shipped graphs use."""
        new_max = self.max_nodes
        while len(self.nodes) + need > new_max - 1 or self._free_after(new_max) < need:
            new_max += 100
            if new_max > 1000:
                raise GraphError("a graph of more than 1000 nodes is beyond anything the game ships")
        if new_max != self.max_nodes:
            self.max_nodes = new_max
        return self.max_nodes

    def _free_after(self, cap):
        used = {n["id"] for n in self.nodes}
        return sum(1 for i in range(1, cap) if i not in used)

    def add_raw_node(self, world, origin, criteria="", like=None):
        """A node with no links yet (links are added separately). Returns its id."""
        if self._free_id() is None:
            raise GraphError("graph is full: all %d node slots used" % self.max_nodes)
        nid = self._free_id()
        rel = tuple((w - o) * SCALE for w, o in zip(world, origin))
        ref = like or (self.nodes[0] if self.nodes else {})
        self.nodes.append({"id": nid, "x": rel[0], "y": rel[1], "z": rel[2], "gamma": 0.0,
                           "radius": ref.get("radius", 0.5), "material": ref.get("material", 1),
                           "criteria": criteria or ""})
        return nid

    def link(self, a, b):
        if a != b and not any({e[0], e[1]} == {a, b} for e in self.edges):
            self.edges.append([a, b, 1])

    def near_nodes(self, world, origin, radius, same_floor=SAME_FLOOR, exclude=()):
        """(distance m, id, world xyz) of nodes on the same floor within radius."""
        rel = tuple((w - o) * SCALE for w, o in zip(world, origin))
        out = []
        for n in self.nodes:
            if n["id"] in exclude:
                continue
            dz = abs(n["z"] - rel[2]) / SCALE
            d = math.dist((n["x"], n["y"], n["z"]), rel) / SCALE
            if d <= radius and dz <= same_floor:
                out.append((d, n["id"], tuple(v / SCALE + o for v, o in zip((n["x"], n["y"], n["z"]), origin))))
        return sorted(out)

    def add_node(self, world, origin, link_radius=15.0, max_links=6, link_ok=None):
        """Add a node at a world position (game units). Returns (id, [linked ids]).

        Links only to nodes on the same floor (within SAME_FLOOR metres of height),
        and - given link_ok(a_world, b_world) - only where nothing solid stands in
        between, so a guard never walks through a wall to reach it.
        """
        near = self.near_nodes(world, origin, link_radius)
        if link_ok is not None:
            near = [n for n in near if link_ok(tuple(world), n[2])]
        if not near:
            raise GraphError("no node on the same floor within %.0f m of %.1f, %.1f, %.1f that can be "
                             "reached without passing through a wall" % ((link_radius,) + tuple(world)))
        ref = next(n for n in self.nodes if n["id"] == near[0][1])
        # never inherit STAIR/DOOR from a neighbour: those carry routing rules, and
        # a copied flag would misapply them
        nid = self.add_raw_node(world, origin, "", like=ref)
        linked = [i for _, i, _ in near[:max_links]]
        for o in linked:
            self.edges.append([o, nid, 1])
        return nid, linked

    def _node(self, nid):
        for nd in self.nodes:
            if nd["id"] == nid:
                return nd
        raise GraphError("node %d does not exist" % nid)

    def remove_node(self, nid):
        """Delete a node and every edge touching it. Returns the ids it was linked to.

        Ids are never renumbered: the routing table is indexed by id and patrols
        name nodes by id, so the slot simply becomes unused.
        """
        self._node(nid)
        self.nodes = [nd for nd in self.nodes if nd["id"] != nid]
        linked = sorted({c if a == nid else a for a, c, _ in self.edges if nid in (a, c)})
        self.edges = [e for e in self.edges if nid not in (e[0], e[1])]
        self.edge_cost = {k: v for k, v in self.edge_cost.items() if nid not in k}
        return linked

    def move_node(self, nid, world, origin):
        """Move a node, keeping its links. Their weights become plain distance.

        The engine's stored weight for an edge is only trustworthy for the geometry
        it was computed from, so edges touching a moved node drop it.
        """
        nd = self._node(nid)
        nd["x"], nd["y"], nd["z"] = ((w - o) * SCALE for w, o in zip(world, origin))
        self.edge_cost = {k: v for k, v in self.edge_cost.items() if nid not in k}
        pos = self._pos()
        far = []
        for a, c, _ in self.edges:
            if nid in (a, c):
                other = c if a == nid else a
                if other in pos:
                    d = math.dist(pos[nid], pos[other]) / SCALE
                    dz = abs(pos[nid][2] - pos[other][2]) / SCALE
                    if d > 40 or dz > 6:
                        far.append((other, round(d, 1), round(dz, 1)))
        return far

    def neighbours(self, nid):
        return sorted({c if a == nid else a for a, c, _ in self.edges if nid in (a, c)})


def graphdata_counts(qsc_text, gid, nodes, edges, capacity=None):
    """Patch 'node count, capacity, edge count' in the level script's AIGraph task."""
    pat = re.compile(r'(Task_New\(%d, "AIGraph", "[^"]*", -?[\d.]+, -?[\d.]+, -?[\d.]+, '
                     r'(?:TRUE|FALSE), )(\d+), (\d+), (\d+)' % int(gid))
    m = pat.search(qsc_text)
    if not m:
        raise GraphError("AIGraph task %s not found in the level script" % gid)
    cap = str(capacity) if capacity else m.group(3)
    return qsc_text[:m.start()] + "%s%d, %s, %d" % (m.group(1), nodes, cap, edges) + qsc_text[m.end():]


# ------------------------------------------------------------------------ CLI
if __name__ == "__main__":
    def arg(name, d=None):
        return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else d

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    path = arg("--graph")
    if not path:
        sys.exit("usage: graph_edit.py verify|add --graph <graphN.dat> ...")
    g = Graph(path)

    if cmd == "verify":
        print(os.path.basename(path))
        print("  maxNodes %d   nodes %d   spare %d   edges %d"
              % (g.max_nodes, len(g.nodes), g.max_nodes - len(g.nodes), len(g.edges)))
        table = g.build_table()
        orig = g.raw[HEADER:g.table_end]
        n = len(orig) // 8
        pred_same = sum(1 for i in range(n) if orig[i * 8:i * 8 + 4] == table[i * 8:i * 8 + 4])
        cost_close = sum(1 for i in range(n)
                         if abs(struct.unpack_from("<f", orig, i * 8 + 4)[0]
                                - struct.unpack_from("<f", table, i * 8 + 4)[0]) < 2.0)
        print("  routing predecessors identical: %d/%d" % (pred_same, n))
        print("  routing costs within 2 raw units: %d/%d" % (cost_close, n))
        print("  table byte-identical: %s" % (table == orig))
        same = g.serialise() == g.raw
        print("  file re-serialised: %s" % ("IDENTICAL" if same else "DIFFERS"))
        sys.exit(0 if same else 1)

    elif cmd == "add":
        world = tuple(float(v) for v in arg("--at").split(","))
        origin = tuple(float(v) for v in arg("--origin").split(","))
        out = arg("--out") or path
        nid, linked = g.add_node(world, origin, float(arg("--link", "15")))
        data = g.serialise(g.build_table())
        if out == path and not os.path.exists(path + ".bak"):
            shutil.copyfile(path, path + ".bak")
        open(out, "wb").write(data)
        print("added node %d, linked to %s; %d nodes, %d edges -> %s"
              % (nid, linked, len(g.nodes), len(g.edges), out))
    else:
        sys.exit("commands: verify | add")
