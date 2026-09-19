# A built-in level reduced to its map: terrain, sky, light, weather and the player,
# with nothing built on it and no mission logic.
#
#   from empty_map import build_empty
#   text = build_empty(level_script_text)
#
# A level script is a few top-level statements:
#   Container "EnvironmentalEffects"   light, sun, sky, rain or snow     -> kept as is
#   Static                             terrain modifiers + static objects -> terrain kept
#   Dynamic                            buildings, AI, cutscenes, logic   -> rebuilt
#   LevelFlow                          complete / failed expressions     -> never completes
#
# What is copied out of the level: HeightMap, TextureModifier, CubeModifier and
# TerrainLightMap (the terrain's shape, paint and baked light), every AIGraph (the
# navmesh stays, so guards can be placed and patrol), AmbientArea (wind, birds)
# and the HumanPlayer with his loadout, taken out of the cutscene condition he
# sits in. DiscardTerrain is not copied: it cuts holes under bunkers, and with
# the bunker gone the hole opens onto nothing. Mission logic is not copied either:
# its expressions name buildings, terminals and cars that are no longer there.
import re
from studio.qvm import source as qvm_source

INSERT = "/*@@PLOTTER_INSERT@@*/"
TERRAIN = ("HeightMap", "TextureModifier", "CubeModifier", "TerrainLightMap")
KEEP_DYNAMIC = ("AIGraph", "AmbientArea")


def tasks(text, start=0):
    """Every Task_New in text: dicts with type, name, id, start, end, depth,
    parent index. end is just past the closing parenthesis."""
    out, stack, depth_parens = [], [], []
    i, instr, n = start, False, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            instr = not instr
        elif not instr:
            if text.startswith("Task_New(", i):
                m = re.match(r'Task_New\((-?\d+), "([A-Za-z0-9_]+)", "((?:[^"\\]|\\.)*)"', text[i:])
                t = {"id": int(m.group(1)), "type": m.group(2), "name": m.group(3), "start": i,
                     "depth": len(stack), "parent": stack[-1] if stack else None}
                out.append(t)
                stack.append(len(out) - 1)
                depth_parens.append(0)
                i += len("Task_New(")
                continue
            if c == "(":
                depth_parens[-1] += 1 if depth_parens else 0
            elif c == ")" and stack:
                if depth_parens[-1]:
                    depth_parens[-1] -= 1
                else:
                    out[stack.pop()]["end"] = i + 1
                    depth_parens.pop()
        i += 1
    return out


def _outermost(ts, types):
    """Tasks of the given types that are not inside another task of those types."""
    keep = []
    for t in ts:
        if t["type"] not in types:
            continue
        p, inside = t["parent"], False
        while p is not None:
            if ts[p]["type"] in types:
                inside = True
                break
            p = ts[p]["parent"]
        if not inside:
            keep.append(t)
    return keep


def build_empty(text, eol="\r\n"):
    first = text.index("Task_New(")
    head = text[:first]
    ts = tasks(text, first)
    top = [t for t in ts if t["depth"] == 0]
    env = [t for t in top if t["type"] == "Container" and t["name"] == "EnvironmentalEffects"]
    if not env:
        raise ValueError("no EnvironmentalEffects container at the top of the level script")
    player = [t for t in ts if t["type"] == "HumanPlayer"]
    if not player:
        raise ValueError("the level has no HumanPlayer")

    def body(t):
        return text[t["start"]:t["end"]]

    def group(name, items):
        if not items:
            return 'Task_New(-1, "Container", "%s")' % name
        return ('Task_New(-1, "Container", "%s", ' % name + eol +
                ("," + eol).join(body(t) for t in items) + ")")

    terrain = _outermost(ts, TERRAIN)
    static = [group(ty, [t for t in terrain if t["type"] == ty]) for ty in TERRAIN]
    graphs = _outermost(ts, ("AIGraph",))
    ambience = _outermost(ts, ("AmbientArea",))
    flow = [t for t in top if t["type"] == "LevelFlow"]
    flow_id = flow[0]["id"] if flow else 10

    out = [head.rstrip() + eol,
           body(env[0]) + ";" + eol,
           'Task_New(-1, "Static", "", ' + eol + ("," + eol).join(static) + ");" + eol,
           'Task_New(-1, "Dynamic", "", ' + eol +
           group("Navmesh", graphs) + "," + eol +
           group("Ambience", ambience) + "," + eol +
           'Task_New(-1, "Container", "Player", ' + eol + body(player[0]) + ")," + eol +
           'Task_New(-1, "Container", "Guards", ' + eol + INSERT +
           'Task_New(-1, "Container", "End of guards")));' + eol,
           # a map with no objective: it never completes and never fails on its own
           'Task_New(%d, "LevelFlow", "", 0, 0, 0, 0, 0, 0, 0, "FALSE", "FALSE", FALSE, 0);' % flow_id + eol]
    return "".join(out)


if __name__ == "__main__":
    import os, pathlib, sys
    from studio.qvm import compile as CQ
    out_dir = pathlib.Path(__file__).resolve().parents[2] / "missions" / "_empty"
    out_dir.mkdir(parents=True, exist_ok=True)
    levels = [int(a) for a in sys.argv[1:]] or list(range(1, 14))
    for lv in levels:
        src = qvm_source.level_qsc(lv).read_text(encoding="latin1")
        try:
            text = build_empty(src)
        except ValueError as e:
            print("level %2d: %s" % (lv, e))
            continue
        f = out_dir / ("level%d" % lv) / "objects.qsc"
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(text.replace(INSERT, "").encode("latin1"))
        ts = tasks(text, text.index("Task_New("))
        kinds = {}
        for t in ts:
            kinds[t["type"]] = kinds.get(t["type"], 0) + 1
        try:
            q = CQ.compile_qsc(f)
            ok = "compiles (%s bytes)" % format(q.stat().st_size, ",")
        except CQ.CompileError as e:
            ok = "FAILS: " + str(e)[:200]
        print("level %2d: %6s bytes, graphs %d, player %d, ambience %d, terrain %d -> %s" % (
            lv, format(len(text), ","), kinds.get("AIGraph", 0), kinds.get("HumanPlayer", 0),
            kinds.get("AmbientArea", 0), sum(kinds.get(k, 0) for k in TERRAIN), ok))
