# Plan: the next eight features

Built in order from least to most work. Each phase is committed on its own.
**In game** marks what can only be proven by playing the mission.

## Phase 1 - 3D preview of the selected building (small)

- [x] `meshes.js`: orbit render of a model (painter's order, sun shading), any yaw/pitch.
- [x] Inspector: a preview panel for buildings and props with a mesh; drag to turn,
      wheel to zoom, slowly turns on its own until touched; size and height under it.
- [x] Inventory: hovering a structure shows the same preview in a tooltip card.

## Phase 2 - Check list before Apply (small)

- [x] One list, grouped by severity, built in the editor before anything is sent:
  - patrol stops that can't be reached (`patrolIssues`)
  - buildings that overlap, stand on steep ground or off the map (`placeCheck`)
  - objects floating or buried (terrain grid; the server's surfaces when it is up)
  - guards with no graph, nodes with no links, graphs over capacity
  - models to import: count and size (server: `/api/imports`)
- [x] Each row: what, where, **Show** (select and jump), and **Fix** where there is
      one (drop to the ground, remove the stop).
- [x] Apply opens the list first; errors block, warnings don't. Also on the Mission menu.

## Phase 3 - Live view (medium)

- [x] `live_pos.py` becomes importable (functions, no work on import) plus a
      `LiveReader` class: attach, auto-calibrate, read.
- [x] Calibration without typing: at the start of a mission the player stands at
      the level's start, which the level data gives. Scan for that position, then
      after the player moves keep the candidates that moved and still sit on the
      ground (terrain grid ±3 m).
- [x] Server: `GET /api/live` (position, heading from movement, status), `POST /api/live/calibrate`.
- [x] Editor: toolbar button, a live player marker with a trail, follow mode,
      "place here" (drop the tool where you stand). Tested against a stand-in process;
      **in game**: confirm the game keeps the position in one of the scanned forms.

## Phase 4 - Faster editing (medium)

- [x] Multi-selection: Shift+drag a box, Shift+click to add or remove; the inspector
      shows the group (count, kinds).
- [x] Group actions: drag to move, R/T rotate about the centre, Delete, Ctrl+D,
      arrows nudge; one undo step each.
- [x] Copy / paste (Ctrl+C / Ctrl+V) at the cursor; the clipboard lives in the
      browser, so it works between missions and levels (models not packed there
      are imported on Apply as usual).
- [x] Saved groups (prefabs): "Save as group" names the selection; the server keeps
      them in `missions/groups/`; the inventory lists them in a Groups section with
      a thumbnail; placing one stamps every member, rotated as a whole. Guards
      keep their patrols only when the stops are their own new nodes in the group.

## Phase 5 - Sight lines and blind spots (medium)

- [x] Obstacle height grid for the level: terrain plus every building's top from its
      mesh (1 m), rebuilt when your buildings change.
- [x] Viewshed from a point: rays every 1°, 0.5 m steps, eye at 1.7 m (guards) or
      the camera's own height, target at 1.2 m (a crouching player); visible where
      nothing rises above the sight line.
- [x] Selected guard or camera: its view cone drawn on the map (field of view and
      range settable, defaults per kind).
- [x] Coverage layer: every guard (patrols sampled along their route) and camera;
      cells seen by several are brighter, blind spots inside the yard stay dark.
      Toolbar toggle and a legend entry. **In game**: compare with what guards
      actually notice and tune the defaults.

## Phase 6 - Flatten the ground under new buildings (large, in game)

Facts (from `terrain.py`, a port of the game's height query): a `HeightMap` task
(Static container) lays `terrain.hmp` item *Bitmap ID* over the octree cube of its
*Level* that holds its position; each sample moves the terrain vertices by
`(value - 64) / 16` m, bilinear; where several cover a point the last one wins.

- [x] Read and write `terrain.hmp` (256 12-byte headers, data in id order).
- [x] `studio/build/flatten.py`: for each of your buildings with flattening on, the cubes
      (level 13, 64 m, 65x65 samples) its footprint and a 3 m apron touch; start each
      from the heights the level already applies there (so an existing height map is
      carried over, not lost), set the footprint to the target height, blend the apron.
- [x] Apply: write the slot's `terrain.hmp` and add the `HeightMap` tasks after the
      shipped ones; the building then stands at the flattened height.
- [x] Editor: "Flatten ground" on a building (default on), preview on the terrain
      layer, placement check treats flattened ground as level.
- [ ] **In game**: the ground renders and collides at the new height; lighting;
      guards and nodes on the pad.

## Phase 7 - Mission objectives (large, in game)

Facts: `DefineComputerObjective` (up to 6: text resource, map position, complete and
failed expressions), `LevelFlow` (complete / failed expressions), `StatusMessage`,
`ComputerHilight` (map-computer label: task id, title and info resources).

- [x] Research: where objective and label text resources live, whether a mission can
      carry its own strings without touching the shared language files, and how
      shipped expressions test "destroyed", "picked up" and "reached".
- [x] Objective kinds: destroy an object, kill a guard / all guards, collect a
      pickup, reach an area, use a terminal; each becomes a complete expression.
- [x] Editor: an Objectives panel (text, kind, target picked on the map), mission
      briefing text, map-computer labels for your own buildings.
- [x] Apply: objectives, LevelFlow complete/failed, a status message per objective,
      labels. **In game**: each kind completes and the mission ends.

## Phase 8 - Real ground textures (research, large)

- [x] Decode `terrain.tex` (LOOP), `terrain.bit` (per-cell texture index) and the
      `TextureModifier` tasks; find how a terrain cell picks its texture and UVs.
- [x] Bake per level: a material per terrain cell (masks checked against slope) and a grey tile per material.
- [ ] Still open: which of a material's three textures the game shows where, their scale, and the lightmap.
- [x] Editor: draw it under the relief, tinted to the map computer's green.
