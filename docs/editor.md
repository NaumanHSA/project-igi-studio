# The editor, feature by feature

What every part of the editor does, how it does it, and what it builds into the
game. This is the reference for working on the studio. Players have the
[manual](https://naumanhsa.github.io/project-igi-studio-site/manual/), which
covers the same ground without the internals.

## Running it from a checkout

```
python -m studio
```

This opens `http://localhost:8765/plotter.html`.

1. The **mission library** opens. Click **New mission**, name it, and start
   from a **copy of a mission** or an **empty map**.
2. Place things from the inventory (or right-click the map). To give a guard a
   route, select him, click **Edit patrol route**, and click nodes on the map.
3. Press **Apply**. The mission is built from its base and installed into its
   own slot.
4. Launch the game (its `IGI-Debug.bat` shows the console) and pick the mission by its name.

Everything saves as you go. **Settings** holds the game folder.

## Missions

The library has two shelves.

- **Your missions:** a cover (a picture of your map, or the base mission's),
  the base, the guard and change counts, and the game status: *not in the game
  yet*, *mission 15 · up to date*, or *changes not applied*. The **⋯** menu
  has open, rename, duplicate, export, remove from the game, and delete.
- **Built-in missions:** the 14 missions with their in-game cover picture,
  name, description and map type. They can't be changed, renamed or deleted.
  Click one to look around its map (read-only), or **New mission from this**.

A mission is a **base plus a plan**:

- **Base:** one built-in mission, as a *copy* (every guard, building and
  objective) or an *empty map*.
- **Plan:** every change you make.

**Apply builds from the untouched base and the whole plan, every time.** Nothing
is built on top of an earlier Apply. Applying twice gives the same game, and
nothing you applied can be lost: to change it, edit the plan and apply again.

**Empty maps** keep the level's terrain (shape, paint and baked light), sky,
lighting, rain or snow, ambient sound, navmesh and player start. They drop the
buildings, props, guards, pickups, vehicles, cutscenes and objectives. The
terrain holes that bunkers need (`DiscardTerrain`) go too, or the map would
have holes into nothing. Empty maps are grouped by look: hills and grassland,
mountains, snow, night, sunset. Level 14 is underground, so it has no empty
map. All 13 empty maps compile.

**Game slots:**

- **Creating a slot:** on its first Apply, a mission gets the slot after the
  last one in the game (`level15`, `level16`, …; with 16 there, 17). The slot
  is a copy of the base level's folder, about 250–300 MB. Its `mission.qvm`
  names it in the game's mission list with your name and description, and its
  cover is the base mission's. If that first Apply fails, the new slot is taken
  out again, so the game never lists a bare copy of the base level.
- **In the game:** the library's first list is every mission the game holds
  past its fourteen, in the order it plays them, whoever made it. ↑ ↓ move the
  studio's own (with the game closed): the folder, its definition, its strings
  (`MS<slot>_*` in its script and the language files), its marker and its
  restore points all take the new number. One the game holds but no mission
  here does can be added (when its marker carries the whole mission) or taken
  out.
- **The chain:** the game lists missions by following each one's next mission
  from mission 1, so level 14 leads on to the first custom mission and each of
  the studio's missions to the next one in the game.
- **What the slot holds:** `_mission_studio.json` records the mission and the
  build, so the game folder alone can bring a mission back.
- **Removing:** **Remove from the game** moves the slot to
  `backups/slots/removed/` and takes its objective texts and map labels
  (`MS<slot>_*`) out of the language files.
- **Deleting:** **Delete** moves the mission to the trash, where the library
  can restore it, and optionally takes it out of the game.

**Protection:** every write into the game goes through `studio/protect.py`.

- **Refused:** the original install, levels 1–14, and the shared folders
  (`common`, `menusystem`, `language`).
- **Allowed:** only slots `level15` and up are written.
- **Deleting:** only a slot the studio created can be deleted.

The installer, the graph writer and the model importer all check this.

**Slots made before missions had a base:** `studio/build/migrate.py --slot N`
compares the slot with its base level and writes a mission whose plan rebuilds
it:

- **Added objects** become placements, and exact duplicates are dropped.
- **Moved objects and nodes** become edits.
- **Nodes you added** become plan nodes.
- **Patrol stops** on a building's interior nodes become that building's
  stops.

Mission 15 was recovered this way from its extracted data in git.

## The map

The plan looks like the in-game map computer, and that is its only look.

- **Ground:** the level's real terrain, lit from the north-west, with ridge and
  gully shading, rock strata on steep slopes, and contours (see *Terrain*).
- **Roads, railways, fence runs and power lines** are splines in the level:
  a `SplineObj` whose `SplineObjWaypoint`s each name the model laid from it to
  the next (a road, railroad track on its embankment, the train bridge, a
  fence, a wire). They are drawn along the curve through the waypoints
  (straight where the spline has linear segments), as wide as that model is
  across: roads grey with a centre line, railway with its rails once you zoom
  in, fences and wires as lines with their posts. An empty map has none of
  them (it keeps only the terrain).
- **A narrow map:** the tools across the top stay on one row. What doesn't fit
  folds into a **⋯** menu at the end of its bar (the show-on-map layers first,
  then the view tools), each with its name and a ✓ when shown; the menu stays
  open while you flip layers in it. A wider window brings them back.
- **Buildings, towers, containers and other structures** are drawn from the
  model itself: `studio/extract/meshes.py` extracts the render mesh of all 1328
  structure models in the game (the collision mesh for the few that have
  none), and `meshes.js` renders each one from above, lit and with its edges
  traced, at its true size and heading. A radar dome reads as a dome, a water
  tower as a tank on legs.
- **Models built from parts** are assembled first. A model's `ATTA` chunk lists
  the parts it is made of — a 16-byte model name, a position and a 3×3 matrix,
  68 bytes each — and the engine hangs them off the model when it draws it.
  228 of the game's models are built that way, some of them only a stub on
  their own: level 14's nuclear coolant system is 84 faces by itself and 7,108
  with its parts, which is why it used to read as an empty square with a name.
- **Cameras and alarm fittings are drawn over buildings**, not under them:
  they are bolted to the walls and roofs they would otherwise hide beneath.
- **Vehicles, aircraft, trains, crates, barrels and every other solid prop**
  (anything you can't walk into) are drawn from their model too, in a darker
  green with a soft dark halo. That way a truck stands out in a yard and a
  plane stands out under a hangar roof. Flat things such as runways stay light.
- **Trees, bushes, lights, poles, computers and switches** are symbols drawn
  at the object's real size and heading.
- **Security cameras** are red camera symbols pointing where they look. Zoomed
  in, each one shows its view cone, and dashed, the whole arc it sweeps
  (see *Security cameras*).
- **Guards** are red triangles pointing the way they face (yours are yellow),
  marked for snipers, gunners and characters. **The player start** is a
  green triangle; select it and drag to move where the mission begins (it
  keeps the 0.94 m hip height the game's own starts stand at). **Pickups** show what they are: rifle, sniper rifle, SMG,
  shotgun, pistol, launcher, grenade, mine, medipack, ammo, binoculars.
- **Zooming** plays the map computer's transition: a quick "CONNECTING" bar
  and a burst of static.

**3D preview:** selecting a building, prop or vehicle shows its model turning in
the side panel, with its size. Drag to turn it, use the wheel to zoom, and
double-click to set it spinning again. The expand button in its corner opens
a large view at the same angle (Esc closes it). Hovering a structure in the
inventory shows the same view beside the panel.

**Hovering the map** shows a card by the cursor: the model in 3D (when it has
one), a tag (enemy, camera, building, vehicle, pickup, yours), a line on what
it is, and the facts that matter:

- **Guards:** type, weapon, model, graph, and how far they see.
- **Cameras:** view, tilt, height, and when the camera is on.
- **Structures:** kind, size and model.
- **Every shipped object:** its task and id, and whether this mission edits
  it.

The card stays out of the way while you place, drag, measure or pick a
target.

**See-through buildings:** a building goes see-through while the cursor is
over it or it is selected. It keeps a dashed outline and is drawn under what
stands inside, so a plane in a hangar or crates in a warehouse show. The
X-ray toggle in the toolbar does this for every building at once.

**The cursor** says what is under it: the crosshair over open ground, a hand
over anything on the plan you can pick up or open, and the usual pointer
everywhere in the panels (the crosshair used to leak onto every small canvas,
including the icons).

**Tooltips and dropdowns** are the studio's own, not the browser's: a title
anywhere becomes a themed tip (the part before an em dash reads as its
heading), and every `<select>` gets a listbox in the same green while the real
element stays underneath, so every handler still works. New panels are picked
up as they are built, so this holds everywhere in the editor.

**Legend** (top right) lists only what is on the current map, with counts.
Hovering shows the first few rows, and a click opens the whole list.

The buttons beside it are for moving around: jump to the player start
(**H**), fit the yard (**F**), fit everything (**0**), zoom to the selection
(**Z**), step through your changes (**J**), measure a distance (**M**: click
two points to get the distance, height difference and slope), and save the
view as a PNG.

## Sight lines

The **Sight lines** button (the eye, top right) opens two views:

- **The selected guard or camera:** its field of view in yellow, over the
  ground it can actually see. It follows a patrolling guard as he walks. It
  is on by default, so selecting a guard is enough to see it.
- **What all guards and cameras see:** a pale wash over watched ground,
  brighter where several watchers overlap, and **red stripes on walkable
  ground nobody sees**. Walkable means within 4 m of a navigation node on
  the ground. The panel also gives the watched share: level 3 as shipped has
  92% of its walkable ground watched by 53 guards and cameras.

How it is worked out:

- An obstacle grid (1 m) is built from the terrain and the top of every
  structure's mesh. Masonry walls are included; wire fences, trees and lamps
  are not.
- Rays fan out every 0.2–0.5° across the field of view, from 1.7 m above a
  guard's feet (just under a camera's mount).
- A spot counts as seen when nothing along the ray rises above the line to a
  player standing there. You can switch that player to crouching or lying.
- Anything up to 1.2 m above the ground (an apron, a runway, a platform) is
  somewhere you can stand. Anything higher blocks the view, and nobody
  stands on it.
- A guard inside a building sees out as if through its windows.
- Patrolling guards are sampled along their route, looking the way they walk.

Field of view and range can be set per kind: guards 120° / 70 m and snipers
80° / 140 m. These defaults are estimates, **to be tuned in game**. Cameras
use their own settings: a sweeping camera counts the whole arc it covers.

**Routes** (the same panel, *Find the routes*): the quietest way on foot from
the player's start to each objective, drawn on the map, green where nobody
watches and red where someone does, with its length and how much of it is in
view, and a word for the whole mission (*quiet*, *watched in places*, *watched
most of the way*).

- The walk grid is the terrain's own cells: not steeper than 40°, nothing
  built over it higher than a step, no wire or electric fence across it. A
  climbable fence and a gate are ways through; so is a building, slowly,
  since the grid does not know its doors (the route says *through a
  building*).
- The search weighs watched ground up to 16 times (with *What all guards and
  cameras see* on); a route to a guard aims at where he starts.
- **Playability:** the check list before Apply warns about an objective with
  no way there on foot. It is an estimate: the player can climb and jump
  where the grid cannot.

**Any guard**, yours or the level's, can have his own sight: the **Sight**
box in his panel has a slider for how far he *Sees* (10 to 200 m) and one
for how wide his *View* is (20 to 360°). They start at his type's own, and
*Back to his type* clears them. The build writes them into his script as the
shipped scripts do (`AIFunction_SetViewLength`, `AIFunction_SetViewGamma` in
its `AIEVENT_CREATE` handler), and the sight cones and coverage use them.

- **Your guard:** into the script the build writes for him.
- **The level's guard:** his own script from the level, with just these two
  lines set; nothing else of his behaviour changes. When you take them off
  again, the next Apply puts the level's script back.

How well he aims and how quickly he reacts come from his **type**: the game
keeps one table per type and difficulty (`common/ai/settings.qsc`), shared by
every mission, so it is not changed per mission.

## Security cameras

Levels 1, 3, 5–9, 11, 13 and 14 ship cameras (`SCamera`). They show on the map
with their view cones, and the **Security** section of the inventory places
new ones: **sweeping** (±45° at 20°/s, 3 s pause) or **fixed**.

- **Mounting:** click near a wall, a masonry fence or the edge of a building.
  The camera snaps onto it within 4 m, facing away from it, about 4.5 m up (or
  lower, just under the top of a short wall). It goes on a **real wall of the
  model**, not on its bounding box: `meshes.js` keeps every upright face of
  every model with the height it covers, so a camera on the radar building
  lands on its base wall instead of hanging in the air under the dome that
  overhangs it. Trees, lamps and poles are not mounts. The ghost says what it
  will hang on and how high. **R** turns it from there. Dragging a placed
  camera keeps it on a wall. With nothing within 4 m, it stands on its own,
  3 m up.
- **Settings** (in the side panel, for shipped cameras too): tilt, view width,
  range, sweep right and left, speed and pause. **Mount on the nearest wall**
  snaps it again.
- **The alarm:** a camera that sees you only raises the alarm if the level
  listens. Each new camera (unless you untick **Raises the alarm**) is added
  to the level's own alarm wiring:
  - **Camera control:** if the nearest cameras belong to one
    (`SCameraControl`), the new camera joins it. It then also goes dark when
    that system is hacked or its generator is blown.
  - **Alarm:** otherwise it joins the nearest alarm (`AlarmControl`).
  - **No alarm:** a level without any gets a camera alarm of its own.

  A new camera also copies the *on while* condition of the level's nearest
  camera.
- **Removing a shipped camera** replaces every mention of it in the level's
  expressions with `FALSE`, so the alarm wiring still compiles.
- **Objectives:** *Destroy something* can target your own cameras as well as
  shipped ones.
- **Models:** all cameras use `313_01_1` (holder), `313_02_1` (camera) and
  `313_03_1` (wreck). A level that doesn't pack them gets them copied in on
  Apply.

Facing is taken as the guards' convention (heading 0 looks north), and the
sweep direction as right = clockwise. Both are **to be confirmed in game**.

## Alarm systems

The **Security** tab (left edge) is where the alarms live. An alarm system in
this game is one `AlarmControl` task and everything that names it by task id —
there is no area anywhere in the data, so **a system's area is its membership**.
Level 3 divides its base into two systems that way, 70 and 80.

Each system reads as a sentence, with four groups under it you can click
through:

- **Raised by** — the cameras and alarm buttons in its trigger expression
  (`SCamera_N.isDetection`, `Switch_N.isLastPressed`), directly or through the
  level's `SCameraControl`. Some levels also let guards raise it by sight.
- **Answered by** — the guards whose own AI script carries
  `SetAlarmControlID(N)`. The studio reads that out of every shipped script, so
  the level's own guards show up here too.
- **When it goes off** — sirens, flashing lights, the alarm heard around the
  base, reinforcements, and whether the mission fails.
- **Turning it off** — its buttons: pressing one while the alarm rings silences
  it, which is how the game's own do it (an `EditVariable` holds the alarm on
  between the two presses).

What you can place, from the Security tab itself — a highlighted **New alarm
system** button with a row of tools under it:

| Part | What it does | Task |
|---|---|---|
| Security camera | sees, and raises its alarm | `SCamera` |
| Alarm button | raises its alarm, and silences it | `Switch` (`234_01_1`, the button every shipped alarm uses) |
| Siren | wails while its alarm rings | `Siren` (`310_01_1`) |
| Alarm light | flashes while its alarm rings | `AlarmLight` (`344_03_1` / `344_01_1`) |
| Alarm system | a system of your own, for a corner the level never alarmed | `AlarmControl` + its `EditVariable` |

Every part's panel has one line: which system it is on, defaulting to the
nearest. Buttons, sirens and lights mount on walls the way cameras do, at their
own heights (a button at hand height, a siren high up).

A guard's panel has the same line — **Answers alarm** — and a tick that makes
him a **reinforcement**: he is not on the map until that alarm rings, and comes
back as many times as you say. That is the game's own `GuardGenerator` with the
alarm as its expression, which is how levels 5 and 8 call in their squads.

When the mission is applied:

- The mission's cameras and buttons are added to their system's trigger, under
  the same `!AlarmControl_N.isAlarm` guard the level uses, and its buttons are
  added to the `EditVariable` that holds the alarm on, so they switch it off
  again.
- A system of your own is written whole: the control (with its hack time), the
  `EditVariable` that remembers it, and the trigger built from its parts.
- Guards on a system get `SetAlarmControlID` for it, plus the alarm path out of
  their building the studio already gives them.
- `310_*` and `344_*` are copied into the slot when the level does not ship
  them.

The tab holds its own tools — a highlighted **New alarm system** and a row per
part, each with what it is and what it does — and the systems under them take
the rest of the panel, each one folding away, with their own scrollbar.

Each part shows as an icon in its group. Clicking it flies to the thing on the
map; hovering it raises a strip of four — show, select, take it off this alarm,
remove it from the mission — each with its own tip, and for the level's own
parts as well as yours. Selecting a system draws it on the plan: a line from every
part to its control, and a ring around each guard who answers.

Cameras the level ships can be re-mounted (**Mount on the nearest wall**) and
moved to another system just like your own; Apply takes such a camera out of
every trigger it was in and adds it to the one you chose.

**To be confirmed in game:** that a mission's own control behaves like the
level's, and that guards answer one they were not born with.

## Live view

The **LIVE** button (top right, radio waves) shows where you are in the running
game. Everything happens in the editor: there is nothing to install or click
in the game.

1. Open the editor from `python -m studio`. The live view needs the
   local server.
2. In the game, start the mission and don't move from the start.
3. In the editor, click **LIVE**, then **Connect at the start**, and walk a
   few steps in the game.

The plan then shows a bright **YOU** triangle facing the way you are walking,
with a trail. **Follow** keeps it centred. **Place … where I stand** drops
whatever you picked in the inventory at your feet. If you have already
walked away from the start, enter the three numbers from the F11 overlay
instead.

How it finds you: the server (`studio/server/live_pos.py`, read-only access to
`IGI.exe`) looks for every place in the game's memory that holds the level's
start position, as float, double or 32-bit integer, in game units or ×4096.
Then it keeps the one that moves when you walk and stays inside the level.
The scan asks `bytes.find` for the two top bytes such a number can have, so
it takes well under a second. It was tested against a stand-in process with
decoys. Whether the real game stores the position this way is still
**to be confirmed in game**.

**Runs:** while the live view follows you in an open mission, your way
through it is recorded (a point every 0.4 m, with the time) and saved to the
mission's `runs/` folder now and then and when you disconnect (*Record this
run* turns it off). The live panel lists the runs, connected or not: *Play*
draws the path as it went, amber, and **red where guards or cameras would
see you** (with *What all guards and cameras see* on); the slider scrubs
through it. Runs are yours, not the project's: `missions/custom/*/runs/` is
not committed.

## Side panels

Two tabs on the left edge switch the side panel: **Inventory** and
**Navigation**. Clicking the open tab hides the panel and gives the map the
room.

**Navigation** holds **Add node**, show/hide all nodes, the shipped patrol
routes, and every graph with how full it is (click a graph to hide it, ⌖ to
zoom to it).

**Every side panel can be made wider or narrower:** drag its inner edge (the
line lights up under the pointer); double-click the edge for the usual width.
The left panels share one width, Selection and the AI designer each keep
their own, all remembered by the browser.

The right edge has tabs too: **Selection** (below) and the **AI designer**
(see *AI designer*), which takes the right panel's place while it is open.

**The right panel** has two parts:

- **Selection:** the selected object's name and tag, 3D preview, details,
  position, rotation buttons and settings. Its actions (drop onto the ground,
  undo changes, remove) sit together at the bottom.
- **Change log:** docked underneath. It lists every change that is **not in
  the game yet**, grouped and colour-coded: **Added**, **Changed**,
  **Removed**, **Navigation**, **Objectives** and **Ground**.
  - **After Apply** the log starts again: what the game now has is part of
    the level (a note says how many changes are in the game, and when they
    were applied), and your things that are in the game are drawn like the
    level's own instead of in gold. Something changed or taken out since
    shows up again, as *changed since the last Apply* or *taken out*. The
    header says *up to date*, or how many changes there are to apply. The
    server keeps the applied plan in `mission.json` (`applied`); the plan
    itself still holds everything, since every build starts from the shipped
    level.
  - **Rows:** each row gives the full name and what changed, with where.
    Clicking a row selects the change and flies there. The button at the
    end of a row undoes that change: put back a removed object, reset an
    edited one, move a node back, or remove something you added.
  - **Folding:** each group folds, and so does the whole log.

## Inventory

The inventory has three sections. Each one takes a share of the panel's
height and scrolls on its own, and each one collapses, as does every group
inside them (Alt+click a group heading to fold or unfold all of them):

- **Characters**: all 28 AI types used in any mission, with the models and
  weapons they're seen with: the enemies, then the story characters (Ekk,
  Priboi, Anya) and civilians.
