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
| The mission list **follows each `DefineMission`'s next mission from mission 1**, up to `GOActiveMission` | A mission the chain does not reach never appears; a link to a mission that is not there crashes the main menu (`Config_FillMissionPictureBox` walks the whole chain unchecked). The game ships level 14 leading to none |
| Soldiers stand on **navmesh nodes**, not on collision meshes | A guard in a building with no nodes stands in its foundation |
| Guards walk graph links **straight, through anything** | A building or fence placed across links is walked through |
| Which patrol path a guard walks is set by **his AI script** | Alarm paths shown as his patrol |
| A guard indoors needs an **ALARMON path out** | He reacts to gunfire by walking through the wall |
| Pickups lie with **beta 1.57**, heading in alpha | A rifle stands on end, half through the desk |
| A height map moves the ground **(value − 64)/16 m, 0..127**: about ±4 m, and only on cubes of level 14 and finer | A bigger change needs the terrain mesh itself (below) |
| The terrain holds **at most 32,767 nodes** (its child indices are i16); the levels use 11,000–15,000 | New unique ground has a budget: a 150 m mountain 800 m across is about what a level has room for |
| A terrain grid point **sits on the height step of the coarsest level it appears on** | Levels of detail stop meeting: cracks at a distance |
| A terrain grid point is **never exactly on a cube's floor, ceiling or middle height** (inside its cube only 4, 8, 10, 14, 16, 20, 28, 32, 34, 38, 40 or 44 of 48 steps up) | It is in two stacked cubes at once, and the cubes beside disagree on their shared side |
| A cube's mesh stays small: **at most 35 vertices** in the game's own, nearly all within a 1600-byte render buffer | The renderer keeps drawn cubes in fixed pools (700 × 1600 B, 50 × 3200 B, 16 × 8000 B); past them a cube is drawn as a hole or a spike |
| Where the ground **hangs over itself**, a grid point has two or three heights in cubes above each other | A cube built again from one height loses the overhang; the unchanged cube beside keeps its half, a side ending in the air |

## Terrain mesh (terrain.ctr, terrain.cmd)

Decoded here (`studio/build/terrain_mesh.py`). Both files round-trip
byte-for-byte on levels 1–13; level 14's terrain is not a terrain (two nodes).

- `terrain.ctr`: 32-byte nodes: 8 × i16 child index, 8 × i8 child transform
  (−1 where there is no child), u8 child mask, 3 pad bytes (the same in every
  node of a level), u32 offset of the node's mesh in `.cmd`. Node 0 is unused,
  node 1 the root (±2^30 raw). Leaves are at level 16: 8 m cubes. Nodes and
  meshes are shared, turned or mirrored by the transform (0–7), so the tree is
  a graph - which is why the same pyramid repeats across a level.
- `terrain.cmd`: meshes back to back: u16 triangles, u16 4 × triangles, u16
  fixed vertices, u16 sliding vertices, then u32 per triangle (indices at bits
  16, 0 and 8 in drawing order, counter-clockwise from above; top byte `0xF0`
  where a strip ends, `0xE0` where it goes on) and u32 per vertex (x, y, z in
  6 bits at bits 26, 20, 14, 0..48 across the cube; texture projection for
  steep faces at bits 8–9 and 6–7; bits 0–5 the fixed vertex a sliding one
  merges into as the cube is seen from further away).
- **Every cube is the same shape:** a 3 × 3 grid over its square, corners
  fixed, edge middles and centre sliding onto a corner, 8 triangles on the
  anti-diagonal; cut where the ground crosses the cube's floor, middle or
  ceiling (floor and ceiling cuts fixed, middle cuts sliding - that is where
  its children meet). Merged, a cube is its parent's two triangles.
- **The terrain is one height grid, a sample every 4 m**: a grid point has the
  same height at every level of detail it appears on. A point first seen at
  level L sits on that level's step, 2^(27−L)/3 raw: 0.17 m at the leaves,
  2.7 m for a point every 64 m, 21 m for one every 512 m.
- The game's own cut points are not always on the straight line between grid
  points (they come from finer source data), so a rebuilt cube takes the
  level's own cut points on every piece of its edge whose ends did not change:
  the cube beside it has them too. A level's mesh lists a point once for each
  texture projection its faces use; taken over, each is used once.
- **Not a height field everywhere.** Here and there the ground hangs over
  itself (a cliff edge; about 11 grid points in a square kilometre of level
  7, 20–30 m between the surfaces). Rebuilt cubes that reach such a point take
  every cube round it with them, at the upper height (the one the game's
  height query and everything standing there use), so no cube is left with
  half an overhang; the height maps there are left as they were.
- **Rebuilt heights stay off the floors**: a new grid height that would land
  on a multiple of 8 m (a leaf's floor; every level's floors and middles are
  among them) goes one step up or down. The game's full rule is not followed,
  as it would move a point every 256 m by up to 40 m.
- The build's own check, `terrain_mesh.seams()`: every pair of cubes side by
  side and stacked meet, and a side with ground on it has a cube beside it.
  The levels' own terrain passes it everywhere; so must a rebuilt one.
- `terrain.lmp`: light maps back to back (u32 size, size × size grey bytes,
  bottom row first, 0 = none), each laid over a cube by a `TerrainLightMap`
  task (Level, Size, TextureIndex); 8 to 256 m a pixel.

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
