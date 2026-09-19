# Shaping the ground

What the engine allows, and what the studio will offer for it.

## What the game can do

A level's terrain is a mesh (`terrain.cmd` / `terrain.ctr`) that the studio never
writes. On top of it the engine reads **height maps**: `terrain.hmp` holds up to
256 of them, and a `HeightMap` task in the level script points each one at a
terrain cube — position, lod level, sample count (129 × 129 for a 64 m cube at
lod 13, i.e. one sample every half metre), and the bitmap id.

Each sample is a byte. 64 is "as the mesh has it" and every step is 1/16 m, so a
height map can move the ground **±4 m** and no further. That is the ceiling on
everything below: hollows and banks, yes; a new hill, no.

Two rules found the hard way (2026-09-18):

- **A cube keeps the map the game loaded first.** Adding a second `HeightMap`
  for a cube that already has one does nothing at all — the flattened ground
  under a barracks in level 3 stayed as it was. A cube with a map of its own is
  rewritten in place, keeping its bitmap id, size and task.
- **The level's own edits live in that map**, so a rewrite starts from its
  values rather than from the bare mesh.

## What the studio offers

**Level the ground under a building** (already): ticking it on a building
flattens its footprint plus a 1.5 m margin at the median height under it, eased
back into the slope over the next 4 m.

**The Ground tool** (this plan): shape the ground anywhere, not only under a
building.

- A button in the map's toolbar opens a small panel, as Sight lines does.
- Drag on the map to draw the area — a rectangle, or a circle when *round* is
  ticked.
- Each area carries:
  - **Level to** a height (the median under it by default) — a yard, a road, a
    firing position;
  - **Raise by** / **Lower by** so many metres — a bank, a ditch, a ramp;
  - **Edge**: how far the change eases back into the ground around it.
- Areas are listed in the change log, can be selected on the map, moved,
  resized and removed like anything else.
- The plan shows the result at once: the relief, the contours and the
  buildable-ground layer all read the edited heights, so what you see is what
  the game gets.

On Apply the areas become pads for `studio/build/flatten.py`, exactly as a building's
own pad does, and end up in the same rewritten height maps.

## Limits to respect, and to say out loud

- **±4 m** from the level's own mesh. The panel says how much of the change fits
  and the check list warns when an area asks for more.
- Height maps are **per 64 m cube**; an area that crosses cubes patches each of
  them.
- A level with no `terrain.hmp` (2, 4, 5, 7, 11–14) gets one made for it, which
  the studio already does for building pads.
- Ground under a **building the level ships** can be shaped, but the building
  itself does not move with it.

## Phases

- **A** — the tool, the areas, level/raise/lower with an edge, drawn and
  previewed on the plan, carried in the plan file, built into height maps.
  *Done (2026-09-18):* a dry-run build of three areas on level 3 gave the level
  area its target height to the centimetre, +2.50 m and −1.50 m at the centres
  of the others, and the original ground again past each edge. Still to see
  in game: how the baked lighting reads on shaped ground.
- **B** — smoothing (average the neighbourhood), and a slope tool that ramps
  between two heights along the area. *Done (2026-09-18):* Smooth and Ramp
  areas, rotation for any area, and natural edges (automatic width, a
  smootherstep, value-noise wander shared with the build).
- **C** — a brush for freehand shaping. *Done (2026-09-18):* Raise / Lower /
  Smooth / Erase on a 1 m grid, saved as `brush`.

## Found in game (2026-09-18)

- **Things were left in the air.** Levelling ground next to the radar dome
  in level 3 left the level's crates floating. Now the ground under the
  level's own buildings is kept, and whatever stands on shaped ground (and
  the navmesh under it) moves with it.
- **The edges looked drawn.** A straight falloff over 4 m left hard lines at
  the top and foot of each slope; now the edge scales with the height, eases
  with a smootherstep and wanders.

## Changed after testing in game (2026-09-18)

- Carrying the level's things up or down with the ground did not hold up:
  crates came down but not onto the ground where it sloped, and an alarm
  button mounted on one was left in the air. Now the ground does not change
  under anything standing on it (studio/build/flatten.py keep_for, apply_plan.py
  KEEP, plotter.html keepsGround); the panel and the check list say what
  stands in an area. Navmesh nodes still move with the ground.
- The editor previews the pads under your own buildings (the barracks'
  ground used to show through its walls in the 3D close-up, though the game
  had it levelled).