- **Weapons & items**: 19 weapons, explosives and items, plus 13 ammo types.
  These are global, so they work on any level.
- **Structures & objects**: 291 models in 16 categories (fences & walls,
  security & military, towers, industrial, underground, vehicles, furniture…).
  The section lists the categories, one row each with a picture, how many
  there are and how many the level packs. **Hovering a row opens its list
  beside the panel** (it closes when the pointer leaves both); **clicking the
  row, or Pin, keeps it open**. The list has its own filter, each entry its
  top-down render and 3D hover card, and picking one closes an unpinned list
  so the map is free. Esc closes it. Typing in the inventory search lists the
  matches in the panel instead, grouped by category.
- **Yours:** designs the AI designer made and you kept are here too: *Your
  designs* as the first category of Structures & objects, *Your characters*
  at the end of Characters. They place like a saved group (R turns them).

Nothing is restricted by level. A model the level doesn't pack is marked
*import*; on Apply it is copied in, together with its LOD variants and textures
(see below). **R** / **Shift+R** rotates the selection by 15°.

The icons above the map show and hide layers: terrain, buildable ground
(**B**), grid, buildings, props and vehicles, fences and walls, doors,
pickups, shipped guards, cutscene actors, map labels (**L**), all navigation
nodes (**N**), and shipped patrol routes. They also control the patrol
animation: play/pause, speed, and back to start positions.

## The mission's own textures

