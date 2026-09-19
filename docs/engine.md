# What the engine demands

The rules the mission builder enforces, and the one binary format decoded here
rather than in a plan. None of this is documented publicly; each rule was found
by debugging a crash or a broken mission.

## Engine rules the generator enforces

| Rule | What happens if it's broken |
|---|---|
| Task ids must be **≤ 4095** | The engine stores `-1`, and the ids collide: `Symbol "HumanSoldier_-1.isDead" already registered` |
| Coordinates are **game units × 4096** | Objects appear far from where you placed them |
| Every `HumanAI` needs `ai/<id>.qvm` | `No AI script in HumanAI #…`. This includes shipped ids 3001–3333, so they are never deleted by id range |
| Patrol stops must be **routable** in the graph's routing table | `Error in graph 4019 routenet, Node #9 to #34` |
| Guards go in the **gameplay** container, not the intro cutscene's | They load hidden and never appear |
| Text a script shows is a **resource key** (language/*/objectives.res, messages.res) | The objective or label shows nothing |
| The soldier's model must be **packed in the level's `models/levelN.res`** | Invisible guard with a floating rifle |
| Win conditions go **object → StatusMessage → LevelFlow** | Untested path; no shipped level does it differently |
| A static object's yaw is the **last number before the model id** | Buildings face the wrong way |
| The mission list is every `missions/location0/*/mission.qvm` with a `DefineMission` | A slot without one never appears |
| Soldiers stand on **navmesh nodes**, not on collision meshes | A guard in a building with no nodes stands in its foundation |
| Guards walk graph links **straight, through anything** | A building or fence placed across links is walked through |
| Which patrol path a guard walks is set by **his AI script** | Alarm paths shown as his patrol |
| A guard indoors needs an **ALARMON path out** | He reacts to gunfire by walking through the wall |
| Pickups lie with **beta 1.57**, heading in alpha | A rifle stands on end, half through the desk |

## Graph file format (graph*.dat)

Decoded here. Every parseable graph in all 14 levels (293 files) round-trips
byte-for-byte.

- Header: 30 bytes. Magic `0xFFEEDDCC`; `MaxNodes` is the int32 at offset 12.
- Routing table: `MaxNodes²` entries of `{int32 pred, float32 cost}`.
  `pred[a][b]` is the node before `b` on the path from `a` to `b`. `-1` means no
  route. Cost is distance × 4096.
- Nodes: chunks for id, position (3×f64, relative to the `AIGraph` task position),
  gamma, radius, material, and criteria (`STAIR`, `DOOR`, …).
- Edges: 36 bytes each (node, node, type).

Level 8's graphs use a different magic number. The tools won't edit them.
