# Seeing it in 3D

Two asks (2026-09-18):

1. **3D models for characters and weapons**, like the buildings and props
   already have.
2. **A 3D close-up of any spot**: the real geometry around an item (walls,
   floors, desks, fences, the ground) in a few metres' radius, where the item
   can be moved by hand. It should answer the questions that today only the
   game answers: is the camera really on that wall, is the rifle on the desk
   or in it, where is the floor of that room.

A third option, starting the game at that spot, was weighed and set aside
(see *Why not the game* below). The close-up is built from what the studio
already reads from the level files.

## What the game files hold (researched 2026-09-18)

**Weapons and items** (models 100–199) are plain static meshes, the same
`.mef` layout as buildings. They are not in the level archives but in the one
archive every level of the location shares:
`missions/location0/common/models/location0.res` (189 models: weapons,
items, a few props). Each `weapons/<NAME>/weapon.qvm` names its models in
`DefineWeaponType(...)`. The first model is the one seen in the world, for
example `WEAPON_ID_AK47` → `100_01_1` and `WEAPON_ID_DRAGUNOV` → `105_01_1`.

**Characters** (models 000–022, five levels of detail `_1`…`_5`) are
skinned:

- `D3DR` is another variant (`[4, faces, groups, ?, ?, verts]`), `XTRV`
  stride 40 = position, normal, uv, weight (f32), a u16, and the **bone index**
  (u16). The group headers are the 14-u16 kind.
- Vertices are in their bone's own space. The skeleton is in
  `common/anims/<hierarchy>.iff`, an EA IFF with big-endian chunk lengths:
  `FORM BOBJ` → `FORM BOBH` → `BOSH` (flags, 33 bones), `PLST` (33 parent
  indices), `TLST` (33 offsets from the parent, game units). `FORM BOAL`
  holds the 95 animations (`BOAN`: `BOAH`, root `BOTH/BOTD`, per bone
  `BORH/BORD` quaternion keys).
- Summing the offsets down the tree with **no rotation** gives the bind pose,
  a soldier standing in an A-pose, 1.80 m tall, origin at the hips 0.97 m up.
  The HumanSoldier task's *Bone Heirachy* field picks the file: 1 for
  guards, 6 for Anya and Ekk, the player 0.
- A soldier's position is his **feet** (29 of 38 level 3 guards sit within
  5 cm of the terrain), so the mesh is baked with the feet at the origin.

**Orientation**: EditRigidObj and most tasks store `alpha, beta, gamma`
with gamma the heading. GunPickup stores `heading, 1.5708, 0` for an item lying
on its side, and the level data kept only the first angle. The studio's level
extract now keeps all three.

**Textures** (for later): `LOOP` v11 files named by model family (the
barracks `418_01_1` has `418_01_1` … `418_05_1`), 16- or 32-bit, up to
1024 × 2048. `XTRV` carries the uvs; which group uses which texture was
found later (see *Status*). The location's shared textures are 68 MB, so they
are served on demand, not shipped with the editor.

## The plan

### A: characters and weapons as models

- `studio/extract/meshes.py` also reads the location's shared archive and:
  - assembles each character's detail-1 model on its skeleton, feet at the
    origin;
  - takes the weapons and items as they are;
  - writes `weapons` (weapon id → model) into `meshes.json`, from the
    weapon scripts.
- The editor's 3D previews (selection panel, map hover card, expanded
  preview, inventory hover card) show guards and pickups as their models.
