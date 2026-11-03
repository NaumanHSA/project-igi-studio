# Designing a mission in Project IGI Studio

How to make a mission that plays well and looks like it belongs in the game. The
person is watching the studio as you work, so go in steps they can follow.

## The game

Project IGI is about one man getting into a guarded place, mostly on foot, with few
weapons and a map computer. Good missions are about reading a place from a distance,
finding the way in, and being in trouble when the alarm goes. Guards see far and shoot
well. There is no saving during a mission, so a mission should be fair: a careful
player can get through it first time, and an alarm is bad news rather than the end.

## How to work

1. **Look first.** `studio_status`, `list_levels`, then `screenshot_map` of the level
   you are thinking of. For a mission from scratch, use `create_mission` with
   `from: empty`: the level's ground, sky and walkways, with nothing built on it.
2. **Look at the ground.** `screenshot_map` with `show: ["walkways"]` shows where guards
   can walk. `ground_heights` tells you what is flat and what is steep. Put things where
   the land helps: a camp on a flat, a sniper on a rise, the way in along a gully.
3. **Plan, and show the plan.** `propose_plan`: the idea in two lines, 3 to 6 areas with
   their real coordinates, the objectives, the events, the way through and another way.
   Then stop and ask the person in your conversation. Change it with `update_plan`.
4. **Build one area at a time.** `checkpoint` first. Then ground, walkways, buildings,
   fences and gates, guards, patrols, cameras and alarm parts, pickups. Prefer `batch`:
   it is faster and one undo step.
5. **Look at every area** before the next: `screenshot_map` close up, `screenshot_3d`
   with `orbit`, and at eye level with `from` (1.7 m above the ground). If it looks wrong,
   it is wrong. Report it with `plan_progress`.
6. **Finish:** objectives, events, `write_texts`, then `check_mission` and
   `stealth_check` until they are clean.
7. **Put it in the game** with `apply_to_game` when the person wants to play it.

## What makes a place look right

- Real places have a reason. A compound has a gate, a road to the gate, a fence all the
  way round, and buildings that face each other or the road. Nothing stands alone in a
  field without a reason.
- Fences join up. A gap in a fence is a way in, so make it on purpose or close it.
- Things stand on level ground. Use `shape_ground` under a building before placing it,
  and check it in 3D: a building on a slope floats on one side and is buried on the other.
- Clusters, not grids. Put things close together with space between clusters, and leave
  open ground to cross, because open ground is what the player is afraid of.
- Height matters. Towers need a line of sight, and ridges hide things.

## What makes it play well

- **Two ways in**, at least: one obvious and guarded, one harder to find.
- **Guards with jobs.** Some stand at posts, some patrol, some watch from towers. Patrols
  need walkways (`add_walkways`), and they should leave gaps a patient player can use.
- **Enough, not many.** A small post has 3 to 6 guards and a base 15 to 30. Every guard
  costs the player time and health, and the game can hold at most 128 people.
- **Alarm with consequences.** Cameras and sirens that bring reinforcements make stealth
  worth it. Give the player a way to deal with them.
- **Objectives in a sensible order,** across the map and at different heights, with the
  hardest one last. At most 6: the map computer shows no more.
- **Weapons and ammo** where a player who explores would look. Don't hand out everything
  at the start.
- **A way on foot** from the player's start to every objective. `stealth_check` tells you
  how exposed it is.

## Budgets the game holds you to

The game keeps fixed lists and stops with a fatal error if one fills up. `check_mission`
counts them, and the build refuses a mission that goes over.

| What | Most |
|---|---|
| People (guards and the player) | 128 |
| Map computer markers and labels | 32 |
| Moving, exploding, watching things | 240 |
| Doors, switches, terminals, and the like | 512 |
| Pickups | 256 |
| Fences and mines | 64 |
| Security cameras | 64 |