Select anything with a model and open **Textures** in its panel: the pictures
that model is drawn with, as the game has them. **Replace** takes a PNG of
yours (up to 2048 × 2048, 8 bits a channel) and that texture becomes the
mission's own; **Back** returns the level's.

- The picture is kept with the mission, like every other change: undo works,
  and nothing is written to the game until you Apply.
- Apply writes it into the mission's own slot in the game's format (16 bits a
  pixel as most of the game's own are, or 32 where the one it replaces is,
  with its mipmaps). The name, order and place of every texture in the level's
  archive stay as they were, so the model palette, the `.dat` and the `.mtp`
  are untouched.
- Because Apply always builds from the untouched base, a picture you take off
  again comes back as the level's own, byte for byte, on the next Apply.
- It changes that texture wherever the level uses it, not only on the thing you
  had selected: the level's models share their textures.
- The format is written down in `studio/build/textures.py`, which can also
  convert either way from the command line and check itself against every
  texture in the game (`python -m studio.build.textures check`).

## Placing things

When you pick an item, a see-through preview of it follows the cursor at true
size and rotation. A bar at the bottom shows the item's angle and rotate
buttons.

- **R / Shift+R** rotate by 15°, **T** by 90°. The angle carries over to the
  next item you place.
- **Fences and walls chain:** each click adds a panel that starts where the last
  one ended and points at the cursor, in 15° steps (hold **Alt** for any angle).
  A new run snaps onto the end of a fence nearby. **C** starts a new run.

## Terrain

The map shows the level's real ground: shaded relief with a contour line
every 5 m (darker every 25 m). The readout at the bottom left gives the
ground height and slope under the cursor. **Terrain relief** in the layers
bar turns it off.

**Ground textures** (on by default, toolbar): the relief is shaded with what
the ground is made of: fields, dirt tracks, rock, snow.
`studio/extract/ground.py` reads it from the level's own texture masks:

- `terrain/terrain.tex` holds the level's textures: 18 or 12 of them at
  512×512, 3 per material.
- `terrain/terrain.bit` holds masks of 1 bit per cell, 4–16 m on the ground,
  least significant bit first from the south-west corner.
- Each `TextureModifier` task paints a material through one mask. Later tasks
  paint over earlier ones, and unpainted ground is material 0.
- The mask orientation was checked on level 3: the cells painted "rock
  around base" are on average 11.8° steeper than the rest.

For each level the result is a material per terrain cell and a grey tile of
each material's first texture, 0.5 MB for all levels. Not decoded yet: which
of a material's three textures the game shows where, and at what scale (the
editor repeats a tile every 16 m).

`studio/extract/terrain.py` samples every level once, at 1 m spacing, with the
same exact height query Apply uses (`studio/build/terrain.py`). The grid covers
where the level is played: its buildings, guards, pickups and navmesh, plus
150 m, and at most 2 km across. The editor's heights agree with the server's
to within 5 mm. Level 14 is underground and has no terrain, so there the
editor falls back to the navmesh.

**Buildable ground:** with a building in hand, the map is tinted for that
building's size. At each point, the tint shows how much the ground varies
over a square as wide as the building, the same rule as the placement check:

- **no tint:** less than 1 m
- **yellow:** 1–3 m (the building sinks into the slope)
- **red:** more than 3 m (too steep)

**B** shows the same tint for a 12 m building without one in hand.

The preview says whether the building can stand where it is:

| Preview | When | Click |
|---|---|---|
| Green, "level ground" | The ground under its footprint varies less than 1 m | Places it |
| Amber, "uneven" | 1–3 m | Places it; the building sinks into the slope by that much |
| Red, "too steep" | More than 3 m | Refused |
| Red, "overlaps …" | Its footprint runs into a building or prop 1.5 m or taller | Refused |
| Red, "outside the mapped ground" | Under 70% of its footprint is on the sampled terrain | Refused |

**Alt+click** places a refused building anyway. Fences only warn, when the
ground drops more than 3 m along them.

## Level ground for new buildings

A building you place gets the ground under it levelled when the mission is
built. The level designers did the same, with height maps:

- A `HeightMap` task lays one item of `terrain/terrain.hmp` over an octree
  cube of the terrain, and moves its vertices up or down by
  `(value − 64) / 16` m, bilinear between samples. **A cube keeps the map
  the game loaded first**: a second `HeightMap` for a cube that already has
  one is ignored.
- `studio/build/flatten.py` patches each 64 m cube (129 × 129 samples, 0.5 m
  apart) that the building and its apron touch. A cube the level already
  maps is rewritten **in place** (same bitmap id, size and task), starting
  from its own values; only a cube with no map gets a new item and task.
- The footprint plus a 1.5 m apron is set to the median ground height under
  the building (the least cutting and filling). Over the next 4 m the ground
  eases back to what it was.
- New tasks go after the level's own, and the slot's `terrain.hmp` is
  rebuilt from the base level on every Apply, so removing a building removes
  its pad.
- The building is set on the levelled ground. Guards and pickups placed
  after it see the new ground too, because the patches are registered with
  the height query first.

Where it applies:

- **On by default** for real buildings (at least 2.5 m tall and 2 × 2 m, not
  walls). **Level the ground under it** in the building's panel switches it
  off. A dashed apron on the map marks a levelled pad.
- **Steep ground:** a height map moves the ground about 4 m either way;
  where a pad needs more, the terrain mesh under it is rebuilt (see *Shaping
  the ground*), so the placement check allows up to 20 m of slope for these
  buildings.
- **Levels without height maps** (2, 4, 5, 7, 11–14) get a `terrain.hmp`
  holding only the new patches.

Checked so far: the levelled height under a 19 × 11 m bunker on a 6 m slope
varies by 16 cm, ground outside the pads doesn't change, an existing height
map in the same cube is kept, and the scripts compile. **To be confirmed in
game:** that the ground renders and collides at the new height, how the
baked terrain lighting looks on a pad, and whether levels that shipped
without a `terrain.hmp` read the new one.

## Shaping the ground

The **Ground bar** on the map's right edge, under the view buttons, holds its
tools; each opens its panel right beside the bar (the legend opens over it):

| Tool | What it does | How |
|---|---|---|
| **Level** | flattens an area at one height (the middle height under it, or one you type) | drag a rectangle, or click for a 12 m patch |
| **Raise** / **Lower** | lifts or sinks an area by so many metres | drag; *Round* for an ellipse |
| **Smooth** | evens out bumps, keeping the lie of the land (*Strength*: how wide a bump) | drag |
| **Ramp** | an even slope between two heights (*From* / *To*, *Width*) | drag from the bottom of the slope to the top |
| **Remove** | takes a hill or a mountain away: the level's ground round its edge (48 points on the ellipse through it) drawn in across it, each weighed by the inverse square of its distance | drag round it. A mountain in a range, with high ground round it, wants *Level* to a height instead |
| **Brush** | paints the ground freehand (below) | hold the button and drag |

**The brush** has two rows. *Raise*, *Lower*, *Smooth*, *Flatten* (to the
height where the stroke began), *Roughen* and *Erase*, with a *Size* (radius,
up to 600 m), a *Strength* and an *Edge* (soft, even or hard). Up to 10 m wide
it paints the fine layer, 1 m cells; wider, the terrain's own 4 m grid.
Then the **shapes**, stamped into the 4 m grid: *Mountains* (a click puts one
down, a drag a range of them), *Hills*, *Plateau*, *Crater* and *Valley*
(carved along the stroke). Each comes in *Small*, *Mid* and *High* (radius and
height, typed over at will) with a *Rough* for how craggy, and comes out
different every time: ridged value noise, a footprint that wanders, the
stroke's own seed. Overlapping mountains keep the higher of the two, so a
range does not pile up.

- **The panel** has what the next area or stroke will be at the top, and
  every shaped area below it as a card: *Go there*, *See it in 3D* and
  *Remove it* on each, and a click opens its settings in the card. The fine
  strokes and the big shapes have a card each. Only the area open in the
  panel (or under the pointer there) is drawn on the map, so the ground stays
  readable; the brush's layers show as a green (raised) or blue (lowered)
  wash while the Brush is open.
- **Areas** can be dragged to move them, and have *Size*, *Turn* (rotation),
  *Shape* and *Edge*. The edge is automatic: about 2.5 m of run for every
  metre of height, up to 150 m, eased with a smootherstep and wandering a
  little (value noise, the same in the editor and the build), so an area
  reads as ground, not as a drawn shape. Type an edge to fix it; clear the box
  for automatic.
- **In order:** the big shapes first, then the areas, each on the ground the
  ones before it left, then the fine brush, then the pads of your buildings.
  The relief, contours, buildable layer and every height the editor reads
  follow at once; while a stroke is painted the relief catches up when you
  let go.
- **Nothing is left floating.** The ground never changes under anything
  standing on it: buildings, walls, props, crates, vehicles and pickups keep
  the ground they stand on, eased in over a few metres round them. The panel
  (on the area's card) and the check list say what stands there, so you can
  move or remove it first if the ground there has to change. Carrying things
  up and down with the ground was tried and left crates half in the air and a
  button mounted on one hanging. Guards are not in it: they stand on the
  navmesh, and the nodes on shaped ground move with it. Nor is the player
  start: it is set down on the shaped ground by the build every time, so it is
  on the slope of a mountain put over it, and back on the ground when the
  mountain goes. Your own buildings level their ground with their own pad.
- Saved in the plan as `ground` (areas), `brush` (1 m cells, metres each) and
  `sculpt` (the 4 m grid, centimetres each), listed in the change log under
  *Ground*, and undone like everything else.
- **As high as you like.** On Apply, `studio/build/flatten.py` works out the
  ground wanted, on the level's own ground from the reference copy (never the
  slot's, which an earlier Apply shaped). Where it moves further than a
  height map can carry (about 4 m; `MESH_FROM` 3 m, smoothed over the 4 m
  round each grid point) the terrain mesh itself is rebuilt there
  (`studio/build/terrain_mesh.py`): its grid points moved, every cube over
  them built again at every level of detail, the rest of the level's terrain
  kept as it is and the new cubes meeting it exactly. The height maps then
  carry what is left, against the new mesh. A 30 m raise came out within 3 cm
  on its top and 0 outside; the finest points follow to the height step of
  their level (a point every 128 m and more can be a few metres off, spread as
  a tilt; the build says when).
- **The terrain budget:** the game holds 32,767 terrain nodes and the level's
  own use 11,000–15,000. Every Apply's dry run says how many the plan needs:
  the *Terrain* bar at the top of the panel, a warning in the check list past
  90 %, and an error (and no Apply) past the limit. Flat ground is cheap - the
  same flat cube is written once - and steep new ground is not.
- **The light:** the level's baked terrain light is redone over rebuilt ground
  (`studio/build/lightmaps.py`): the direction of the level's light worked out
  from its own light maps against the lie of its land, and each light map
  pixel over changed ground made brighter or darker by how the change turned
  the ground to it. A level whose light does not follow the land (night and
  rain levels) keeps its light maps as they are.

## Painting the ground

**Paint** (the last tool on the Ground bar) changes what the ground is made
of: pick one of the level's own materials (named from the level's own
painting where it names them: grass, dirt, rock), set the size and drag over
the map; *Erase* takes paint off. The painted squares show while the tool is
open, and whenever *Ground textures* is on; the panel has a *Painted ground*
card and the change log a row.