- `studio/extract/levels.py` keeps a pickup's full orientation and a switch's
  real model (it recorded `"1"`, the task's expression).

### B: the 3D close-up

The **3D** button on the selection panel (and **V**, and *View in 3D* on the
right-click menu) opens a close-up of the selected item: a WebGL view over the
map with the real geometry within a radius of it (10 m by default; 5, 10, 20
or 30 m to choose).

What is in it:

- the **terrain**, from the same 1 m height grid the map uses (with the
  mission's own ground shaping), shaded by the ground material;
- every **model** within the radius, the level's and the mission's own:
  buildings, walls and fences, props, vehicles, crates, desks, doors,
  cameras, alarm hardware, pickups (weapon models), guards (character
  models), at their exact position and heading. The level's objects are
  green-grey, the mission's gold, the one being edited bright and outlined;
- for a camera, its **view cone** (field of view and range).

Looking around:

- drag to orbit, right-drag or Shift-drag to pan, wheel to zoom;
- presets: **Top**, **Front**, **Eye level** (1.7 m), and for a camera
  **Through the camera** (its position, heading, tilt and field of view);
- **Cut above**: a height slider that clips everything above it, so a
  room is seen from above with its ceiling and the floors over it gone. It
  starts just above the item when the item is inside a building;
- **X-ray**: other buildings see-through.

Moving the item:

- **drag it** and it slides over the surfaces under the pointer. A floor
  item (guard, pickup, crate, desk, any prop) goes onto **upward-facing**
  surfaces (ground, floors, desk and crate tops) with its base on them. A
  wall item (camera, alarm button, siren, alarm light) goes onto **upright**
  surfaces (walls, fences, pillars), turned to face out, as on the map;
- **Shift+drag** moves it straight up or down; **R** / **Shift+R** turns it
  15°; arrows nudge it 5 cm;
- a readout names what it stands or hangs on and how high it is above the
  floor or ground;
- every move goes through the same edit path as the map (undo, the change
  log, saving). The map shows the result when the close-up is closed.

Picking and placing:

- click another object in the close-up to edit that one instead;
- with an item picked in the inventory, a click in the close-up drops it
  where the pointer is, on the surface there.

The build keeps a height set in the close-up: such placements carry
`exact: true`, and Apply sets them down where they were put instead of
snapping them to the navmesh or to the surface rules.

### C: textures (after A and B)

Decode `LOOP` v11 (16-bit and 32-bit), find how a group chooses its texture,
and serve decoded textures as PNG from the studio server (`api/texture`),
cached. The close-up asks for the textures of the models it shows and falls
back to plain shading without the server.

## Status (2026-09-18)

A, B and C are in, and verified in the editor (not yet in game):

- 25 characters, all weapons, ammo and items are models; pickups map to
  their models (37 ids).
- The close-up draws the scene with shadows and the game's textures; dragging
  a crate 3 m put it on the ground there to the centimetre; a Dragunov put on
  the checkpoint's floor slab and a camera hung on its wall were written with
  their heights kept (the build left the Dragunov's height alone instead of
  lifting it 0.5 m); undo inside the close-up moved the crate back.
- Textures: group i of a model uses texture i of the model's list in the
  level's `.dat`; `LOOP` v11 is ARGB1555 (2 bytes) or B, G, R, A (4 bytes,
  "_argb8888"). Faces with see-through textures (nets, grilles) are drawn
  with alpha test and are not picked.
- The ground: `terrain/terrain.qvm` (`CreateTerrainMaterial`) says which
  texture sets a ground material uses (set s = textures 3s..3s+2 of
  `terrain.tex`). The close-up colours the ground with them. Some levels name
  sets the (high-resolution) `terrain.tex` of this install does not have;
  those get a neutral earth colour.

Found on the way: the level editor's "waypoint" arrow model on an alarm
control is drawn in the game - it was the arrow next to the radar dome. Ours
now have no model.

Not done yet:

- characters stand in their bind pose (an A-pose); a pose from the animations
  (`BOAN` rotation keys) would make them stand at ease;
- the ground is coloured per material, not textured per material.

## Why not the game

Starting IGI at the spot (a debug start position, then the F11 overlay) was
considered. It needs a full Apply first, a game launch per question, and it
cannot move anything: the answer comes back as coordinates to type in. The
close-up answers the same question in the editor, and it can move the item
right there. The studio's live view (the running game's position on the map)
stays for checking the result in game.

## Technology

- **three.js r160** (MIT), kept in `editor/vendor/`, loaded as an ES module
  through an import map, so the editor keeps working offline. The close-up
  is its own module, `editor/view3d.js`; the editor passes it the scene and
  callbacks and it hands back moves.
- Geometry comes from `meshes.bin` (already loaded for the map). Picking
  and surface snapping raycast against what is drawn, with normals from the
  faces.
- One draw per model; a close-up holds a few dozen models and one terrain
  patch, well within what WebGL does at full frame rate.

## Changed after testing in game (2026-09-18)

- **Heights came from the plan, not the build.** Crates the build set down on
  shaped ground were still drawn at their old height (half in the ground),
  and rifles put on them in 3D kept the crates' old tops, so in the game
  they were inside the crates. Now apply_plan.py writes `heights.json` (the
  z it gives every placement and edit), serve.py runs it as a dry run
  (`GET api/missions/<id>/heights`, cached by plan hash), and the editor
  takes those heights over, moving what rests on each thing by the same
  amount (plotter.html ridersOf / carry / applyHeights).
- **Your alarm buttons** are written by the build as the shipped alarm
  button, 234_01_1; the close-up drew the gate switch. It draws 234_01_1 now.
- **Camera:** orbit controls made the building swing away when you turned
  inside it. It is a free spectator camera now (turn in place, fly where you
  look, 11 m/s, Shift 32 m/s); buildings move only with Alt+drag. The radius
  choices doubled (10/20/40/60 m) and the ground reaches past them into fog.
