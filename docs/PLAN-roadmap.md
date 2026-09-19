# Plan: the roadmap, item by item

Written 2026-09-18 after going through every idea in [ROADMAP.md](ROADMAP.md)
against the studio's code and the game's own files. For each: what is there
already, what the game offers for it (with the task parameters from
[TASK-PARAMETERS.md](TASK-PARAMETERS.md), collected from every
`Task_DeclareParameters` in the 14 levels), what gets built, and what can only
be proven in the game (**in game**).

## What the research changed

- **The game declares every task's parameters by name** at the top of each
  level's `objects.qsc`. That turned several "needs research" items into small
  steps:
  - `Door`: *Locked expression*, *Open door expression*, *Close door
    expression*, *Pickable* and *Pick lock time*. Locked doors need no new
    format at all.
  - `LevelFlow`: *Interface timer enabled* and *Max level play time*. Level 7
    ships with a 1200 s limit: a time limit is a built-in feature.
  - `RainEffect`: *Is Rain* (false is snow), *Is Active* (an expression) and
    *Rain Alpha* (how heavy). `FlatSky`: *Fog Amount*, *Distance*, *Fog
    Color* and the sky dome's colours.
  - Guard scripts: `AIFunction_SetViewLength(m)` (how far he sees, 20 to 180
    in the shipped scripts) and `AIFunction_SetViewGamma(deg)` (his field of
    view), `AIFunction_SetInvulnerability`, `AIAction_PlayAnimation(n)` at idle.
- **Difficulty is global, not per mission.** The menu has *Select Difficulty*,
  and `common/ai/settings.qsc` holds a `HumanAIConfigItem` per AI type and
  difficulty (`GD_1` to `GD_3`: accuracy, damage, reaction times, grenades).
  No expression can test the difficulty, and that file is shared by every
  mission (changing it would change the built-in ones, which we never touch).
  So item 5 cannot be done per mission. What a mission *can* do already: the
  AI type of each guard picks his row in that table, so a sniper type or a
  patrol type is harder or easier at every difficulty.
- **Expressions the game understands** (counted over the 14 levels), the
  vocabulary for events: `AreaActivate_N.nActive`, `Switch_N.isLastPressed`,
  `HumanSoldier_N.isDead`, `Terminal_N.isHacked`, `GenericPickup_N.isPickedUp`,
  `GunPickup_N.isPickedUp`, `ExplodeObject_N.isExploded`, `Car_N.isExploded`,
  `AlarmControl_N.isAlarm`, `SCamera_N.isDetection`, `HumanAI_N.isDetection`,
  `Door_N.isOpen` / `isClosed` / `isPicked`, `LevelTimer_N.nTick`,
  `StatusMessage_N.isSendt`, `EditVariable_N.nValue`, `HumanPlayer_0.isDead`,
  `Cabinet_N.isSearched`, `GAME_FREQUENCY` for seconds.

## Status of each idea

| # | Idea | Before | Now |
|---|---|---|---|
| 1 | Events | mostly built | **Phase 2** |
| 2 | More objective types | partly there | kill, kill all, collect, reach, hack, destroy and *fail on alarm* exist; **time limit** in Phase 1 |
| 3 | Locked doors with keys | needs research | research done; **Phase 3** (a switch, a terminal, an event or a picked lock opens it) |
| 4 | Per-guard tuning | needs research | **Phase 1**: sight range, field of view, alarm answering exists; accuracy stays with the AI type |
| 5 | Difficulty levels | needs research | **not possible per mission** (see above) |
| 6 | Walk mode in 3D | small step | **Phase 4** |
| 7 | Navigation in 3D | small step | **Phase 4** |
| 8 | Stealth route finder | mostly built | **Phase 6** |
| 9 | Map computer preview | mostly built | **Phase 7** |
| 10 | Playability check | mostly built | **Phase 6** |
| 11 | Paint the ground | mostly built | **Phase 10**, after the in-game checks of the ground work |
| 12 | Weather and atmosphere | needs research | research done; **Phase 1** (rain or snow, fog) |
| 13 | Ready-made compounds | mostly built | **Phase 8** |
| 14 | Characters at ease | needs research | **Phase 11** (decoding BOAN) |
| 15 | Test from here | small step | **Phase 5** |
| 16 | Play-session replay | mostly built | **Phase 9** |
| 17 | Mission packages | small step | export and import **already exist** (Mission menu); Phase 9 adds the briefing and campaigns |
| 18 | Describe it, get a draft | new | **Phase 12**, last, rule-based |

## Phase 1 - Small wins the research opened (done 2026-09-18)

