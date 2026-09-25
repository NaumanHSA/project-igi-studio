# Changelog

What changed in each release of Project IGI Studio, newest first. Each
section is also that release's notes on GitHub.

## Unreleased

Your items in the inventory, a repair button for the AI designer, fences laid
by dragging, and fixes for a mission that stopped the game.

### New

- **Your items.** Keep what you like in a mission - a building, a guard, a
  whole area, yours or the level's - in the inventory: select it, *Add to your
  items*, give it a name and a category (areas, buildings, characters, objects,
  weapons and items, cameras and alarms). It places in any mission, on any
  level. A building keeps its doors, lift and furniture, and one of the level's
  comes back with what the game gives it. The AI designer's kept designs and
  characters, and saved groups, are there too.
- **The inventory as tabs.** The button beside its search box shows Your
  items, Characters, Weapons and Structures as tabs, one at a time filling the
  panel - or as sections again.
- **Fix with the AI designer** at the foot of the check list: its Edit agent
  gets every problem on the list and fixes them, keeping your guards, cameras
  and buildings.
- **Built-in missions can be taken from.** Select one thing or a whole area of
  an original mission (Shift+drag), look at it in 3D, copy it, and keep it in
  Your items for a mission of yours - a group's panel has *Add to your items*
  first, to keep the whole selection as one item.
- **The level's machine guns are on their stands** on the map and in 3D: the
  gun itself was never read, only its stand (the level data is read again
  once, version 6).
- **Fences by dragging.** With a fence or wall in hand, press and drag: a panel
  is laid each time the pointer gets a panel's length on, end to end, as far as
  the drag goes - one undo step for the whole run. A click still lays one.
- **A gate on its own** in the inventory, beside the gateway: both leaves and
  the switch that opens them, with no fence panels either side.
- **A ⋮ menu on each of Your items:** edit its name and description, or
  delete it from the inventory.
- **An item's preview is all of it:** hovered, a compound shows as the whole
  compound - its fence, gate, towers, buildings and guards, as one model -
  and what it covers. It showed the first thing in it, often a guard.

### Changed

- **Fences, walls, gates and small things are placed on their own.** Only a
  real building brings the doors, lift and furniture the game gives it: a fence
  panel came with an electricity pole and doors, a wall with doors.
- **An area kept from a level keeps its gates and doors**, as doors of yours
  that open, its cameras and alarm buttons (joined to the nearest alarm system)
  and the look of its other switches. The player start and the machine guns
  stay behind.
- **The level's switches are named for what they do:** an alarm button only
  when an alarm system listens to it; a gate's, a lift's or a door's switch by
  its own name, or *Switch*. Every one of them was called an alarm button.
- **The AI designer sees the check list you see:** its check includes the
  server's rows (hovering, placed twice, models no level ships), each with the
  id its tools take and the list's own fix, and so does *Fix with the AI
  designer*.
- **Trying to change a built-in mission says so where it can't be missed:**
  the banner at the top turns amber with a warning and a *New mission from
  this* button, instead of a toast. Looking at one no longer shows the
  message at all - it came up just from selecting something - and its
  panels are no longer greyed out: what only looks stays on.
- **The AI designer repairs instead of deleting.** Its agents are told that a
  fix makes the thing work - walkways laid where a guard has none, a guard
  stood on a building's floor or a tower's platform - and that a guard, camera
  or building is never removed just to make a check pass. It had removed the
  snipers a check complained about.
- **A camera joins the nearest alarm system as it is placed**, by hand, by the
  AI designer or from a draft, as buttons and sirens do. On a level with no
  alarm of its own, a camera or guard with none set raises or answers the
  mission's own nearest system.

### Fixed