**Hovering a material** shows what that ground looks like: a stretch of it
seen from standing height, in the level's own texture for it (read from the
level's `terrain.tex` in the untouched install by the studio server,
`api/groundtex`, cached in `cache/ground/`). Only the materials the level
has are offered: a level with no snow on it has no snow to paint.

- The game paints its ground per octree cube, wherever a bit of the cube's
  mask is set (`TextureModifier` and `terrain/terrain.bit`, worked out in
  `studio/extract/ground.py`). Apply writes one 64 x 64 mask per 64 m cube and
  material (1 m a bit) into the slot's own copy of `terrain.bit`, and a
  `TextureModifier` for each after the level's own, which it paints over.
  Removing the paint puts the level's own `terrain.bit` back.
- The material names come from `ground/levelN.json` in the level data (`names`,
  rebuilt by `studio/extract/ground.py`); a level that names none shows
  *Ground 1*, *Ground 2* and so on, with their colours.
- **To be confirmed in game:** that a painted square shows the material, and
  how it blends at the edges.

## Seeing it in 3D

**View and place in 3D** on the selection panel (or **V**, or the right-click
menu) opens a close-up of the selected item over the map: the real geometry
within 10, 20 (the default), 40 or 60 m of it, drawn with the game's own
textures. The ground reaches well past that and fades into the haze, so the
view never ends at a cliff.

- **What is in it:** the ground (with the mission's shaping, coloured by its
  material), every building, wall, fence, prop, vehicle, crate and desk, the
  guards and the player start as their character models, pickups as their
  weapon and item models, cameras with their view cone. The level's things
  are as the game draws them; yours are tinted gold, the one being edited
  outlined. **Textures** off shows plain colours instead.
- **Looking around:** a free camera, like a spectator in a shooter. Drag to
  turn your head (the camera stays where it is, the world does not move),
  right-drag to circle round the item, the wheel steps forward and back
  where you look. **Around**, **Top** (T), **Eye level** and, for a camera,
  **Camera view** (its own lens, heading, tilt and field of view) jump to a
  ready view.
- **Flying:** **W A S D** or the arrow keys fly where you look while held
  (11 m/s, **Shift** 32 m/s), **Q** / **E** go straight down and up. Inside
  a building it is the same: you fly through the rooms, nothing moves.
- **Walk** (or **G**): you land on the floor under the camera and walk at
  eye height (1.7 m) with **W A S D** where you look, **Shift** runs. Floors,
  stairs, slopes and roofs are followed (a step up to 0.55 m is climbed, a
  drop is fallen down); a wall, a crate or a fence in the way stops you, and
  you slide along it. Another view (or G) flies again.
- **Ramps and sunken yards are open:** the level's terrain runs flat across
  the ramp down to a bunker's doors (3.4 m over the ammunition store's on
  level 3), where the game draws no ground. The close-up leaves the ground
  out wherever a building standing on the ground is open to the sky below
  ground level (its highest floor or roof there more than 0.3 m under the
  ground), so the ramp shows and can be walked down; roofed rooms keep their
  ground, and rooms deep underground are not affected.
- **It goes where you go:** the close-up is gathered round the camera, not
  just round the item it opened on. Fly or walk anywhere and, every few
  metres, what stands near you, the ground under you and the walkways are
  gathered again: what came into reach is drawn, what fell out of it goes,
  and what is still near stays as it is. Things are drawn as far as the
  ground reaches (about 55 m at 20 m, 135 m at 60 m, fading into the haze),
  so you can cross the whole level from any item. Once you leave the item's
  surroundings, a **cut** set for its room switches off, the sun's shadows
  follow you and the readout says where you are (*you* x, y, z, and the
  ground under you). The item you opened stays drawn wherever you go.
