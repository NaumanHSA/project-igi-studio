# Ideas for what comes next

Collected 2026-09-18, after the 3D close-up. Each idea says how much of it the
studio can already do, from what has been decoded so far:

- **mostly built**: the pieces work already, this puts them together;
- **small step**: builds directly on something that exists;
- **needs research**: needs a part of the game files not yet worked out;
- **new**: nothing like it in the studio yet.

The top three picks are at the end. **The plan for all of them, with what the
research found, is in [PLAN-roadmap.md](PLAN-roadmap.md)** (2026-09-18). All but
idea 5 (not possible per mission) are built; see the plan for what still needs
checking in the game.

## Making missions play better

1. **Events** (*mostly built*). A simple "when this happens, do that" panel:
   when the player enters an area, send in guards, sound the alarm, open a
   gate, show a message, start a timer. AreaActivate, StatusMessage,
   GuardGenerator and the alarm expressions already do this for objectives
   and alarms; this puts them in the user's hands.
2. **More objective types** (*partly there*). Destroy an object, hack a
   terminal, finish within a time limit, don't raise the alarm, reach the
   extraction point.
3. **Locked doors with keys** (*research done: the Door task has locked, open
   and close expressions and a pickable lock*). A door that opens only
   after a switch is pressed or a keycard is picked up.
4. **Per-guard tuning** (*research done: sight range and field of view are
   script calls; accuracy follows the AI type*). How far a guard sees and hears,
   how accurate and how alert he is. Richer patrols: waits, look-at points,
   stretches he runs.
5. **Difficulty levels** (*not possible per mission: the game's difficulty is
   one global table per AI type, shared by every mission*). Different guards for easy,
   normal and hard in one mission.

## Seeing it before playing it

6. **Walk mode in 3D** (*small step*). Walk the level at eye height with the
   arrow keys, standing on floors and stopped by walls, and see what each
   guard would see along the way.
7. **Navigation in 3D** (*small step*). Guard walkways (navmesh nodes and
   links) and patrol routes drawn in the 3D close-up, and walkway points added
   on building floors there - much easier indoors than on the flat map.
8. **Stealth route finder** (*mostly built*). The coverage map already knows
   what every guard and camera watches: find the least-seen path from the
   start to each objective, and give each mission a rough difficulty score.
9. **Map computer preview** (*mostly built*). Show exactly what the in-game
   map computer will show: markers, labels, objective numbers.
10. **Playability check** (*mostly built*). Before Apply: can the player
    actually reach every objective along the walkways? Is any objective
    impossible?

## Shaping the world

11. **Paint the ground** (*mostly built*). The level's ground materials and
    their masks (terrain.bit, TextureModifier, terrain.qvm) are understood:
    paint dirt roads, gravel yards or snow patches with the Ground brush.
12. **Weather and atmosphere** (*research done: RainEffect does rain or snow,
    FlatSky the fog*). Fog distance, rain or
    snow, sky and ambient sound per mission.
13. **Ready-made compounds** (*mostly built*). Draw a rectangle and get a
    fenced compound with gates, watchtowers, searchlights and guards, as a
    starting point to edit.
14. **Characters at ease** (*needs research*). Pose characters from the
    game's own idle animation (the BOAN rotation keys in common/anims)
    instead of the bind pose, an A-pose.

## Testing and sharing

15. **"Test from here"** (*small step*). Apply the mission, start the player
    right at the selected spot, and launch the game - for checking one room
    without playing through.
16. **Play-session replay** (*mostly built*). Record a run through the live
    view and replay it on the map: the path taken, where the player was
    spotted, where he died.
17. **Mission packages** (*small step*). Export a mission as one file others
    can import, with its name and briefing text; chain several missions into
    a campaign.
18. **Describe it, get a draft** (*new*). Type a mission in words - "night
    raid on the radar station, two snipers, hack the terminal, escape by the
    north gate" - and get a first plan to refine.

19. **AI designer** (*built*, 2026-09-18, [PLAN-ai.md](PLAN-ai.md)). A chat on
    the right edge with a model (OpenAI, or any compatible server) that
    suggests missions for the level and builds them on the map while you
    watch, through the studio's own editing (25 tools), with Stop and undo.
    Next: let it read the live view of a play-through, and shape the ground.

## Top three picks

- **Events (1)**: it turns static setups into real missions.
- **Walk mode and navigation in 3D (6, 7)**: they build directly on the 3D
  close-up and fix the hardest part, guard routes inside buildings.
- **"Test from here" (15)**: much faster checking in the game.
