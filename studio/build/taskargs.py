"""How many parameters each kind of task takes, and a check of a level script.

The game refuses a level in which a task has more or fewer parameters than its
kind takes, and says no more than "Too few parameters in line 0 of file
LOCAL:missions/location0/level16//objects.qsc" - always line 0, as a compiled
script keeps no lines. The build checks its own script against this table
before anything is installed, so a mistake in a writer stops Apply with the
task's name instead of stopping the game.

COUNTS is how the fourteen levels' objects.qvm write each kind: every task of
a kind there has the same count, the plain values after the task's id, kind
and name (a task nested in another is not counted). AnimTask carries its
animation data inline, of any length, and is not checked. A kind the game
never writes is not checked either.
"""
import re

COUNTS = {
    "AIGraph": 14, "AIStationaryGunHolder": 12, "AddAmmo": 2, "AlarmControl": 21,
    "AlarmLight": 12, "AmbientArea": 12, "AmmoPickup": 8, "AreaActivate": 10,
    "Binocular": 2, "BinocularOverlayHolder": 1, "Building": 7, "Cabinet": 6,
    "Car": 19, "CarAI": 3, "ComputerHilight": 10, "ConditionalContainer": 3,
    "ConditionalSound": 8, "Container": 0, "CubeModifier": 5, "CutScene": 18,
    "DefineComputerObjective": 25, "Dirlight": 3, "DirlightKeyframe": 9,
    "DiscardTerrain": 4, "Door": 20, "Dynamic": 0, "EditCamera": 20,
    "EditRigidObj": 13, "EditVariable": 6, "Elevator": 29, "ExplodeObject": 17,
    "Fence": 6, "FlatSky": 23, "FlatSkyLayer": 8, "Generator": 22,
    "GenericPickup": 7, "GenericTBA": 22, "GlobalLight": 8, "GlobalLightKeyframe": 51,
    "GuardGenerator": 2, "Gun": 2, "GunDRAGUNOV": 2, "GunM16A2": 2, "GunMP5SD": 2,
    "GunPickup": 7, "GunSPAS12": 2, "HeightMap": 9, "Heli": 19, "HumanAI": 2,
    "HumanPlayer": 6, "HumanPlayerInput": 4, "HumanSoldier": 8, "HumanSoldierFemale": 8,
    "HumanSoldierRPG": 8, "LODSettings": 8, "LevelFlow": 11, "LevelTimer": 9,
    "LightmapInfo": 10, "MineField": 14, "MipMapControl": 4, "PatrolPath": 0,
    "PatrolPathCommand": 2, "PlaceExplosiveTBA": 24, "Plane": 16, "Radio": 23,
    "RainEffect": 5, "RotatingObject": 16, "SCamera": 17, "SCameraControl": 20,
    "Siren": 20, "Smoke": 25, "SplineObj": 16, "SplineObjWaypoint": 12, "Static": 0,
    "StationaryGun": 12, "StatusMessage": 13, "Switch": 14, "Terminal": 19,
    "TerrainLightMap": 7, "TextureModifier": 8, "Train": 10, "Wire": 7,
}

_TASK = re.compile(r'Task_New\(')


def _args(text, open_at):
    """(start, end) of each argument of the call whose "(" is at open_at."""
    spans, depth, i, start, n = [], 0, open_at, open_at + 1, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                if text[start:i].strip():
                    spans.append((start, i))
                return spans
        elif c == "," and depth == 1:
            spans.append((start, i))
            start = i + 1
        i += 1
    return spans


def mismatches(text):
    """[(kind, name, count, (the count its kind takes,))] for every task in a
    level script whose count is not its kind's."""
    out = []
    for m in _TASK.finditer(text):
        spans = _args(text, m.end() - 1)
        if len(spans) < 3:
            continue
        kind = text[spans[1][0]:spans[1][1]].strip().strip('"')
        want = COUNTS.get(kind)
        if want is None:
            continue
        n = sum(1 for a, b in spans[3:] if not text[a:b].lstrip().startswith("Task_New("))
        if n != want:
            out.append((kind, text[spans[2][0]:spans[2][1]].strip(), n, (want,)))
    return out