- **Walkways:** the guards' navmesh round the item, its points as small posts
  and its links as lines (the level's in cyan, yours in gold), and a selected
  guard's patrol as a gold line over them. **Add walkway point** puts one
  where you click a floor, an upper floor of a building as easily as the
  ground; it joins the graph with a point on that floor within 15 m, as on
  the map.
- **Inside buildings:** the close-up looks straight up from the item and
  **cuts** everything above the first ceiling, so the room is open from
  above (the slider moves the cut). **X-ray** makes other buildings
  see-through.
- **Moving the item:** drag it. A floor item (guard, pickup, crate, desk, any
  prop) slides over upward-facing surfaces - ground, floors, desk and crate
  tops - with its base on them; a wall item (camera, alarm button, siren,
  alarm light) slides along walls, turned to face out. A **building** moves
  only with **Alt+drag**, so a plain drag inside one always looks around. **Shift+drag** lifts or
  lowers it, **R** / **Shift+R** turns it 15° (Alt: 1°), **Ctrl+arrows**
  nudge it 5 cm (Shift 50 cm), Ctrl+PgUp/PgDn change its height. The readout says what it stands
  or hangs on and how far above or into it it is.
- **Placing:** with something picked in the inventory, a ghost of it follows
  the pointer over floors (or walls, for cameras and alarm parts) and a click
  puts it down right there.
- Click another item to edit it (or, if it can't be moved, to look at it).
  Every move is an ordinary edit: undo, the change log and saving all work,
  and the map shows the result.
- **Edit mode:** holding **Alt** frees the mouse for as long as you hold it;
  the **Edit** button at the top does the same until you press it again (it
  reads *Camera* while it is on, and Esc leaves it). With the mouse free,
  click to select, drag to move.
- **Delete** takes the selected item away, **Ctrl+C** copies it and **Ctrl+V**
  puts a copy where the view is aimed (the crosshair, on the ground or a
  floor); **Ctrl+D** leaves a copy there too. Undo works as everywhere else.
- **The close-up stays open** when the thing it was on is taken away - here,
  in the side panel or by an undo. It keeps looking at the place it stood.
- **It follows the rest of the editor:** turning or moving something in the
  side panel (the 15° and 90° buttons, or *Facing* in degrees), undo, and
  whatever rests on a moved crate all show in the open close-up straight
  away, from where you are looking.
- **Every heading turns the same way:** a larger heading is further
  anticlockwise, R turns anticlockwise, on the map and in 3D alike. A weapon
  lying on its side keeps its heading in the first angle (alpha), which turns
  the other way, so the build writes minus the heading there. Plans saved
  before this (2026-09-18) are converted once when they load (`ccwLying`),
  and every weapon keeps the pose it has in the game.
- **Heights set in 3D are kept:** such items carry `exact`, and Apply puts
  them where they were put instead of snapping them to the navmesh or the
  pickup rules. Moving one on the map again drops the flag. Guards still
  stand on the navmesh in the game, whatever their height.
- **Heights as the game will have them:** a moment after each change the
  server runs the build without installing anything (a dry run into
  `missions/plan-heights/`, which writes `heights.json`) and the editor takes
  over the heights it would give your things: a crate the build sets down on
  the ground is shown on the ground, not half in it. It takes a few seconds
  (about 15 on a mission with a lot of shaped ground) and is cached until the
  plan changes. It is not an undo step.
- **What rests on something goes with it:** a rifle on a crate, a crate on a
  crate, an alarm button on a crate's side, whatever stands in a building.
  When you move the thing below (on the map, in the panel or in 3D), or the
  build's heights set it lower or higher, what rests on it moves the same
  amount. Your alarm buttons are drawn as the game's alarm button
  (`234_01_1`), the model the build writes for them.

**Characters stand at ease**, as the game's own first animation has them
(standing with a rifle), not in the A-pose they are modelled in. The
skeleton files (`common/anims/NNN.iff`) hold, after the bones, every
animation (FORM BOAN): per bone its rotation keys, 13 floats each (a
quaternion x, y, z, w, its time and two tangent quaternions); a bone turns
with its parent (`studio/extract/meshes.py` `posed`). Animation 0 stands with a
rifle, 1 runs, 2 walks, 3 to 5 aim, 6 and 7 kneel.

**Guards hold their own weapon**, in the 3D close-up, in the panel's preview
and on the inventory's hover card: the model the game shows for his weapon
(an AK-47, a Dragunov, a pistol) in his hands. Every human skeleton has a
bone for the gun (bone 22, a chain off the spine): in the aiming animations
it sits at the chest with no turn, the right hand on its grip and the left on
the fore-grip, so a weapon model (barrel along +y, its origin at the grip)
goes on it as it is. `studio/extract/meshes.py` writes where each character
holds it (`grips` in the level data's `meshes.json`). Change his weapon and the
gun in his hands changes with it.

The models come from the game files: `meshes.bin` in the level data (built by
`studio/extract/meshes.py`, now with the characters on their skeletons and the
weapons from the location's shared archive), and textured, on demand, from the
studio server (`api/model3d`, `api/texture`, `studio/extract/model3d.py`, decoded
textures cached in `cache/`). Without the server the close-up draws the
models plain.

## Keyboard

| Keys | Action |
|---|---|
| Arrows (Shift ×10, Alt ×0.2) | Move the selection 0.5 m |
| Ctrl+Arrows | Pan the map (arrows alone pan when nothing is selected) |
| `[` / `]` | Selection down / up one floor |
| Delete · Ctrl+D | Remove · duplicate (the whole group when several are selected) |
| Shift+drag · Shift+click · Ctrl+A | Select a group · add/drop one · all your changes |
| Ctrl+C · Ctrl+V | Copy the selection · paste it at the cursor, in any mission |
| G | Drop the selection onto the ground |
| P | Edit the selected guard's patrol |
| A · N · L · B | Add nodes · show all nodes · show labels · buildable ground |
| + / − · F · 0 | Zoom · fit yard · fit all |
| H · Z · J | Jump to the player start · zoom to the selection · next of your changes |
| M | Measure a distance (Esc stops) |
| Space | Play / pause patrols |
| Ctrl+Z · Ctrl+Y · Ctrl+S | Undo · redo · save |
| Esc · ? | Stop / deselect · list every shortcut |

## Ground height

Guards, pickups and objects are set down on what is really under them. This
happens **as you work**, not only on Apply. Placing, dragging, nudging with the
arrows, typing coordinates, **G** and duplicating all ask the local server
(`/api/ground`), which answers from the level's terrain and collision meshes,
with the mission's own changes counted. Opening a mission does the same for its
guards and pickups. Apply checks every guard again. Without the server, the
editor uses its terrain grid (see *Terrain*).

- **Buildings** rest on the **lowest** ground under their footprint, sampled
  every 1.5 m, so no corner hangs in the air. On a slope the uphill side sinks
  into the ground instead. Resting on the ground at the building's origin left
  a bunker on a hillside several metres up at its low end. Apply warns when the
  ground under a building varies more than 1.5 m.

- **Guards:** a guard's z is his feet. 66 shipped guards in levels 1–9 stand
  within 7 mm of the terrain, and the game leaves a guard placed in the air
  hanging there. The navmesh blend the editor used to start from put guards on
  a hillside 2–4 m up.
- **Dropped without a height:** a guard steps onto a kerb, apron or low
  platform (up to 0.6 m) but not onto a desk. A pickup lands on a desk, crate
  or bed (up to 2 m).
- **Inside a building with known floors:** that building's floor is used.

Where things rest:

- **Terrain:** exact, from the level's terrain files (`studio/build/terrain.py`, a
  port of the octree height query from project-igi-editor).
- **Built surfaces:** aprons, platforms and other shipped models' collision
  meshes (`studio/build/surface.py`).
- **Under a roof:** the floor you picked, because building floors aren't in
  the collision meshes (see *Inside buildings* below).
- **Items on furniture:** a pickup rests right on a desk, crate or bed top,
  as the shipped ones do (median +0.03 m over 52 of them). On open ground it
  sits +0.5 m up, like the shipped ground pickups.
- **Lying down:** weapons and items are turned onto their side the way the
  shipped ones are: orientation `alpha = heading, beta = 1.57`. With
  `0, 0, heading` a Dragunov stands on its end, half through the desk.
  Grenades and ammo boxes sit as they are, and mines lie with `alpha = 1.57`.
  Pickups placed by an earlier Apply are laid down on the next one.

Models rest on their lowest point, ignoring base plates under 10 cm.

Navigation nodes lie on the terrain to within 3 mm, but blending nearby nodes
lifted objects off bare ground next to concrete aprons. That was the "slightly
floating" problem.

**Mission ▾ → Tidy up** asks the local server which of your objects hover over
bare ground, and which you placed twice in the same spot. You pick which to fix,
and the fixes go into the plan like any other change.

## Objectives

The **Objectives** tab (left edge) sets what the player has to do, up to six
things, in order. The list starts as the base level's own objectives, and the
mission adds to it, reorders it or drops from it:

| Objective | Target | The game tests |
|---|---|---|
| From the level | one the base level ships | whatever the level tests |
| Eliminate a guard | any of your guards, or a shipped one with a task id | `HumanSoldier_N.isDead` |
| Eliminate every guard | all enemy guards | all of them `.isDead` |
| Collect a weapon or item | your pickup, or a shipped weapon or item with a task id | `GunPickup_N.isPickedUp` or standing on it, `GenericPickup_N.isPickedUp` |
| Reach an area | a point and radius on the map | a new `AreaActivate` box (`.nActive`) |
| Hack a terminal | a shipped terminal | `Terminal_N.isHacked` |
| Destroy something | a shipped vehicle, camera or explosive | `…_N.isExploded` |

- **The level's own:** the first time a mission is opened, the level's
  objectives go into the list in the order the map computer lists them (a
  level whose list changes as it goes, such as level 3, contributes each of
  its objectives once). They keep the level's own wording, which lives in the
  game's language files, and their own completion. Drop the ones the mission
  doesn't want; the plan remembers that.
- **Setting one up:** the ⊕ button picks the target on the map (an area for
  *Reach an area*), the eye shows it, and × removes it. Each objective of
  your own gets its own text; leave it empty for a sensible default.
- **Order:** drag a row by its header. The order is the order the map
  computer lists them in, and the numbers beside them follow it.
- **On the map:** targets show numbered yellow diamonds. A badge on a
  patrolling guard walks with him.
- **In the game's map computer:** each objective gets a numbered marker on the
  terrain view as well as its line in the list (see below).
- **Collecting a weapon:** the engine flags `GunPickup.isPickedUp` when the
  weapon goes into a free hand, and not when it only tops up the ammo of one
  the player already carries, so a *collect* objective on a weapon also counts
  the player standing on it — a 1.5 m `AreaActivate` box at the item. Taking it
  means walking into it either way. A `GenericPickup` (the C4, the keycards)
  needs no such help.
- **In the check list:** an objective with no target, or whose target was
  removed, is an error. A *collect* objective whose item lies more than 1.2 m
  above the ground is a warning with a fix: the player takes things by walking
  into them, so a weapon on top of a crate stack or on a roof can't be
  reached. (Nor does the game count a weapon the player already carries as
  picked up — for a collect objective, use something that is not in the
  mission's loadout.)

When the mission is applied, it is wired the way level 14 wires its own:

- The list goes into the level's **own** `DefineComputerObjective` task, in
  the mission's order — that task is the one the map computer shows, so a
  second task of ours would only compete with it. A level can carry several
  lists, each taking over when its "Objectives Valid" expression comes true;
  the others are switched off (`"0"`) and emptied, so nothing of the level's
  can come back over the mission's. A level that ships no list at all gets a
  new one.
- Each objective sends "Objective complete" when done. When all are done,
  "Mission complete" shows and `LevelFlow` completes the mission.
- **What ticks an objective off in the list:** the map computer reads each
  slot's complete expression at the moment you look at it, and some conditions
  only hold for an instant — `AreaActivate.nActive` is true while you stand in
  the area and false again when you walk out. So the slot's expression is the
  objective's own "Objective complete" message, `StatusMessage_N.isSendt`,
  which is sent once and stays sent (levels 6 and 10 do the same). The real
  condition is what sends that message.
- **The numbered markers** on the map computer's terrain view are separate
  `ComputerHilight` tasks carrying the sprite `COMPUTER:h_<n>.spr`, one per
  objective, numbered in the mission's order and shown while that objective is
  unfinished. An "eliminate every guard" objective has no one place, so it gets
  no marker.
- **A marker is drawn where the task it names stands**, not at its own
  position: level 1 puts all 17 of its hilights at one point and they show at
  their own buildings. The computer can only place the level's fixed objects
  this way — a marker naming a guard or a weapon on the ground draws nothing —
  so each marker (and the objective's "link to position") names the nearest
  thing it does know: a building, terminal, generic pickup, explosive, car,
  helicopter, generator, radio or switch. If the nearest one is a task the
  level left without an id, it is given one. The build log says what each
  objective ended up marked by and how far away that is.
- **The map computer holds 32 markers and labels, and no more.** A 33rd is the
  fatal `QTaskList is full` when the level loads. Level 8 ships exactly 32,
  level 3 ships 29. So a mission's markers are written **over** the level's own
  numbered ones first (they are the ones being replaced anyway), and only what
  is left over is added. If the budget still runs out, map labels are dropped
  first, with a warning; the check list says so before you apply.
- The mission fails on the base level's own failures, on the player's death,
  and on the alarm if **The mission fails if the alarm goes off** is ticked.

**Time limit and weather** (under the objectives, or the Mission menu):

- **Time limit:** minutes and seconds, and whether the countdown shows on
  screen. The countdown is the game's own (`LevelFlow`'s *Max level play
  time* and *Interface timer enabled*, as level 7 ships with 20 minutes), in
  the game's small timer font. The game's own limit only counts: at zero
  nothing happens. So the mission keeps its own clock too: a `LevelTimer`
  from the start, messages at 5 minutes, 1 minute and 10 seconds left (the
  ones the limit is long enough for), and at zero *Time is up*, after which
  the mission fails (`LevelFlow`'s *Failed* waits for that message, as an
  event's failure does).
- **Rain or snow:** as the level, clear, rain or snow, light to heavy. The
  level's `RainEffect` is rewritten (*Is Rain* false is snow), or one is added
  next to its sky when the level has none.
- **Haze:** how hazy the distance is, between the clearest level (5) and the
  haziest (3 and 9): `FlatSky`'s *Fog Amount* and *Distance*.
- The change log shows them as one row; *As the level* takes them all back.
- **To be confirmed in game:** rain or snow on a level that had none, and how
  the haze looks.

**Map computer labels:** the same tab names your own buildings on the map
computer, with a title and a line of info (`ComputerHilight`).

**Texts:** objective texts and labels are the game's text resources.
`studio/build/lang.py` writes them into every `language/<lang>/objectives.res`
and `messages.res` of the working game, under the mission's own prefix
`MS<slot>_`:

- Each Apply replaces that prefix's keys and touches no other key.
- The first write backs the files up to `backups/language/`.
- This is the one write the studio makes outside a mission slot, and
  `protect.py` allows only these two files of a working game.
- All 12 shipped language files rebuild byte-for-byte.

**To be confirmed in game:** that the objectives list, completion, failure
and labels behave as in the shipped levels, and the size of an
`AreaActivate` box (its dimensions are written as the radius).

## Events

The **Events** tab (left edge) is "when this happens, that happens". The
kinds of event are listed at the top of the tab; pick one to add it. Each
event is a card below: **When**, then what happens (**Then**). An event
happens once.

- **When:** the player reaches an area (a circle you click on the map), a
  switch is pressed, a guard dies, a terminal is hacked, an item is picked
  up, something is blown up, a camera sees the player, an alarm goes off, a
  number of seconds after the start, or some seconds after another event.
  The target is picked on the map, as for objectives (the level's own things
  need a task id the game can test).
- **Then:** show a message (your own words, for so many seconds), raise an
  alarm (the level's or one of yours), send in guards, or fail the mission
  (with your own words or the game's *Mission failed*).
- **Send in guards:** *Pick guards* and click your own guards. They are not
  on the map until the event happens, and come back as many times as their
  panel says (*Arrives* in the guard's Alarm section does the same from the
  guard's side).
- On the map, each event has a pink numbered badge on its area or on what it
  watches; the open card's guards are ringed.
- The change log has an **Events** group, and the check list warns about an
  event that can never happen (nothing picked, its target gone).

**Doors of your own.** A door model placed from the inventory is written as
the game's own doors are (a `Door` task), so it opens in the game: walk up to
it and the prompt comes. The numbers come from the game itself
(`studio/extract/doors.py` reads every `Door` task of all fourteen levels into
`data/doors.json`): how far that model slides and along which axis, its angles,
how long it takes, and its sounds. A door placed inside a building goes on the
floor there, not on the ground, so upper floors take doors too.

- **A building brings its doors and its lift.** Placing one of the game's
  buildings places the doors it has in the levels, in the same doorways, each
  one that opens (the Office has six, the Guard HQ twelve, the lift's own
  sliding doors on both floors included), and its lift where it has one. The
  doors of one real copy of that building are used, exactly as it was built,
  rather than an average of its copies, and a building's other skins (its snow
  or desert version) count as the same building. They are ordinary placements:
  take one out, or move it, and it stays where you put it; move, turn or settle
  the building and its own doors and lift go with it, in the editor and in the
  build.
- **Nothing of another level comes with them.** A door model's numbers are the
  game's own, but an expression naming a task by id (a lift door in level 12
  closes on `Switch_211`) means nothing in a mission of yours, so it is left
  out: a door of yours closes a few seconds after it opens, as the game's
  sliding doors do. Two of the same door in one doorway is dropped too; two
  leaves facing opposite ways are a double door, and both are kept.
- **Lifts.** A lift of yours is written as the game writes its own: an
  `Elevator` task on a `SplineObj` whose waypoints are the floors it stops at,
  with a call button at every floor and one inside the cabin. Six buildings
  bring one (both Guard HQs, the Winch House, and the lift shafts, one of which
  drops 27 m to the tunnels); the shafts are in the inventory on their own,
  under *Lift* and *Ekks HQLift*, to put a lift anywhere. It is free to run
  ("1" where the game's own wait for their doors to be shut), so a lift of
  yours is never stuck.
- **A lift's doors belong to the lift**, as the game has them: locked to the
  player, opening when the cabin reaches that floor (`Elevator_N.vFloor == k`)
  and shutting when any of its buttons is pressed. Which doors those are is not
  guessed - the game's own wiring says so, and that is kept with the door, so an
  ordinary door beside a shaft still opens by hand.
- **A shaft that runs below the ground opens the ground over it**
  (`DiscardTerrain`, as the game does where its own lifts go down), so the cabin
  is not stopped by the terrain. A lift between the floors of a building leaves
  the ground alone.
- **Everything inside comes too.** A building brings what stands in it in the
  levels - desks, filing cabinets, lamps, beds, crates, barrels (the Guard HQ
  33 things, an office 21, a warehouse 26) - taken from one real copy of it, up
  to 40 things. They are ordinary placements: move them, take them out, or keep
  them.
- **A gate is a whole gateway.** A gate in the game is one leaf, half a way in.
  Placing one (304_01_1, or `place_object` with that model) lays the whole
  thing: both leaves meeting in the middle and sliding back behind their posts,
  the switch that opens them, and a fence panel in line on each side, so a run
  of fence carries straight on from either end. Hold **Alt** while placing (or
  `one_leaf`) for a single leaf, which the player opens like a door. The switch
  stands against the gate post at hand height and **stays pressed**, as level
  10's gate switch does, so it opens the gate and closes it again; the leaves
  themselves are not locked (a locked leaf never moves).

**Doors** of the level (not elevator doors) have a **Lock** section in their
panel:

- **Locked:** as the level, always, or until a switch is pressed, a terminal
  hacked, an item picked up, a guard killed, or an event happens (the switch,
  terminal, item or guard is picked on the map).
- **Lock can be picked in (s):** the player can pick it, taking that long.
- **Opens by itself:** when an event happens. An event's *Open doors* does
  the same from the event's side (*Pick doors*, then click them).
- A pink padlock marks every door the mission changes.
- Built as the levels do it: the door's *Locked expression* waits for an
  `EditVariable` that goes to 1 when the thing happens (level 10), a pickable
  lock is `Door_N.isClosed && !Door_N.isPicked` (level 11; a door without a
  task id gets one), and *Open door expression* gains the event. **To be
  confirmed in game.**

How it is built (`apply_plan.py`, *events*): each event is an `EditVariable`
that goes to 1 the first time its condition holds and stays there. A message
is a `StatusMessage` sent once on it; an alarm gets a pulse of a few ticks in
its trigger (a `LevelTimer` started by the event), so an alarm switched off
later is not raised again; guards are a `GuardGenerator` on it; failing is a
`StatusMessage` that `LevelFlow`'s *Failed* waits for. An area is an
`AreaActivate`, time a `LevelTimer`. **To be confirmed in game:** each kind
of trigger and of action.

## Map computer preview

The **map computer** button (top right, the screen with a chart) shows the
plan as the game's map computer shows it: the ground, buildings, walls and
large structures, the level's labels and yours, the player, and the numbered
markers of the first six objectives. Pickups, props and everything the
studio draws of its own are hidden. Zoomed in, it shows the guards and
cameras too, as the game's map computer does when you zoom it. Its card lists the **Objectives**
page as the game shows it and how many of the map computer's **32 markers
and labels** the mission uses (the check list warns before a 33rd).

## AI designer

The **AI designer** tab on the right edge (next to *Selection*) is a chat with
a team of agents that design missions with you, each with its own job. It
works through the studio's own editing, so everything it does is an ordinary
change: undo, the change log, saving, the 3D view and Apply all work on it,
and building into the game stays yours.

Pick the agent above the chat. A chat keeps its history when you switch, so
the next agent reads what happened.

- **Ideas:** it looks at the level (its named places, buildings, guards,
  alarms, walkways) and answers with designs, each a pitch with objectives,
  enemies and where they stand, security, time and weather, and difficulty.
  Nothing changes. Each design has a **Build this** button, which hands it to
  the Mission builder.
- **Mission:** a whole mission, planned first and built one area at a time.
  It is at its best on an empty map, where nothing is built yet (a new chat on
  an empty-map mission of yours starts with it). It surveys the map, then
  proposes the mission as a **plan**: a card with the title and pitch, the
  settings, 3 to 6 **areas** (each lettered, with its role and what goes
  there: ground work, structures, guards, cameras and alarms, pickups), the
  objectives and the events. The areas are outlined on the map (blue while
  planned, yellow while being built, green once built, red where it hit a
  problem). The studio checks the plan before you see it: areas on the map,
  six objectives at most, objectives the game can test. Ask for changes in the
  chat ("move B north", "three areas, not five") and the card changes.
  **Build it** builds every area in turn, then finishes the mission (the
  objectives, events, player start, time and weather, texts, the check list
  and the stealth check); **Area by area** stops after each area for you to
  look (**Build the next area**, **Build the rest**). Typing "yes" or "build
  it" does the same. Each area is a request of its own, with its own **Undo
  these changes**; **Undo the whole build** on the card puts the mission back
  as it was before the first area. An area that ends with nothing built is
  marked as a problem, with **Try again**. The plan and its progress are kept
  with the chat, so a build left halfway goes on later.
- **Edit:** changes to the mission as it is: "make it harder", "move the
  snipers so they cover the road", "check the mission and fix what you can".
  It reads the mission as it is, your own changes included; what you have
  selected, and places you tag, say where ("put a sniper up there"). Each
  step is a row in the chat (with **Show** to find it on the map) and appears
  on the map as it happens; *Follow on the map* moves the map along.
- **Workshop:** buildings, characters and objects for your inventory, made
  from the game's parts and shown turning in 3D (see *New things for the
  inventory* below). The map
  doesn't change: add what you like to the inventory and place it yourself.
- **Review:** it walks the mission as the player would (the check list, the
  stealth check, the start, the objectives, the guarded places, the texts)
  and lists what to fix, most important first, each as a card saying where,
  why it matters and the fix. **Fix** on a card hands that finding to Edit,
  which makes it. Review itself changes nothing.
- **Stop** ends a request at once (and a plan's build after the area it is
  on). **Undo these changes** under a request puts the mission back as it was
  before it (Ctrl+Z brings the changes back).
- A built-in mission is never changed: Ideas and the Workshop work on it; the
  Mission builder and Edit offer a mission of your own first (the Mission
  builder: on this level's empty map, or a copy).
- **Chats:** each mission keeps its conversations, as many as you like
  (`missions/custom/<id>/ai/threads/`, one file each, ignored by git; a
  built-in mission's stay in the browser). The name at the top of the panel
  opens the list: open one to carry on where it stopped, **Rename** it, or
  **Delete** it (click twice). **+** starts a new chat and keeps the others.
  A new chat is named from its first message, and the light model gives it a
  better name after the first answer.
- **The message box** is three lines tall and grows as you type.

What it can do (its tools, in `editor/plotter.html` *the AI designer's
hands*): look at the mission, find named places, look around a point (what is
there, the ground, the nearest walkway, a building's floors), the catalogue,
one thing in full, the check list (with the build's own verdict: the AI
designer's check waits for a dry run of Apply on the plan as it is, so a plan it
calls clean is one Apply takes); place guards (on walkway points near a
place, or exactly, on a tower's top floor), change a guard, set a patrol,
place structures, fence or wall runs, a fenced compound, pickups, cameras and
alarm hardware; move and remove things (yours or the level's), objectives,
events, time limit and weather, the mission's name and the player start; and
move the map or open the 3D view to show you something. It keeps to the
game's rules: guards need a walkway within 25 m (it is refused, and told the
nearest one, where there is none), six objectives on the map computer, and
the level's own objectives dropped for a new mission.

- **Walkways and ground:** `add_walkways` lays walkway points from the
  nearest walkway to a place along a way on foot (the routes' walk grid, round
  buildings), every 4 to 12 m, and rings of them round the place; where the
  nearest walkway is on other ground (a hill), it climbs to it in steps short
  enough for a link (2 m up or down); where a step is too steep it stops
  and says where a ramp would make it walkable. Out of doors the points keep
  off buildings, and each new link is tested against the walls and fences the
  mission has (`api/links`, the test Apply makes): a point only reachable
  through one is left out, and the answer says so. Guards and patrols can use
  the new points. A guard moved (`move_item`) onto other walkways (into a
  building, say) takes that graph, as Apply would, and a patrol on the old one
  is dropped with a note to set a new one. `shape_ground` levels, raises,
  lowers, smooths or ramps the ground, as the Ground tool does.
- **Stealth check** (`stealth_check`): the quietest way on foot from the
  player start to each objective (the Sight lines panel's routes), how many
  metres of it are watched, the watched stretches, and which guards and
  cameras watch it most (each one's own view, his walk and a camera's sweep
  included). The routes are drawn on the map, green unseen and red watched.
  It then suggests fixes, or makes them.
- **Texts** (`write_texts`): the mission's name and one-line description (the
  game's mission list), objective texts, map computer labels of your
  buildings, and a briefing of one to three lines shown as messages at the
  start, in the game's terse style. A level's own objective can be worded
  anew too: it keeps what it tests, and the build writes the new words under
  the mission's own key (`retext`).
- **Versions and campaigns:** `make_versions` makes easy, normal or hard copies
  in the library (also *Mission menu, Easy, normal and hard versions*):
  easy has a third fewer of your guards, everyone seeing 20% less, cameras
  25% less far, 50% more time, no failing on the alarm and a medipack by the
  start; hard one more guard for every two of yours on walkways near them,
  sight and cameras 25% further, 25% less time, failing on the alarm and half
  your medipacks gone. Guards the objectives and events name are kept.
  `make_campaign` (and *Mission menu, Make a campaign*) puts missions in order
  under a name and a briefing (the AI can write it) and exports them as one
  pack; importing it adds them numbered in order and shows the briefing.

**Settings** (the Settings button, *AI models*):

- **Saved models:** as many as you like, each with a name, a provider, its
  model, how much it thinks (off to high), whether it reads pictures, the
  longest answer it may give, and a key of its own. **Add a model**, **Edit**,
  **Test** (one short request to it) and **Delete** (click twice; the one a
  role uses can't be deleted). Kept in `config.json` (`ai_models`), keys
  apart.
- **The AI designer uses** and **The light model uses:** each picks one of the
  saved models (`ai` and `ai_light`, `use`). **Pace** (how long each step
  stays, to watch it build) and **Steps per run** (60) belong to the designer,
  whichever model it uses; **Use a light model** turns the light one on or off.
- **Switching:** the model's name at the top of the AI panel opens a menu:
  which model this chat runs on (the designer's or the light one), and which
  saved model each of them uses, without opening Settings.
- **Providers:** OpenAI, which the studio talks to through its Responses API
  (on the newest models the only way to think and use tools together: Chat
  Completions refuses tools with reasoning on `gpt-5.6-luna`), or any
  OpenAI-compatible server (OpenRouter, a local LM Studio, Ollama, vLLM or
  Unsloth Studio) through Chat Completions: its address, the model, its
  context window as the server loaded it (every request is fitted into it),
  and a key if it asks for one.
- **Keys:** typed in a model's form, the studio keeps each encrypted for your
  Windows account (DPAPI, `secrets.json` in the studio's folder, one per saved
  model), never in `config.json`. The page never gets a key back, only its last
  four characters. An OpenAI model without a key of its own uses the one from
  before saved models, or a checkout's `.env` (`OPENAI_API_KEY`); a key is
  never sent to any other server.
- **From before saved models:** the designer's model and the light model
  settings become the first two saved models, keys and all, the first time the
  studio starts.
- **The light model** does the chores: it names chats, reads pictures, and is
  the **scout**: a tool the designer can send to look things up with the
  looking tools, which answers briefly and saves the designer's time and
  tokens. Keep its thinking off: with it, a 9B model took 49 s to name a chat,
  without it 2 s (2026-09-19). A chat can run on it entirely (the menu above;
  the name turns green).

How it runs: the loop is in the page (`editor/ai.js`), because its tools act
on the plan in the editor. Each model turn goes through the studio server
(`studio/server/ai.py`, `POST /api/ai/chat`), which adds the key, speaks the
provider's protocol and streams the answer back as JSON lines (text, thinking,
tool calls, done, error). Turns chain by response id, so a long build does
not send the whole history each time. A run of about twenty steps took 40 s
and 100 to 170 thousand tokens (half of them from the cache) with
`gpt-5.6-luna` at low thinking (2026-09-18).

**Pictures and sketches** (the buttons above the message box):

- **Sketch on the map:** drag on the map to draw, in red, yellow, cyan or
  white (say in the message what each colour means); Undo, Clear, Done. The
  strokes go to the model as exact coordinates (their turning points), with a
  picture of the map with the sketch on it. They stay drawn until the message
  about them has been worked on. "A fence along the red lines, a camera at
  the north-east corner" builds just that.
- **Attach the map:** the map as it is on screen, with a grid in metres
  labelled, and where its edges lie, so the model can read positions off it.
- **Attach a picture:** a file, or paste one, or drop it on the panel: a
  sketch on paper, a screenshot of another game's map, a plan. Pictures are
  shrunk to 1400 px.
- The light model reads each picture first (what is where, the marks and
  their colours) and its reading goes with the message; the main model sees
  the pictures too. A picture goes to the model once; the chat keeps a small
  copy to show.

**Tagging a place:** the button left of the message box tags a place on the
map for the next message: drag an area, or click a thing or a spot (Esc
cancels). Tags are lettered **A**, **B**, **C**, drawn over the map, shown as
chips on the message, and sent to the model with their exact bounds, so
"build a checkpoint here" or "a sniper nest in A facing the road" means just
that. They stay drawn while it works on them.

**New things for the inventory:** asked to design something ("a sandbagged
sniper nest I can keep", "a Spetnaz officer with a Desert Eagle"), it makes
it out of what the game has, as a card in the chat with its 3D model turning:

- **A structure** (`design_structure`): parts by model id placed round a
  centre (with guards and pickups if it needs them): a guard post, a
  checkpoint, a weapons cache, a bunker entrance.
- **A character** (`design_character`): a guard type with a model of its
  kind, a weapon and sight of its own.
- **The studio checks a structure** as it is made and tells the AI its flaws,
  which it corrects before showing it: a part floating with nothing under it,
  or sunk into the ground; the same part twice in one place; a part far from
  the rest; a guard or pickup inside a wall, a fence or a crate. Each part's
  box is its model's real one (size, height, and where the box sits from the
  model's origin, which the catalogue now reports for parts whose origin is not
  their middle, like a sandbag wall's end).
- **View in 3D** shows it bigger, **Place** puts it on the map where you
  click (R turns it), and **Add to inventory** keeps it (`missions/groups/`,
  kind `blueprint` or `character`), for any mission. It can place its own
  designs too (`place_design`).
- New weapon types and new 3D models can't be made: the game defines its
  weapons for every mission at once, and models come from its files.

## A draft from a description

*A draft from a description…* (Mission menu): write the mission in plain
words, for example *"Two snipers near the radar dome, four spetnaz guards at
the barracks and two cameras by the control tower. Hack the terminal, grab
the Dragunov at the watchtower, then escape by the north gate. Snow, a 15
minute time limit, don't raise the alarm."* **Read it** lists what it
understood; **Add to the mission** places it, as one undo step, selected as a
group to move or change.

- It is read with a few rules on this machine, nothing is sent anywhere.
- **Who:** a number and a kind (guards, patrols, snipers, gunners, RPG
  troopers, officers; *spetnaz*, *mafia*, *security* where the game has
  them), and cameras. They stand on the walkways nearest the place named
  after them.
- **Where:** the map computer's labels, the level's buildings and gates, and
  north, south, east, west (*the north gate* is the gate furthest north).
  Without a place, the last one named.
- **What:** hack the terminal, eliminate an officer or target (a guard is
  placed for it), eliminate everyone, collect a weapon (it is placed), destroy
  what can be blown up, escape or reach a place. The level's own objectives
  are left out when it adds some.
- **And:** rain, snow or fog, a time limit in minutes, staying unseen (the
  mission fails on the alarm).

## Test from here

Right-click the map, **Test from here…** (or, walking in the 3D close-up,
**Test from here** in its bar): the mission is built and installed with the
player starting at that spot (on the floor of a building there, or the
ground; from the close-up facing where you look), and the game is started.
Pick the mission in the game's list. **Build only** installs without
starting the game; if the game is already running, leave the mission and
pick it again.

- The plan keeps its own start. The game has the test start until the next
  Apply: the header says *a test build, starting elsewhere*, and the change
  log shows the player start as changed.
- Server: `POST api/missions/<id>/applyjob {test: {x, y, z, gamma, launch}}`
  (a copy of the plan with the player's start moved, recorded in
  `installed.test`) and `POST api/launch` (starts `IGI.exe` in the working
  game, once).

## Groups, copy and paste

**A fenced compound** (right-click the ground, *Build a fenced compound
here…*): a chain-link fence or a masonry wall round a rectangle you size, a
way in on the side facing the player's start, a floodlight panel by it,
watchtowers (two by the way in, or one at each corner; the snow ones on snowy
levels) and up to four guards inside the way in, looking out. It is made of
your own placements, selected as one group: drag it, turn it with R, or
change any piece. Models the level does not pack are brought in on Apply.

- **Level ground:** the ground under it is levelled at its middle height (a
  *Level* area of the Ground tool), and the fence stands on it. The game
  moves its ground a few metres at most, so on a steep slope part of it stays
  uneven; the message after building it says so.
- **A gate with a switch:** the way in is two sliding gate leaves (the
  level 10 gate, `304_01_1`), each sliding back behind the fence, and a gate
  switch (`202_01_1`) inside by the post. Pressing it opens them (a `Door`
  task each, opening on `Switch_N.isPressed`). *No gate* leaves a 6 m gap.
- **Guards** walk to the level's walkways. When the nearest walkway is more
  than 25 m away they would walk off out of the compound, so none are placed
  and the message says why; the check list warns about any guard of yours
  that far from a walkway.

- **Select a group:** Shift+drag a box around your objects (Shift+Alt+drag
  also takes the level's own movable objects), or Shift+click to add or
  drop one. **Ctrl+A** selects all your changes.
- **Work on the group:** drag any member to move them all. The arrow keys
  nudge it, **R / T** turn it about its centre, **G** drops it onto the
  ground, **Ctrl+D** duplicates it and **Delete** removes it. Each of these
  is one undo step.
- **Copy and paste:** **Ctrl+C** copies the group to this browser's clipboard,
  and **Ctrl+V** pastes it at the cursor, in any mission and on any level.
  Patrol stops at copied nodes or copied buildings follow the copies. Stops at
  the level's own nodes are kept only on the same level.
- **Save as group…** (in the group panel) names the group and keeps it in
  `missions/groups/`. It then appears under **Saved groups** in the inventory,
  with a small map of its members. Pick it, turn it with **R**, and click to
  stamp it. **Delete saved group** is on the placement bar.

## Check before applying

**Apply** first saves the mission, then shows a check list. **Mission ▾ →
Check mission…** shows the same list at any time. It has three groups:

- **Must fix** (Apply stays disabled): patrol stops that don't exist or can't be
  routed to, new nodes with no neighbour (a link through a wall or fence does
  not count: the server tests each one as Apply does), graphs over 999 nodes
  (Apply makes a graph's file bigger in steps of 100, up to 1000), guards with
  no graph, models no level ships, and the **Build** group: what Apply itself
  would refuse. The server runs the build on the saved plan without installing
  anything (the dry run that also settles heights) and the list shows its
  errors word for word; its warnings, and what it changes on its own (a guard
  moved onto a building's walkways), go under the other two groups.
- **Worth a look:** buildings that overlap others, stand on steep ground or
  lie outside the mapped ground; objects hovering over bare ground; objects
  placed twice.
- **Good to know:** which model families Apply will copy in from other levels,
  and how many MB that adds (`/api/missions/<id>/check`, which reads only the
  archives' name chunks).

Every row has **Show** (select it and fly there). Where there is an obvious
fix, it also has one: remove the stop, remove the node, set it down, remove
the copy. The list refreshes after each fix.

Before it builds, the dialogue also lists **what goes into the game**: what
is placed, changed, removed, the navigation it touches and the objectives the
map computer will list.

**Applying** saves the mission again and builds it in the background
(`POST /api/missions/<id>/applyjob`, polled at `GET /api/jobs/<job>`). A
CONNECTING-style bar shows the stage, each step as it happens, and the full
log under **Details**, which opens by itself when the build is over. The stages are:

1. Copying the base level into a new slot (first time only).
2. Building the level script.
3. Compiling, and importing models from other levels.
4. The height map and the language strings.
5. Installing `objects.qvm`, the AI scripts and the graphs.
6. Checking the result.

Closing the sheet doesn't stop the build.


**After the first Apply** the list is about what this Apply adds: *New since
the last Apply* counts only what the game does not have yet, and warnings
about things already in the game fold into one line you can open (*N about
what is already in the game*). Errors always show. When nothing has changed
since the last Apply, it says so and applies nothing; **Apply again anyway**
rebuilds the mission as it is (after a problem in the game, for instance).

The editor's height sync (the heights the build gives) also updates the
record of what is in the game for things already there: the game has those
heights, so the mission stays up to date.

**Faster Apply:** the height maps for shaped ground (most of a build's time on
a mission with a lot of it) are kept in `cache/patches`, under a hash of
everything they are made from, and reused when the ground has not changed.

**Imported models bring their parts:** a model can be built from parts of
other families (a watchtower carries its stairs, 314_01_1); Apply copies those
too, and completes a slot that has the model without them.
## Mission menu and right-click

**Several missions in one file:** *Export all my missions in one file* (Mission
menu) writes a pack (`igi-mission-studio-pack`): every mission of yours with
its name, in-game description and whole plan. *Import mission file…* takes a
pack as well as a single mission, and adds each as a mission of its own, in
order, for handing a set (a campaign) on to someone.

**Mission ▾** (next to the title) has:

- new mission, the library, save (**Ctrl+S**), duplicate
- rename (the in-game name and description)
- export/import a mission file, copy the plan
- apply to the game, remove from the game, tidy up, settings
- delete

Looking at a built-in mission, it offers only **New mission from this one**.

Right-click anything on the map for its actions:

- **Objects**: edit, duplicate, rotate, edit or clear a patrol, change a guard's
  type or weapon, change a pickup's item, undo, remove.
- **Nodes**: remove (disabled while a patrol uses the node), undo, zoom to or
  hide the graph.
- **Empty ground**: add an enemy, weapon or node right there. "Add building or
  object here…" opens a type-to-search box over the whole catalogue.

## Editing what the level already has

Select any shipped object to edit it:

- **Guards**: position, facing, type, weapon, model and patrol route.
- **Pickups**: the item.
- **Buildings and props**: position and rotation. Drag them once they're
  selected.
- **Anything**: remove it, including objects with no task id.

Edits are applied to that very task in the level script, found by its
reference (task type plus position exactly as written). Ids never change, so
objectives and scripts that name the object keep working. Every edit can be
undone, from the inspector or the "Your changes" list.

Giving a patrol to a guard that had none adds a PatrolPath task and a standard
patrol AI script in place of his own. A rewritten route becomes walk-and-pause
stops.

## Models from other levels

`studio/build/models.py` packs a model into the slot along with its whole
*family*: every model sharing the first number group (hull, LODs and parts).
The family's textures and palette entries come with it.

**Lightmaps: why an imported model can be invisible.** A level bakes a lightmap
for the objects it ships, and each of a model's render groups says whether it is
lit that way — field 13 of the group header in its `DNER` chunk is 12 for "lit by
the level's lightmap", 0 for "lit dynamically". A model copied into another level
has no lightmap there, and the engine then draws **nothing at all**: the object
is in the world, it makes its sounds, and it cannot be seen. The importer
switches that flag off on every model it copies, and on models earlier imports
left behind. The same models ship with the flag off in levels that light them
dynamically — level 6's siren is byte-identical to level 1's apart from this flag
and a build stamp — so this is the game's own arrangement, not a workaround.

How the files fit together:

- **Palette:** `levelN.mtp` is regenerated from the text `.dat`. That
  regeneration is byte-identical for 13 shipped levels and the slot.
- **Sources:** source levels are read from their compiled `.mtp`. Level 10's
  `.dat` lists more models than its own count says, so it can't be written to,
  but it can be used as a source.
- **Archive chunks:** each chunk's fourth field points to the next chunk, and
  the last chunk says **0**. That's where the game stops reading, so appended
  models only count once the chain is re-linked.

Importing only appends. The original sizes and last chunk are recorded in
`backups/models/`.

- `python studio\build\models.py verify` checks every level.
- `python studio\build\models.py repair --slot 15` re-links the chain and
  completes partly imported families.
- `python studio\build\models.py restore --slot 15` truncates back to the
  original.

## Patrol nodes

Guards walk the level's navmesh. **Navigation → Add node**, then click the map.
Dashed lines preview the links the node will get: up to 6 nodes on the same floor
within 15 m. The generator uses the same rule, and also drops any link that
would pass through a wall (see *Walls*). A red node has no neighbour close
enough, so the build rejects it. Patrols can use new nodes like any other node.

Shipped nodes can be edited too. Show nodes, click one to select it, then drag it
to move it or press Delete to remove it. A node that any guard's patrol uses
can't be removed. The Navigation section shows each graph's used / total node
slots.

On Apply the graph file is edited and the whole routing table is rebuilt. An
existing entry keeps its original bytes only while it is still correct: same
cost, and its predecessor still exists, is still linked, and still lies on a
shortest path. The build is refused if an edit would cut a route that a shipped
guard walks. The script's `AIGraph` counts are updated to match, and the slot's
original graphs are backed up once, to `backups/graphs/levelN/`.

## Patrol animation

Guards with a patrol walk it on the map, drawn once where they are right now. They follow the graph's links (shortest
path), walk or run as the patrol says, pause on its delays, and change pace on
its "set travel speed" commands. Your own guards' routes are always drawn;
shipped guards' routes show when selected, or with the routes toggle on.

A shipped guard usually has several patrol paths: one for when all is quiet,
the others for alarms. Which one he walks is decided by his AI script
(`AIEVENT_IDLE` → `AIAction_Patrol(path)`), so the extractor reads the
scripts (decompiled out of the slot after every Apply). Only that path is his
patrol. The barracks guards in level 1 each walk to a post inside the
barracks and stay there; their alarm paths lead out into the yard. A
rewritten patrol replaces that idle path and leaves the alarm paths alone.

## Inside buildings

Building floors are **not** in a building's collision mesh. The barracks mesh,
for example, has a slab at −0.02 m and a rim, but its floor is at +0.32 m, and
only the navmesh nodes inside know that. The engine stands a soldier on the
navmesh. So a building with no nodes inside leaves its guards in the
foundation, feet under the floor. A guard killed there drops out of sight.

`studio/build/navtemplates.py` takes, for each of 99 building models (plus
4 same-size variants), the shipped copy with the richest interior. It records
that interior in model space: floor, stair and door nodes; their links, with
the engine's own link weights; the doorstep nodes outside; and the floor
heights. The result is `navtemplates.json` in the level data.

- **A building you place** brings its interior (inspector → *Inside → Floor
  nodes*, on by default). On Apply its nodes join the nearest graph, whose
  capacity grows in 100-node steps when needed. Its doorways are linked to
  yard nodes within 12 m, but only along lines that don't cross a wall.
- **A building an earlier Apply placed** has no interior. Its inspector says
  so; **Add floor nodes** gives it one. Guards already standing inside it are
  moved up onto its floor.
- **A floor with no nodes yet** gets them when a guard stands on it. A
  building's floors are its own nodes' floors plus the template's. A floor
  counts as present when any node stands within 0.3 m of its height; it isn't
  decided by clustering, because yard nodes at a doorstep would swallow a floor
  30 cm up. Only the missing floors are added, and template nodes on floors
  that already exist are matched to the building's own nodes.
  - **Towers:** a watchtower (platform +11.6 m) or a water tower (+18.1 m)
    has only its platform. The shipped platforms aren't linked to the ground,
    so a guard up there stays there.
- **A shipped building you move** takes its interior nodes with it. One you
  remove takes its floor nodes away, except nodes a patrol still uses.
- **Floors:** a guard or item dropped inside a building lands on its lowest
  floor (a tower's platform), on the graph that building is on. **Stand on**
  (or `[` / `]`) lists the building's floors (ground floor, 1st floor…,
  platform +11.6 m) and, for a tower, the ground under it. With the local
  server running it also lists desk, crate and shelf tops right there, read
  from the collision meshes (`/api/surfaces`). A guard on a floor with no nodes
  yet says so in his inspector.
- **Patrols** can use interior nodes: in patrol mode, click the hollow dots
  inside the building. The walk animation follows the stairs.

Outside buildings, **Stand on** lists the heights of the nodes nearby
(ground, +3.4 m on a tower, and so on).

## Walls

A guard follows his graph links in a straight line, and nothing solid stops
him. A link that runs under a building someone placed on top of it leads
straight through its walls. On Apply, `surface.py` tests every link near
what the plan builds or moves:

- **The test:** the walk, at knee and chest height, against the model's
  collision triangles. It counts as blocked only if lines 0.6 m to either side
  are blocked too, so shaved corners and poles don't count.
- **Checked against shipped levels:** of 23,615 shipped links outside doorways,
  98.6% pass, and most of the rest are inside tunnel pieces.
- **What gets tested:** your placements, moved shipped objects, and buildings
  and props an earlier Apply placed in the slot. The earlier ones are found by
  comparing the slot with the shipped level it was made from.

Links that fail are cut. If a patrol, alarm routes included, has no other
way round, the link is kept and the build log says so. Yard nodes left
stranded inside a building, or buried under its floor, are removed unless a
patrol names them. A building's own interior and doorway links are never
cut on its account.

## Fence and wall runs

Panels laid end to end (by hand, in a compound, or by the AI designer) join
without a gap in the game. A panel is measured from its render model: the
sizes come from the collision box, which is longer (16.31 m for a chain-link
panel whose posts stand 15.84 m apart, 20.39 m for a 20 m wall), and runs laid
by it left a gap of about half a metre at every joint (found in game
2026-09-19). A fence's end post now stands where the next panel's first post
does; walls meet edge to edge.

- A run always ends where it should: the last bit is covered by a panel set
  back to end there, never left open.
- A compound's gate stands where whole panels end, near the middle of its
  side, so the fence meets the gate post exactly.
- **Runs laid before the fix:** the check list before Apply counts the joints
  that leave a gap, and **Close them** moves each panel after a gap back
  along its run (each run then carries on from its first panel, and its far
  end moves in a little).

## A guard needs walkways where he stands

When a mission starts the game walks every guard to his walkway graph. With no
walkway point near him at his own height he walks off to the nearest one there
is: across the map, or up into the air where a building's floor used to be (an
empty map keeps the walkway graphs of the buildings it takes away, and some of
them hang 12 to 18 m up). That is how guards end up standing in the sky.

- The graph a guard is given is never one whose points are on another floor;
  where there is none he can stand on, he is given none, and the check list
  says so.
- **The check list** (and the AI designer's check) refuses a guard whose
  nearest walkway point on his graph is more than 2.5 m above or below him, and
  warns when it is more than 30 m away.
- **Apply refuses it too** (`studio/build/plan.py`), with the same words, so a
  mission with a floating guard never reaches the game. A guard with no graph
  at all is given the nearest one that has a point on his floor, rather than
  whichever graph the level lists first.

## Guards reacting to gunfire

Cutting links isn't enough. A guard whose AI script hands every event to
`AIFunction_DefaultHandler` reacts to gunfire by moving straight at it,
through the wall. The shipped guards indoors don't do that: 825 of the game's
855 AI scripts have this shape:

```
CREATE  -> DefaultHandler (+ SetAlarmControlID, for 120 of them)
IDLE    -> AIAction_Patrol(patrol path)
ALARMON -> AIAction_Patrol(alarm path)    level 1 barracks: "Runs to node 20", out through the door
else    -> DefaultHandler
```

Every guard Apply creates now gets the same shape. Guards an earlier Apply
created get it too, once, if their script has no `AIEVENT_ALARMON`:

- **Alarm control:** he gets the one the nearest shipped guard uses (within
  80 m), if any.
- **Inside a building** (not a tower), he also gets an alarm path. It runs to
  the nearest node in his own room first, then along the navmesh to the first
  node outside. Going straight to the nearest node could mean the doorstep
  outside, through the wall.

Combat after that is the engine's default handler, as it is for the shipped
guards.

## Guard models

A `HumanSoldier` names its model, team and skeleton (`Bone Heirachy`). Apply
takes these from the shipped soldiers: skeleton 6 for the two models that ship
with it (015_01_1 and 012_01_1), 1 for every other model. The team is 1
(enemy) unless the placement sets another.

**Which side a soldier shoots for** is that team, and the panel's **Side**
names the three the game itself uses, rather than asking for the number: the
enemy (1, and 678 of the game's soldiers are on it), fights on your side (0 -
Harrison and his GIs in GOD, Priboi, Anya and her escort, the driver in
Trainyard: 18 in all), and a side of its own (2, which only Ekk's fortress
uses, for two guards). *Another side* takes any other number, for a mission
that wants more sides than the game ever needed.

This works on a soldier the level ships as well as your own. It is an edit
like any other: undo puts it back, and Apply writes the number into the
level's own `HumanSoldier` task, leaving its model, skeleton and nested tasks
alone. A soldier on your side is drawn in the player's green on the map,
counted on its own line in the legend, and left out of the guards the sight
layer watches with.

A model that is missing from the level's `models/levelN.res` gives an
invisible guard with a floating rifle. **Model import** packs every soldier
model a mission uses from other levels. Spetnaz 018_01_1 was still invisible
in level 3 with the model packed byte-for-byte, and with its textures, bones,
animations and AI checked. The **Guard model test** mission
(`missions/custom/guard-model-test-08be29/lineup.txt`) puts every guard type
in a row at the start, numbered from the west, to find out in the game which
ones fail.