### 1a. Time limit (idea 2)

- Objectives panel: *Time limit* (off, or minutes and seconds) and *Show the
  timer*.
- Build: the level's `LevelFlow` gets *Interface timer enabled* and *Max
  level play time* (seconds). Plan keys `timeLimit` (seconds, 0 = none) and
  `showTimer`.
- **In game**: the mission fails when the time runs out (as level 7), and the
  timer shows.

### 1b. How far a guard sees (idea 4)

- Guard inspector (yours): *Sees* (metres, 20 to 180, default the game's) and
  *Field of view* (degrees). The editor's sight cones and the coverage layer
  use the same numbers, so the map shows what the game will do.
- Build: `AIFunction_SetViewLength(n)` and `AIFunction_SetViewGamma(n)` in the
  guard's `AIEVENT_CREATE` handler, next to `SetAlarmControlID`.
- The level's own guards keep their scripts (an AI script is shared by type and
  is the level's). **In game**: a guard with 20 m does not see the player at 40.

### 1c. Weather (idea 12)

- A *Weather* section (Mission menu, next to the objectives' settings): *Rain*,
  *Snow* or *None*; *Heavy* (the alpha, 0.05 to 0.35); *Fog*: the sky's fog
  distance (40 m foggy to 250 m clear) and fog colour.
- Build: rewrite the level's `RainEffect` (or add one inside the level's sky
  container when the level has none) and `FlatSky` parameters 1 to 4 in place.
- **In game**: rain or snow falls; the fog moves in.

## Phase 2 - Events (idea 1, done 2026-09-18)

A panel of rules, **When** something happens, **Do** something.

Built as planned, except: *an objective is done* is not a trigger (the
things objectives watch, a guard dying, an item picked up, an area reached,
are triggers themselves), and an alarm is raised by a short pulse rather than
the latch, so switching the alarm off holds.

- **When** (each one an expression, with the task it needs added by the build):
  - the player enters an area (a circle or box drawn on the map:
    `AreaActivate` with `CRITERIA_HUMAN0`),
  - a switch is pressed (a shipped or own `Switch`),
  - a guard dies (`HumanSoldier_N.isDead`),
  - a terminal is hacked, an item is picked up, something blows up,
  - the alarm goes off (`AlarmControl_N.isAlarm`),
  - a camera sees the player,
  - an objective is done (its `StatusMessage.isSendt`),
  - N seconds after the start or after another event (`LevelTimer`).
- **Do**:
  - show a message (`StatusMessage`, the mission's own text),
  - raise an alarm (the event goes into the `AlarmControl`'s trigger),
  - send guards (a `GuardGenerator` with a guard of the mission's, spawning
    when the event fires, up to N times),
  - open or unlock a door (Phase 3 wires the door's expressions),
  - fail the mission (joins `LevelFlow`'s *Failed*),
  - start a timer for another event.
- Every event fires once: an `EditVariable` latch (*Add* when the condition
  first holds), so an area you walk out of does not un-fire it.
- Map: an event's area and the things it names are drawn when it is selected.
- **In game**: each kind of trigger and action.

## Phase 3 - Doors (idea 3, done 2026-09-18)

- A door in the level (the `Door` tasks are already extracted, type `door`)
  gets an inspector section: *Locked* (never, until a switch is pressed, until a
  terminal is hacked, until an event fires) and *Lock can be picked* (seconds).
- Build: the door's *Locked expression* becomes `!(<condition>)`, its *Pick
  lock time* and *Pickable* set; a door with task id -1 gets an id of the
  mission's (the expression needs to name it only when others refer to it).
- Keys: the game has no keycard item; *until an item is picked up* uses any
  pickup (`GunPickup` / `GenericPickup.isPickedUp`) as the key.
- **In game**: the door stays shut, then opens.

## Phase 4 - The 3D close-up: walking and walkways (ideas 6 and 7, done 2026-09-18)

- Built as planned. Walking starts on the floor under the camera (not in front
  of the item, which could be against a wall), and reads the ground from its
  height grid and floors only from the things near you, so it stays smooth.
- **Walk** (a button, and W A S D once in it): the eye at 1.7 m over the floor
  under it, following floors, stairs and the ground (the close-up already finds
  the floor under a point); walls stop it (a ray ahead at knee and chest).
  Mouse looks around as now. What a guard sees is left for the coverage layer.
- **Walkways**: the navmesh nodes and links of the level and the mission drawn
  in the close-up (small posts and lines), the selected guard's patrol route in
  gold; *Add a walkway point* puts one on the floor clicked (an own node,
  linked to the nearest one of its graph, as on the map).

## Phase 5 - Test from here (idea 15, done 2026-09-18)

- Right-click on the map (or the 3D close-up): *Test from here*. It applies the
  mission with the player start moved to that spot (the saved plan is not
  changed) and starts the game (`IGI.exe` in the game folder). The game still
  asks for the mission in its menu: the toast says which one.
- Server: `POST api/missions/<id>/apply {start:{x,y,z,gamma}}` and
  `POST api/launch`.

## Phase 6 - Routes: can the player get there, and unseen? (ideas 8 and 10, done 2026-09-18)

- A walk grid (1 m): ground not steeper than 40°, not under a masonry wall or
  a wire fence. Built: a building is a slow way through (its doors are not
  known, and treating it as a wall made the control tower of level 3
  unreachable, which it is not); water is not known either.
- **Playability** (in the check list before Apply): every objective's target is
  reachable from the start on that grid; an objective on a roof with no way up
  is a warning, never an error (the player can climb and jump where the grid
  cannot).
- **Stealth route**: a least-seen path from the start to each objective over the
  same grid, weighted by the coverage layer (how many guards and cameras see
  each cell). Drawn on the map, with how much of it is seen; a rough difficulty
  for the mission from the sum.

## Phase 7 - Map computer preview (idea 9, done 2026-09-18)

- A view mode that draws only what the game's map computer shows: the map
  image, the objective markers and their numbers, the labels of buildings
  (`ComputerHilight`), within the 32-marker limit, with the counts.

## Phase 8 - Ready-made compounds (idea 13, done 2026-09-18)

- A tool: drag a rectangle, get a fence around it with a gate on the side
  nearest the road, watchtowers at the corners, a searchlight and two guards
  on a patrol round it, as a group of the mission's own things to edit.
- Built as a right-click sheet (size, fence or wall, towers, floodlight,
  guards). The way in faces the player's start (the level has no roads in
  its data), and is an opening: the gate model is a closed static prop. The
  guards stand at the way in: a patrol round a new fence would need walkway
  points linking across it, which the build rejects.

## Phase 9 - Replay and sharing (ideas 16 and 17, done 2026-09-18)

- **Replay**: the live view records the run (position every 0.5 s, when the
  alarm went off, where the player died) to `missions/custom/<id>/runs/`; a
  run plays back on the map with a slider. Built with the position only: the
  live reader finds the player's position in the game's memory, not the
  alarm or his death. Where he was in view comes from the coverage layer.
- **Packages**: export already writes one file with the plan, name and
  description. Add the briefing text and objectives' texts (in the plan
  already) and a *campaign*: several missions installed into consecutive slots
  in one go. Built as a pack file of several missions, imported as a set;
  each mission keeps its own slot when applied.

## Phase 10 - Paint the ground (idea 11, done 2026-09-18)

- A *Paint* tool on the Ground bar: pick one of the level's ground materials
  and paint cells. Build: the slot's own `terrain.bit` (a copy, as with
  `terrain.hmp`). Waits until the shaped ground has been checked in game, since
  it writes the same folder.

## Phase 11 - Characters at ease (idea 14, done 2026-09-18)

- Decode the skeleton animations (`BOAN`: rotation keys per bone) from
  `common/anims`, pose guards in the close-up with the first frame of their
  standing animation instead of the bind pose.
- Decoded: each skeleton file holds 122 to 190 animations; per bone a BORH
  (key count) and BORD (13 floats a key: quaternion x, y, z, w, time, two
  tangent quaternions), root translation keys in BOTD (10 floats: x, y, z,
  time, tangents). World rotation = parent's times own, taken as stored.
  Animation 0 of each file is standing with a rifle; all characters (map
  sprites, previews, the 3D close-up) are posed with it. Non-character models
  are byte for byte as before.

## Phase 12 - Describe it, get a draft (idea 18, done 2026-09-18)

- A text box: words map to things the studio can already place (a number and a
  kind of guard, "sniper", "camera", "hack the terminal", "escape by the north
  gate" to a reach objective at the yard's north edge), laid out round the
  level's own buildings. Rule-based, offline, a starting point to edit.

## Where it stands (2026-09-18)

Every phase is built, one commit each. Built but **to be confirmed in game**:
events, doors, the time limit, rain or snow and haze, painted ground, a
guard's own sight, and one real *Test from here*. Not possible: difficulty
per mission (idea 5).

## Order and commits

One commit per phase (or part), README updated with each. Phases 1 to 5 carry
the value; 6 to 9 build on what exists; 10 to 12 are the long tail.
