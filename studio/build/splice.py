# Where in a level's script the mission's own tasks go (studio/build/plan.py).
#
# Beside the game's own guards, in the part of the level that is there for the
# whole of play. Not just before the first soldier: in level 1 that is id 1505,
# inside ConditionalContainer 'Intro cutscene' / 'Opening heli and train', so
# anything placed there exists only while the intro plays. Nor inside a branch
# that waits for something: level 8's best-named guards are in 'SAM guard 442',
# which comes to life only once the player is at the SAM site with the beacon,
# and in levels 4, 6, 9 and 14 they are inside a GuardGenerator, which spawns
# copies of what it holds. Our tasks go in just before such a branch, as its
# sibling, so they are there from the start.
import re

# a ConditionalContainer that only waits for the level's cutscenes to be over
_AFTER_CUTSCENES = re.compile(r"!ConditionalContainer_\d+\.isRun(?:&&!ConditionalContainer_\d+\.isRun)*")


def container_chain(text, pos):
    """Every task enclosing an offset, outermost first: (offset, id, type, name)."""
    stack, i, instr = [], 0, False
    while i < pos:
        c = text[i]
        if c == '"':
            instr = not instr
        elif not instr:
            if text.startswith("Task_New(", i):
                mm = re.match(r'Task_New\((-?\d+), "([A-Za-z0-9_]+)", "([^"]*)"', text[i:])
                stack.append((i,) + (mm.groups() if mm else ("?", "?", "")))
                i += len("Task_New(")
                continue
            elif c == "(":
                stack.append(None)
            elif c == ")" and stack:
                stack.pop()
        i += 1
    return [s for s in stack if s]


def live_part(text, chain, player):
    """How much of a chain is there for the whole of play, and where it stops.

    Plain containers are, and a ConditionalContainer that holds the player (the
    offsets in player) or only waits for the cutscenes to be over. Anything else
    is not: a container that waits for something to happen in the mission, or a
    GuardGenerator. Returns (the live part, the offset of the first task that is
    not live, or None when all of it is)."""
    for k, (at, _id, kind, _name) in enumerate(chain):
        if kind in ("Container", "Dynamic"):
            continue
        if kind == "ConditionalContainer":
            if at in player:
                continue
            mm = re.match(r'Task_New\(-?\d+, "ConditionalContainer", "[^"]*", "([^"]*)"', text[at:])
            if mm and _AFTER_CUTSCENES.fullmatch(re.sub(r"\\n|\s", "", mm.group(1))):
                continue
        return chain[:k], at
    return chain, None


def pick(text):
    """(score, offset to insert at, the containers it is in) - None if the level
    has no soldier to go beside."""
    pm = re.search(r'Task_New\(-?\d+, "HumanPlayer", "', text)
    player = {c[0] for c in container_chain(text, pm.start())} if pm else set()
    best = None
    for m in re.finditer(r'Task_New\(\d+, "HumanSoldier", "', text):
        chain, stop = live_part(text, container_chain(text, m.start()), player)
        names = " ".join((c[3] or "").lower() for c in chain)
        score = len(chain)
        if re.search(r"\bguard", names):
            score += 10
        if re.search(r"\bai\b", names):
            score += 5
        if best is None or score > best[0]:
            best = (score, m.start() if stop is None else stop, chain)
    return best


def describe(chain):
    """The last few containers of a chain, for the build's log."""
    return " > ".join(("%s(%s)%s" % (c[2], c[1], (" " + c[3]) if c[3] else ""))
                      for c in chain[-3:]) or "(top level)"
