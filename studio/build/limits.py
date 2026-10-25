# The game's fixed-size task lists, and what fills each one.
#
# IGI.exe keeps tasks of some kinds in lists it makes once, each at a size of
# its own (QTaskList_New, 0x4c1800: a count, a capacity, and that many slots).
# Adding one more than a list holds is the fatal "QTaskList is full"
# (QTaskList_Add, 0x4c1790) while the level loads. Which kinds of task take a
# place in which list was read from the game's own type table (each type is
# registered by name with its parent type, 0x401900): a list takes the type
# whose handler adds to it, and every type made from it. So a HumanSoldierRPG
# takes a place among the people, and a Terminal (an ExplodeObject) among the
# things that move, explode or watch.
#
# The fourteen levels as they ship, at most (level 8 is full of markers):
#
#   markers   32   level 8: 32      humans    128   level 14: 100
#   dynamic  256   level 14: 160    objects   512   level 6: 101
#   pickups  256   level 14: 47     fences     64   level 6: 41
#   helis     16   level 7: 4       cameras    64   level 8: 9
#   blasts   128   (mines; grenades and rifle grenades take places as they fly)
#
# A mission is held to all of them before it is built (studio/build/plan.py),
# so none of them can fill up in the game. The two the game also adds to as it
# plays keep room for that: 16 places of the 256, and 32 of the 128.
import re

# key: (what, capacity the game makes it with, places kept free for the game, the task types that take a place)
LISTS = {
    "markers": ("map computer markers and labels", 32, 0, {"ComputerHilight"}),
    "humans": ("people (guards, soldiers on your side, the player)", 128, 0,
               {"Human", "HumanPlayer", "HumanSoldier", "HumanSoldierFemale", "HumanSoldierPistol", "HumanSoldierRPG"}),
    "dynamic": ("things that move, explode or watch (people, vehicles, cameras, alarms, terminals, explosives)", 256, 16,
                {"AlarmControl", "AlarmLight", "Car", "ExplodeMagicObj", "ExplodeObject", "Generator", "GenericTBA", "Glass",
                 "Heli", "Human", "HumanPlayer", "HumanSoldier", "HumanSoldierFemale", "HumanSoldierPistol",
                 "HumanSoldierRPG", "Mine", "PlaceExplosiveTBA", "Radio", "SCamera", "SCameraControl", "SCameraLens",
                 "Siren", "Terminal"}),
    "objects": ("doors, gates, switches, terminals, ladders, cabinets, fences and wires", 512, 0,
                {"AlarmControl", "Cabinet", "Door", "Fence", "GenericTBA", "Ladder", "PlaceExplosiveTBA", "SCameraControl",
                 "StationaryGun", "Switch", "Terminal", "Wire"}),
    "pickups": ("weapons, ammunition and items to pick up", 256, 0, {"AmmoPickup", "GenericPickup", "GunPickup"}),
    "fences": ("fences and minefields", 64, 0, {"Fence", "Mine", "MineField"}),
    "blasts": ("mines (grenades take places as they fly)", 128, 32, {"Grenade", "M203", "Mine", "MineField"}),
    "helis": ("helicopters", 16, 0, {"Heli"}),
    "cameras": ("security cameras", 64, 0, {"SCamera", "SCameraLens"}),
}

TASK = re.compile(r'Task_New\(\s*(-?\d+)\s*,\s*"([A-Za-z0-9_]+)"')
MARKER = re.compile(r'Task_New\((-?\d+), "ComputerHilight", "((?:[^"\\]|\\.)*)"')


def usage(src):
    """{list key: how many places the script takes in it}"""
    kinds = {}
    for m in TASK.finditer(src):
        kinds[m.group(2)] = kinds.get(m.group(2), 0) + 1
    return {k: sum(n for t, n in kinds.items() if t in types) for k, (_, _, _, types) in LISTS.items()}


def room(key):
    _, cap, keep, _ = LISTS[key]
    return cap - keep


def problems(src):
    """[(key, what, used, room)] for every list the script would fill past what it may take."""
    u = usage(src)
    return [(k, LISTS[k][0], u[k], room(k)) for k in LISTS if u[k] > room(k)]


def _task_end(text, start):
    depth, j, instr = 0, start, False
    while j < len(text):
        ch = text[j]
        if ch == '"' and text[j - 1] != "\\":
            instr = not instr
        elif not instr:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
        j += 1
    return len(text)


def _cut(text, start, end):
    """text[start:end] out, and exactly one of the commas around it."""
    j = end
    while j < len(text) and text[j] in " \t\r\n":
        j += 1
    if j < len(text) and text[j] == ",":
        j += 1
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        return text[:start] + text[j:]
    k = start
    while k > 0 and text[k - 1] in " \t\r\n":
        k -= 1
    if k > 0 and text[k - 1] == ",":
        k -= 1
    return text[:k] + text[end:]


def fit_markers(src):
    """The map computer's markers, made to fit its 32 whatever brought more: the mission's objective
    markers past the level's own numbered ones, labels, an area brought from another level. The
    level's own location labels give way - the last ones in the list first - never an objective's
    marker (its picture is COMPUTER:h_<n>), nor one with an id something could name.
    Returns (src, [titles left out])."""
    found = list(MARKER.finditer(src))
    over = len(found) - room("markers")
    if over <= 0:
        return src, []
    labels = []
    for m in found:
        end = _task_end(src, m.start())
        if m.group(1) != "-1" or "COMPUTER:h_" in src[m.start():end]:
            continue
        labels.append((m.start(), end, m.group(2).strip()))
    gone = []
    for a, b, title in sorted(labels[-over:], reverse=True):       # from the end, so the places before stay put
        src = _cut(src, a, b)
        gone.append(title)
    return src, gone[::-1]