- **A mission with cameras and no alarm stopped the game** ("Too few
  parameters in line 0 of file ...objects.qsc"): the alarm made for its
  cameras was written one parameter short. It is written whole now, and every
  Apply checks each task it writes against the count the game's own levels
  give that kind of task, so a slip like it stops Apply, with the task's name,
  instead of the game.
- **A time limit could not be applied** ("unexpected ','"): its clock went
  beside the level's LevelFlow, where the script allows nothing else.
- **Snipers on a tower of yours** were refused, standing 11 m above their
  walkways: a tower's platform got walkway points only with a graph within 40 m
  of its base. It joins the nearest graph however far now, as the game gives
  its own tower snipers walkways of their own up there, and the check list
  reads a guard in a building on that building's walkways, as Apply does.
- **Buildings beside walkways the mission laid got no floor nodes** ("no
  navmesh within 40 m"): the mission's own new walkway points count now, and
  doorways link to them.
- **Warnings nothing could fix:** things on the floor of a building of yours
  were said to hover as high as the floor (the check measured them against the
  bare level), and a ground area levelling the ground at the height it already
  has was said to keep it from changing under everything on it.
- **"No level ships model 1":** a switch kept from a level took the level's
  switch expression for its model, and Apply refused the mission. The check
  list gives it its look back (*Give it its look*); anything else of a model no
  level ships has a *Remove* button. The dry run and the check no longer list
  the same problem twice.
- **A copied building left its doors behind:** the doors, lift and furniture
  that came with a building follow its copy when it is pasted or placed from
  Your items, and an alarm or event the copy names that the mission lacks falls
  back to the automatic.

## 1.0.5

Soldiers on your side, buildings whose cellars, lifts and doors work the way
the game's own do, and a 3D view that shows the levels as the game draws them.

### New

- **A soldier can fight on your side.** Every soldier - yours or one the level
  ships - has a *Side*: the enemy, fights on your side, or a side of its own,
  the three the game itself uses; *Another side* takes any other team number.
  A friendly is drawn in the player's green on the map and counted on its own
  line in the legend. Contributed by @heaven-hm (#10, closing #8).
- **The 3D view is ready when you open it.** Opening a mission or a built-in
  level fetches every model the 3D view draws and the textures they wear, with
  a bar on the map as it goes (level 9: 82 models and 341 textures in about
  three seconds).
- **Cellars, lift shafts and tunnels are open in 3D** where the game opens
  them. The levels' own `DiscardTerrain` squares are read, so the generator
  room's floor and Eagle's Nest's tunnels are no longer hidden under a sheet of
  ground (#4).
- **The game's own lifts** stand in the 3D view where each level starts them,
  Eagle's Nest's cable car among them.
- **Railways and roads are the game's own models in 3D** - ballast, sleepers
  and rails along the curve, the embankment on its slopes, the track across the
  bridge - and they come along as you move, like everything else (#4).
- **A building's cellar comes with it:** the underground security building
  brings its cell doors, its metal door and its beds with the rest.

### Changed

- **A building with a cellar or a lift shaft stands on the game's ground
  grid.** The game opens the ground only in whole squares, 16 or 32 m, on a
  grid of their own, and its buildings stand where those squares fall under
  their walls; yours now do too - placed there, settling onto it when you let go of
  a drag, kept there as they turn. A mission made before moves such a building
  once as it opens (a banner says which and how far; undo takes it back). No
  building moves more than 8 m each way.
- **A soldier is offered the weapons the game arms its soldiers with**, the
  thirteen of them. The knife, the flashbang, the proximity mine and the dual
  Uzi are gone from that list: a guard given one held it like a rifle and
  never used it. The AI designer is refused them too, and a guard who already
  carries one keeps it, marked as something he can't use.
- **A thing is called by its model when its level's name for it belongs to
  another model:** a water tower swapped for a radar tower in an editor keeps
  the task name "WaterTower", and is now "Radar Tower" (#2). The inventory
  names models by the same rule.
- **Tests run on every push and pull request**, from @heaven-hm's #10.
- The level data is rebuilt once after updating (version 5).

### Fixed

- **A lift's doors open where the cabin is.** They could open onto the empty
  shaft while the cabin stood below, and stay shut when it arrived: a
  building's doors and its lift could come from two copies of it whose lift
  paths run opposite ways. A door now opens at the floor at its own height,
  also for missions made before, on their next Apply.
- **Door leaves slide as their own doorway's do.** The lift doorway never
  shut - its inner leaves slid apart as the outer ones closed - because every
  door a building brought slid as its model most often does; 67 of the 202
  doors buildings bring slide otherwise.
- **No pit round a building of yours that opens the ground.** Its lift shaft
  was opened in 16 m squares laid off the building, up to 32 m across round
  it, where you could fall through beside the wall.
- **An imported model wears its own textures** (#7). In the game, a model
  brought into a level that had a texture of the same name with another
  picture wore the level's - the sniper `001_01_1` in Eagle's Nest wore the
  level's pale camouflage; 86 of the ways a guard can be imported were hit. It
  now gets its own copy, and models imported before are put right on the next
  Apply. In the studio, an imported model's textures were looked up in the
  wrong archive, and a texture's picture was cached by its name alone, so the
  first level to show it showed it in every level after.
- **Parts of the 3D view went missing** as you moved: the railway was gathered
  once and never again, past the edge of a level's ground nothing new came at
  all, and a cut set for one room took every watchtower's head off.
- **Trainyard's track sank into the ground** in 3D before its embankment.
- **The level's guards no longer float in 3D:** they are drawn where the game
  stands them, on their walkway (level 6's buyers and scientist).
- **The map's red names** no longer pile up on an empty map, and go with the
  building they name when a mission takes it out.
- **Opening another mission closes the 3D view** of the last one.
- **Collision boxes** are no longer drawn as brown blocks in 3D.
- **A building's doors are its own:** some were given to a desk or a plank
  standing beside them, and a lift building's lift doors went missing.
- **The Textures section's header** read "undefined".
- **A first data build guessed every guard's patrol** and missed the alarm he
  answers; it reads their AI scripts now (88 guards answer one).

## 1.0.4

A team of agents in the AI designer, buildings that come with everything
inside them, and a mission that can carry its own textures.

### New

- **The AI designer is a team.** *Ideas* suggests missions; the **Mission
  builder** surveys the map, proposes the whole mission as a plan (the areas,
  the objectives, the events) and then builds it one area at a time, each
  undoable on its own; *Edit* changes the mission as it is; the **Workshop**
  designs buildings, characters and objects for your inventory; **Review**
  plays the mission on paper and lists what to fix, each finding with a *Fix*
  button that hands it to Edit. A build left halfway goes on later.
- **Buildings come with their doors, their lift and everything inside.** A
  building placed from the inventory brings what the game gives it, copied
  from a real copy of that building in the levels: 175 doorways over 164
  buildings, 7 lifts, and for 149 of them the things that stand inside -
  desks, filing cabinets, lamps, beds, crates, barrels (the Guard HQ brings 33
  things, a warehouse 26). Each is an ordinary placement: move it, take it
  out, or keep it, and it stays in place when the building moves.
- **Doors that open and lifts that run.** A door of yours is written the way
  the game writes its own, so it opens in the game, and can go on an upper
  floor. A lift runs between its floors with a call button at each and one
  inside the cabin; a lift's own doors belong to the lift, locked to the
  player and opening when the cabin arrives; and a shaft that goes below the
  ground opens the ground over it.
- **A gate is a whole gateway.** Placing one lays both leaves, the switch on
  the post that opens them, and a fence panel in line on each side, so a run
  of fence carries straight on.
- **A mission can carry its own textures.** Anything with a model has a
  *Textures* section: the pictures it is drawn with, as the game has them, and
  *Replace* takes a PNG of yours. It is kept with the mission like any other
  change, and written into the mission's slot on Apply; taking it off again
  gives the level its own picture back, byte for byte.
- **Save as many models as you like** (Settings, *AI models*): each with its
  provider, address, model, thinking, context window and its own encrypted
  key. The designer and the light model each pick one, and the model name at
  the top of the AI panel switches either of them without opening Settings.
- **The map draws the level's roads and railways** - the track on its
  embankment, the train bridge, fence runs and power lines, each as wide as
  the model laid along it - and the 3D close-up lays them on the ground too.
- **In the 3D close-up:** an *Edit* button holds the mouse free instead of
  holding Alt, **Delete** takes the selected thing away, **Ctrl+C** and
  **Ctrl+V** copy it to where the view is aimed, and the view stays open when
  what it was on is taken away.
- **Trash:** take one mission out of it, or empty it.

### Changed

- **The check list says what Apply would refuse.** The server's dry run of the
  build keeps the build's own verdict, and the list shows its errors word for
  word, so a mission the check calls clean is one Apply takes. New walkway
  points are tested against the walls and fences the mission has, as Apply
  tests them.
- **On a narrow window** the map's tools stay on one row and fold into menus.
- **The studio reads your game once more** when it first starts after this
  update: the level data now holds the doors and lifts of the game's own
  buildings, and the roads and railways the map draws.

### Fixed

- **Guards no longer stand in the sky.** The game walks every guard to his
  walkway graph when the mission starts; with no walkway at his own height he
  walked off to the nearest one there was - on an empty map, up to where a
  building's floor used to be. A guard is never given walkways on another
  floor now, and both the check list and Apply refuse one that is.
- **Guards no longer end up in a tunnel.** Walkway points count only near the
  height of the spot, and a walkway that has to climb starts from one on the
  ground.
- **The check list counted no problems at all**, because it looked for them
  under a name its rows never carried.
- **Eight models were invisible in 3D** once their textures arrived, among
  them Eagle's Nest's fortress walls: the textured reader took a 2 in a
  model's header to mean a character and read the rest wrong.
- **A walkway graph may hold 999 points, not 100** - the build makes its file
  bigger as it needs to, and the check list knew nothing of it.
- **A guard moved onto other walkways** (into a building, say) takes that
  graph, and a patrol that can no longer be walked is dropped with a note.

## 1.0.3

Ground of any height, and the game's mission list in your hands.

### New

- **Mountains, hills and valleys of any size.** The game's height maps move
  the ground about 4 m at most. Where you shape it further than that, the
  studio now builds the level's terrain itself again there, so there is no
  height limit. Raise, Lower, Level and Ramp take any height, and a big change
  gets a wider slope of its own.
- **A brush for the ground:** Raise, Lower, Smooth, Flatten, Roughen and
  Erase, up to 600 m wide, with a soft, even or hard edge.
- **Big shapes to stamp:** Mountains (a click places one, a drag places a
  range), Hills, Plateau, Crater and Valley, each with small, mid and high
  presets. No two stamps come out the same.
- **Remove.** Drag round a hill and it is replaced by the ground around it.
- **Light and shade follow the new ground.** The level's baked light is redone
  over what you changed, so a new mountain has a lit side and a shaded side,
  and one you took away leaves no shadow behind.
- **A terrain budget.** The game holds a fixed amount of terrain, and a bar in
  the Ground panel shows how much of it your mission uses. A mission that
  would need more is stopped before Apply, with what to make smaller.
- **The AI designer shapes ground too:** it can stamp mountains, ranges and
  valleys, and remove hills.
- **Copy details.** Apply's log can be selected, and a button under it copies
  the whole log, with the studio's version on top, ready for a bug report.

### Changed

- **The missions in your game, as the game lists them.** The studio shows
  every mission in slot 15 and up, in the game's order. A new mission goes
  after the last one, missions can be reordered, and one can be taken out of
  the game (its folder is kept in `backups/slots/removed`). The game's chain
  from one mission to the next is kept whole through all of it.

### Fixed

- **A mission from a blank map applies.** Its objectives went into the level
  script in the wrong place, and the script failed to compile (*unexpected
  ','*). An objective that belongs to the level's own story, which a blank map
  does not have, is now pointed out with what to do instead of failing.

## 1.0.2

Fixes for 1.0.1's new top bar and 3D view.

### Fixed

- **The mouse looks around in the 3D view.** The desktop app refused the
  browser's request to hold the mouse, so the view only moved while Alt was
  held. It is allowed now: click in the view, then move the mouse.
- **Menus and dialogs are on top.** The Mission and Help menus went under the
  map's toolbar and under the 3D view, and Settings opened behind the 3D view.
  Everything that drops down, pops up or opens over the studio is above the map
  and the 3D view now.

### Changed

- **Settings, About** lists its links one a line, each with what it is,
  instead of a row of buttons.

## 1.0.1

Fixes found by testing on a copy of the game as it shipped, a free camera for
the 3D view, and new Settings.

### Fixed

- **Your missions show in the game's list on a fresh install.** The game only
  offers the missions a player has reached, which on a new install is mission 1
  alone, so a mission in slot 15 was installed and never offered. Apply now
  lets the game's list reach your mission, through the one line of the game's
  settings (`config.qvm`) that says how far it goes, backed up first. Nothing
  you reached playing is taken away.
- **Switching to another copy of the game.** Changing the game folder now
  connects the new copy properly, with a reference copy of its levels and its
  level data, and each mission shows as in the game only in the copy it was
  applied to. Before, a mission kept the slot number it had in the old game:
  Apply failed with *slot belongs to another mission*, and *Remove from the
  game* could have taken out another mission's slot.
- **No jump when Alt is pressed.** The desktop app's hidden menu bar came up
  with every Alt, shifting the whole studio during an Alt+drag. It is gone; what
  it held is in the new **Help** menu.

### New

- **3D from the top bar.** **Map | 3D** in the middle of the top bar; 3D starts
  just behind the player start, looking the way the player faces.
- **A free camera in 3D.** The mouse looks around, W A S D fly, easing in and
  gliding to a stop. Hold **Alt** to edit: click to select, **Alt+drag** moves
  anything, **Shift+Alt+drag** lifts or lowers it. The range is a slider, and
  starts at 60 m.
- **New Settings.** A page each for the game (with **Browse**, and the folder
  checked as you pick it), the AI designer, the light model, updates, and about.
- **Local models.** Each model is **OpenAI** or **OpenAI-compatible** (LM
  Studio, vLLM, Ollama, OpenRouter), with its server's address and **context
  window**: requests are fitted into it, so a long chat no longer overflows a
  local model.
- **A new look** for the top bar, the buttons and the menus, with the logo.
- Text is no longer selected by accident; the AI designer's chat still can be.

## 1.0.0

The first public release: a mission studio for *Project I.G.I.: I'm Going In*,
as one Windows installer. It needs nothing else, no Python and no other tool
for the game, and it ships no game files: everything it shows is read from your
own copy of the game.

### What's in it

- **The map computer.** Design on the green map from the game: contours,
  buildings from above, every guard and pickup as a symbol. Zoom, drag, place.
- **Guards that patrol.** Soldiers, snipers and officers, their routes drawn on
  the walkways, how far they see and how hard they fight, with sight lines
  that show what they cover.
- **Objectives and events.** Destroy, steal, reach, rescue, survive, chained
  with triggers so doors open and reinforcements arrive when you say.
- **Cameras and alarms.** Security cameras with their sweep on the map, alarm
  panels, sirens, and who comes running.
- **Ground and buildings.** Raise, flatten and paint the terrain, place
  buildings, fences, towers and trees, and check it all in a 3D close-up.
- **The AI designer.** Ask for a change in plain words. It reads the map, makes
  the changes in the studio, and lists every one for you to keep or undo. It
  uses your own OpenAI key, encrypted for your Windows account.
- **Its own compiler.** The game's mission scripts are read and written by the
  studio itself: all 884 of them round-trip byte for byte. The IGI ToolKit is
  no longer needed.
- **The 14 originals stay untouched.** The studio keeps a checked reference
  copy of the levels, builds every mission from it, and writes only into its
  own mission slots, 15 and up.
- **A first run that sets itself up.** It finds the game (registry, GOG, Steam,
  the usual folders), checks the build, makes its reference copy and reads the
  level data, in a few minutes.
- **Updates.** From this release on, the studio looks for new versions itself.
  An installed studio updates when you close it; Settings, Updates turns the
  check off.

### Good to know

- Windows 10 and 11, 64-bit.
- Tested on two copies of the game: retail 1.1 as it shipped, and retail 1.1
  with a texture pack. Both are known builds. GOG and Steam copies should work
  too, because missions are built from whichever copy you connect, but if yours
  does something odd, please
  [open an issue](https://github.com/NaumanHSA/project-igi-studio/issues).
- This release is not signed yet. Signing through SignPath Foundation follows
  in a later release.
