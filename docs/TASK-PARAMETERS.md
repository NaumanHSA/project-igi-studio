# Task parameters

Every task type the game's QSC scripts declare (`Task_DeclareParameters`), with
its parameters in order, collected from the QEditor library of the 14 levels,
the menus and the AI settings. *Used* is how many times the 14 levels use it.
Some declarations pair names and types the wrong way round (SCamera from
its 9th parameter); they are listed as the game has them.

## AIGraph  (used 295)

1. Graph position: `ObjectPos`
2. Update: `PushButton`
3. Graphdata: `Graph`
4. Node cover midoffset: `Real64`
5. Node cover topoffset: `Real64`
6. Max height difference between linked nodes: `Real64`
7. Width of node links: `Real64`
8. Link maximum distance to ground: `Real64`
9. Use precise link method (SLOW!): `bool8`
10. Precise link method step value: `Real64`

## AIStationaryGunHolder  (used 9)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Holder model: `String16`
4. Viewcone Alpha: `Degrees`
5. Viewcone Gamma: `Degrees`
6. Viewcone Length: `Real32`
7. On expression: `VarString`
8. Team expression: `VarString`

## AddAmmo  (used 27)

1. ID: `EnumString32`
2. Ammo: `Int16`

## AlarmControl  (used 15)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Destroyed model: `String16`
5. Damage scale: `Real32`
6. Explosion radius: `Real32`
7. Explosion falloff radius: `Real32`
8. Explosion damage scale: `Real32`
9. Explosion delay: `Real32`
10. Explosion fragments: `Int32`
11. Explosion fireballs: `Int32`
12. Explosion expression: `VarString`
13. Explosion sound: `String16`
14. On Expression: `VarString`
15. Hack Time (s): `Real32`
16. Trigger Expression: `VarString`
17. Alarm Expression: `VarString`

## AlarmLight  (used 16)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. On expression: `VarString`
4. On model: `String16`
5. Off model: `String16`
6. Destroyde model: `String16`
7. On sound: `String16`
8. Explode sound: `String16`

## AmbientArea  (used 162)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Size: `Real64x3`
4. Min Delay: `Real64`
5. Random wait: `Real64`
6. SoundDef: `String256`

## AmmoPickup  (used 71)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. ID: `EnumString32`
4. Ammo: `Int16`

## AnimTask  (used 67)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. TargetID: `Int32`
4. Run: `VarString`
5. Initial run: `bool8`
6. AnimData: `AnimData`

## AreaActivate  (used 171)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Dimensions: `Real32x3`
4. Criteria: `VarString`

## AsciiBox  (used 0)

1. Font Resource: `String32`
2. Text File: `String32`
3. Width: `Int32`
4. Height: `Int32`

## Binocular  (used 14)

1. ID: `EnumString32`
2. Slot: `Int16`

## BinocularOverlayHolder  (used 1)

1. Visible expression: `VarString`

## Building  (used 503)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`

## Cabinet  (used 5)

1. Position: `ObjectPos`
2. Orientation: `Angle`
3. Model: `String16`
4. Search Time (s): `Real32`

## Car  (used 31)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Original Thrust: `Real32`
4. Speed: `Real32x3`
5. Model: `String16`
6. Collision detection: `bool8`
7. Force Z: `bool8`
8. Open door: `VarString`
9. Can fire: `VarString`
10. Play sound: `VarString`
11. ViewCone Alpha (degrees): `Degrees`
12. ViewCone Gamma (degrees): `Degrees`
13. ViewCone Length (meter): `Real32`

## CarAI  (used 16)

1. Car ID: `Int32`
2. Graph ID: `Int32`
3. Route ID: `Int32`

## ComputerHilight  (used 232)

1. Position: `ObjectPos`
2. Hilight: `VarString`
3. TaskID: `String256`
4. Click to select sprite: `DropDownCombo`
5. Marker mesh: `String32`
6. Marker color: `String32`
7. Title text resource: `String256`
8. Info text resource: `String256`

## ConditionalContainer  (used 204)

1. Condition: `VarString`
2. Run at start: `VarString`
3. Run at stop: `VarString`

## ConditionalSound  (used 384)

1. Condition: `VarString`
2. SoundDef: `String32`
3. Position: `ObjectPos`
4. Simple: `bool8`
5. OneShot: `bool8`
6. Relative to microphone: `bool8`

## CubeModifier  (used 15)

1. Position: `ObjectPos`
2. Level: `Int32`
3. Expression: `String256`

## CutScene  (used 45)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Run: `VarString`
4. Reset: `VarString`
5. Time delta (seconds): `VarString`
6. Start time (seconds): `Real32`
7. Initial run: `bool8`
8. Time scale: `Real32`
9. Viewport height factor: `Real32`
10. Viewport height factor fade in time: `Real32`
11. Viewport height factor fade out time: `Real32`
12. Time of day: `Real32`
13. Start expression: `VarString`
14. Stop expression: `VarString`

## DefineComputerObjective  (used 16)

1. Objectives Valid: `VarString`
2. Objective 1 Text Resource: `String32`
3. Objective 1 Link To Position: `Int32`
4. Objective 1 Complete Expression: `VarString`
5. Objective 1 Failed Expression: `VarString`
6. Objective 2 Text Resource: `String32`
7. Objective 2 Link To Position: `Int32`
8. Objective 2 Complete Expression: `VarString`
9. Objective 2 Failed Expression: `VarString`
10. Objective 3 Text Resource: `String32`
11. Objective 3 Link To Position: `Int32`
12. Objective 3 Complete Expression: `VarString`
13. Objective 3 Failed Expression: `VarString`
14. Objective 4 Text Resource: `String32`
15. Objective 4 Link To Position: `Int32`
16. Objective 4 Complete Expression: `VarString`
17. Objective 4 Failed Expression: `VarString`
18. Objective 5 Text Resource: `String32`
19. Objective 5 Link To Position: `Int32`
20. Objective 5 Complete Expression: `VarString`
21. Objective 5 Failed Expression: `VarString`
22. Objective 6 Text Resource: `String32`
23. Objective 6 Link To Position: `Int32`
24. Objective 6 Complete Expression: `VarString`
25. Objective 6 Failed Expression: `VarString`

## DialogWindow  (used 0)

1. X-Pos: `Int32`
2. Y-Pos: `Int32`
3. Width: `Int32`
4. Height: `Int32`
5. SwapKeys: `bool8`

## Dirlight  (used 14)

1. Affects terrain: `bool8`
2. Affects objects: `bool8`
3. Radiosity intensity: `Real32`

## DirlightKeyframe  (used 28)

1. Beta: `Angle`
2. Gamma: `Angle`
3. Front Color: `RGB`
4. Back Color: `RGB`
5. Time: `Real32`

## DiscardTerrain  (used 63)

1. Position: `ObjectPos`
2. Level: `Int32`

## Door  (used 535)

1. Position start: `ObjectPos`
2. Position stop X: `Real32`
3. Position stop Y: `Real32`
4. Position slider: `Real32`
5. Orientation: `Real32x9`
6. Model: `String16`
7. Max angle: `Real32`
8. Open time: `Real32`
9. Pickable: `bool8`
10. Pick lock time (s): `Real32`
11. Locked expression: `VarString`
12. Open door expression: `VarString`
13. Close door expression: `VarString`
14. Open sound: `String16`
15. Close sound: `String16`
16. Move sound: `String16`

## EditCamera  (used 470)

1. Position: `ObjectPos`
2. Alpha: `Angle`
3. Beta: `Angle`
4. Gamma: `Angle`
5. FOV: `Real32`
6. Duration: `Real32`
7. Link task ID: `Int32`
8. Update link continously: `bool8`
9. Target task ID: `Int32`
10. Update target continously: `bool8`
11. Smooth to next: `bool8`
12. Time of day (-1 means use default): `Real32`
13. FILTER: `EnumString32`
14. Noise: `Real32`
15. Filter color: `RGB`
16. Camera shake: `Real32`

## EditRigidObj  (used 5696)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Dirlight Angular Effect: `RGB`
5. Dirlight Ambient Effect: `RGB`

## EditVariable  (used 96)

1. Position: `ObjectPos`
2. Initial value: `Int32`
3. Add: `VarString`
4. Sub: `VarString`

## Elevator  (used 16)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. SplineObj taskid: `Int32`
5. Linear: `bool8`
6. Force orientation: `bool8`
7. Pos: `Real32`
8. Max speed: `Real32`
9. Speed inertia: `Real32`
10. Floor down: `VarString`
11. Floor up: `VarString`
12. Can start: `VarString`
13. Wanted floor 0: `VarString`
14. Wanted floor 1: `VarString`
15. Wanted floor 2: `VarString`
16. Wanted floor 3: `VarString`
17. Wanted floor 4: `VarString`
18. Wanted floor 5: `VarString`
19. Wanted floor 6: `VarString`
20. Wanted floor 7: `VarString`
21. Wanted floor 8: `VarString`
22. Wanted floor 9: `VarString`
23. Start sound: `String32`
24. Stop sound: `String32`
25. Move sound: `String32`

## ExplodeObject  (used 200)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Destroyed model: `String16`
5. Damage scale: `Real32`
6. Explosion radius: `Real32`
7. Explosion falloff radius: `Real32`
8. Explosion damage scale: `Real32`
9. Explosion delay: `Real32`
10. Explosion fragments: `Int32`
11. Explosion fireballs: `Int32`
12. Explosion expression: `VarString`
13. Explosion sound: `String16`

## Fence  (used 79)

1. Position: `ObjectPos`
2. Gamma: `Angle`
3. Model: `String16`
4. Electric Expression: `VarString`

## FlatSky  (used 14)

1. Fog Amount: `Real32`
2. Z Pos: `Real32`
3. Distance: `Real32`
4. Fog Color: `RGB`
5. SkyDome Snap Colours: `bool8`
6. SkyDome Angle: `Degrees`
7. SkyDome Top Colour: `RGB`
8. SkyDome Middle Colour 1: `RGB`
9. SkyDome Middle Colour 2: `RGB`
10. SkyDome Bottom Colour 1: `RGB`
11. SkyDome Bottom Colour 2: `RGB`

## FlatSkyLayer  (used 26)

1. Texture File Name: `String256`
2. Scale: `Real32`
3. X Speed: `Real32`
4. Y Speed: `Real32`
5. Alpha: `Real32`
6. Color: `RGB`

## Generator  (used 7)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Destroyed model: `String16`
5. Damage scale: `Real32`
6. Explosion radius: `Real32`
7. Explosion falloff radius: `Real32`
8. Explosion damage scale: `Real32`
9. Explosion delay: `Real32`
10. Explosion fragments: `Int32`
11. Explosion fireballs: `Int32`
12. Explosion expression: `VarString`
13. Explosion sound: `String16`
14. Run sound: `String16`
15. Shutdown sound: `String16`
16. On expression: `VarString`
17. Use backup timer: `bool8`
18. Seconds until power backup: `Real32`

## GenericPickup  (used 9)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`

## GenericTBA  (used 4)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Destroyed model: `String16`
5. Damage scale: `Real32`
6. Explosion radius: `Real32`
7. Explosion falloff radius: `Real32`
8. Explosion damage scale: `Real32`
9. Explosion delay: `Real32`
10. Explosion fragments: `Int32`
11. Explosion fireballs: `Int32`
12. Explosion expression: `VarString`
13. Explosion sound: `String16`
14. Explodable: `bool8`
15. On Expression: `VarString`
16. Activate Anim: `Int16`
17. Activate Time (s): `Real32`
18. Click to select sprite: `DropDownCombo`

## GlobalLight  (used 14)

1. Radiosity intensity: `Real32`
2. Texture filter ambient colour: `RGB`
3. Texture filter scale: `RGB`
4. Texture filter gamma: `Real32`

## GlobalLightKeyframe  (used 28)

1. Link All Sliders: `PushButton`
2. Ambient color terrain: `RGB`
3. Fog color terrain: `RGB`
4. Fog density terrain: `Real32`
5. Link setting terrain: `Int32`
6. Ambient color object category 1: `RGB`
7. Fog color object category 1: `RGB`
8. Fog density object category 1: `Real32`
9. Link setting object category 1: `Int32`
10. Ambient color object category 2: `RGB`
11. Fog color object category 2: `RGB`
12. Fog density object category 2: `Real32`
13. Link setting object category 2: `Int32`
14. Ambient color object category 3: `RGB`
15. Fog color object category 3: `RGB`
16. Fog density object category 3: `Real32`
17. Link setting object category 3: `Int32`
18. Ambient color object category 4: `RGB`
19. Fog color object category 4: `RGB`
20. Fog density object category 4: `Real32`
21. Link setting object category 4: `Int32`
22. Sky color: `RGB`
23. Water ambient: `RGB`
24. Water color: `RGB`
25. Time: `Real32`

## GuardGenerator  (used 82)

1. Generate guards: `VarString`
2. Max spawns: `Int32`

## Gun  (used 684)

1. ID: `EnumString32`
2. Slot: `Int16`

## GunDRAGUNOV  (used 20)

1. ID: `EnumString32`
2. Slot: `Int16`

## GunM16A2  (used 15)

1. ID: `EnumString32`
2. Slot: `Int16`

## GunMP5SD  (used 11)

1. ID: `EnumString32`
2. Slot: `Int16`

## GunPickup  (used 109)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. ID: `EnumString32`

## GunSPAS12  (used 44)

1. ID: `EnumString32`
2. Slot: `Int16`

## HeightMap  (used 24)

1. Position: `ObjectPos`
2. Level: `Int32`
3. Size: `Int32`
4. isEdit: `bool8`
5. Bitmap ID: `Int32`
6. NORMALSMOOTH: `Int32`
7. BLURSMOOTH: `Int32`

## Heli  (used 29)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Original Thrust: `Real32`
4. Speed: `Real32x3`
5. Model: `String16`
6. Collision detection: `bool8`
7. Force Z: `bool8`
8. Open door: `VarString`
9. Can fire: `VarString`
10. Play sound: `VarString`
11. ViewCone Alpha (degrees): `Degrees`
12. ViewCone Gamma (degrees): `Degrees`
13. ViewCone Length (meter): `Real32`

## HumanAI  (used 698)

1. AI Type: `String32`
2. Graph ID: `Int32`

## HumanAIConfig  (used 0)

1. Save all settings: `PushButton`

## HumanAIConfigItem  (used 0)

1. AI Type: `String256`
2. Difficulty: `String256`
3. Damage scale: `Real32`
4. Recoil threshold: `Real32`
5. Combat initial movement delay (in seconds): `Real32`
6. Combat movement delay (in seconds): `Real32`
7. Combat targeting timeout (in seconds): `Real32`
8. Combat tracking distance (in meters): `Real32`
9. Combat liedown mim distance (in meters): `Real32`
10. Combat evasive action probability: `Real32`
11. Combat evasive stand roll / liedown probability: `Real32`
12. Combat evasive kneel roll / liedown probability: `Real32`
13. Combat evasive stand roll side probability: `Real32`
14. Combat evasive kneel roll side probability: `Real32`
15. Combat firing hit probability at minimum range: `Real32`
16. Combat firing hit probability at maximum range: `Real32`
17. Combat Firing Max Number Of Rounds per sequence: `Int32`
18. Combat firing Aim precision: `Real32`
19. Combat firing minimum clip percentage: `Real32`
20. Combat firing random clip percentage: `Real32`
21. Combat firing minimum delay (in seconds): `Real32`
22. Combat firing random delay (in seconds): `Real32`
23. Combat firing minimum shot delay (in seconds): `Real32`
24. Combat firing random shot delay (in seconds): `Real32`
25. Combat grenade throw probability: `Real32`
26. Combat grenade throw when reload probability: `Real32`
27. Combat grenade minimum distance (in meters): `Real32`
28. Combat grenade maximum distance (in meters): `Real32`
29. Combat grenade minimum fly time (in seconds): `Real32`
30. Combat grenade random fly time (in seconds): `Real32`
31. Combat grenade minimum explode time (in seconds): `Real32`
32. Combat grenade random explode time (in seconds): `Real32`
33. Close Combat hit probability: `Real32`
34. Close Combat damage: `Real32`

## HumanPlayer  (used 14)

1. Position: `ObjectPos`
2. Gamma: `Angle`
3. Model: `String16`
4. Team: `Int32`

## HumanPlayerInput  (used 14)

1. Record: `bool8`
2. Playback: `bool8`
3. File: `String256`
4. Mapcomputer on expression: `VarString`

## HumanSoldier  (used 692)

1. Position: `ObjectPos`
2. Gamma: `Angle`
3. Model: `String16`
4. Team: `Int32`
5. Bone Heirachy: `Int32`
6. Stand Animation: `Int32`

## HumanSoldierFemale  (used 5)

1. Position: `ObjectPos`
2. Gamma: `Angle`
3. Model: `String16`
4. Team: `Int32`
5. Bone Heirachy: `Int32`
6. Stand Animation: `Int32`

## HumanSoldierRPG  (used 1)

1. Position: `ObjectPos`
2. Gamma: `Angle`
3. Model: `String16`
4. Team: `Int32`
5. Bone Heirachy: `Int32`
6. Stand Animation: `Int32`

## InputBox  (used 0)

1. Width: `Int32`
2. String Length: `Int32`
3. Get Data Script: `VarString`
4. Set Data Script: `VarString`
5. On Modify Script: `VarString`
6. Hide Input: `bool8`

## LODSettings  (used 14)

1. Distance to first switch, relative to object radius (Spline Objects): `Real32`
2. Distance to first switch, relative to object radius (Rigid Objects): `Real32`
3. Distance to first switch, relative to object radius (Bone Objects): `Real32`
4. Cutoff distance, relative to object radius (Spline Objects): `Real32`
5. Cutoff distance, relative to object radius (Rigid Objects): `Real32`
6. Cutoff distance, relative to object radius (Bone Objects): `Real32`
7. Degree to which radius affects LOD: `Real32`
8. Ideal radius: `Real32`

## LevelFlow  (used 14)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Start time: `Real32`
4. Complete: `VarString`
5. Failed: `VarString`
6. Interface timer enabled: `bool8`
7. Max level play time: `Real32`

## LevelTimer  (used 62)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. On: `VarString`
4. Reset: `VarString`
5. Initial run: `bool8`

## LightmapInfo  (used 481)

1. Texture scale: `Real32`
2. Passes: `Int32`
3. Hemicube resolution: `Int32`
4. Dirlight resolution: `Int32`
5. Gamma: `Real32`
6. Max radiosity per square meter: `Real32`
7. Indoors ambient light: `RGB`
8. Filename: `String16`

## ListBox  (used 0)

1. Sprite Resource: `String32`
2. Font Resource: `String32`
3. Width: `Int32`
4. Collect Items Script: `VarString`
5. Get Data Script: `VarString`
6. Set Data Script: `VarString`
7. Modify Data Script: `VarString`

## MenuFrame  (used 0)

1. Sprite Resource: `String32`
2. X-Pos: `Int32`
3. Y-Pos: `Int32`
4. Width: `Int32`
5. Height: `Int32`
6. LineUpMode: `Int32`
7. X-Spacing: `Int16`
8. Y-Spacing: `Int16`
9. Is Selectable: `bool8`

## MenuManager  (used 0)

1. Current menuscreen: `Int32`
2. Resource path: `String256`
3. isOwnDisplay: `bool8`

## MenuScreen  (used 0)

1. Background: `String32`
2. Frame x0: `Int32`
3. Frame y0: `Int32`
4. Frame x1: `Int32`
5. Frame y1: `Int32`
6. On Press Escape: `VarString`
7. On Init Data: `VarString`
8. On Change Data: `VarString`

## MenuText  (used 0)

1. Text Resource: `String32`
2. Font Resource: `String32`
3. ColourIndex: `Int32`
4. On Click Script: `VarString`
5. Click Sound Resource: `String32`

## MenuTextConditional  (used 0)

1. Text Resource: `String32`
2. Font Resource: `String32`
3. ColourIndex: `Int32`
4. isEnabled Expression: `VarString`
5. isVisible Expression: `VarString`
6. On Click Script: `VarString`
7. Click Sound Resource: `String32`

## MineField  (used 2)

1. Position: `ObjectPos`
2. Explode: `VarString`
3. Explosion radius (meter): `Real32`
4. Explosion falloff radius (meter): `Real32`
5. Explosion damage scale: `Real32`
6. Explosion delay (seconds): `Real32`
7. Explosion fragments: `Int32`
8. Explosion fireballs: `Int32`
9. Explosion sound: `String16`
10. Explode close to task ID: `Int32`
11. Explosion delay between explosions (seconds) -1: explode once: `Real32`
12. Snap explosion to ground: `bool8`

## MipMapControl  (used 14)

1. LOD blend: `bool8`
2. MipMap mode: `Int32`
3. LOD bias (Standard MipMapping): `Real32`
4. LOD bias (Trilinear MipMapping): `Real32`

## PatrolPath  (used 627)


## PatrolPathCommand  (used 3878)

1. Command: `Int32`
2. Command Parameter: `Int32`

## PictureBox  (used 0)

1. Width: `Int32`
2. Height: `Int32`
3. Collect Items: `VarString`
4. Get Active Picture: `VarString`

## PlaceExplosiveTBA  (used 2)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Destroyed model: `String16`
5. Damage scale: `Real32`
6. Explosion radius: `Real32`
7. Explosion falloff radius: `Real32`
8. Explosion damage scale: `Real32`
9. Explosion delay: `Real32`
10. Explosion fragments: `Int32`
11. Explosion fireballs: `Int32`
12. Explosion expression: `VarString`
13. Explosion sound: `String16`
14. Explodable: `bool8`
15. On Expression: `VarString`
16. Activate Anim: `Int16`
17. Activate Time (s): `Real32`
18. Click to select sprite: `DropDownCombo`
19. Activate radius (meters): `Real32`
20. Task ID to place: `Int32`

## Plane  (used 13)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Original Thrust: `Real32`
4. Speed: `Real32x3`
5. Model: `String16`
6. Gear: `bool8`
7. Canopy: `bool8`
8. Collision detection: `bool8`
9. Force Z: `bool8`
10. Play sound: `VarString`

## Radio  (used 2)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Destroyed model: `String16`
5. Damage scale: `Real32`
6. Explosion radius: `Real32`
7. Explosion falloff radius: `Real32`
8. Explosion damage scale: `Real32`
9. Explosion delay: `Real32`
10. Explosion fragments: `Int32`
11. Explosion fireballs: `Int32`
12. Explosion expression: `VarString`
13. Explosion sound: `String16`
14. Radio sound 0: `String16`
15. Radio sound 1: `String16`
16. Radio sound 2: `String16`
17. Radio sound 3: `String16`
18. Shutdown sound: `String16`
19. On expression: `VarString`

## RainEffect  (used 8)

1. Is Rain: `bool8`
2. Traceline start: `Real32`
3. Traceline end: `Real32`
4. Is Active: `VarString`
5. Rain Alpha: `Real32`

## RotatingObject  (used 3)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Rotate sound: `String16`
5. Degrees per second X-axis: `Degrees`
6. Degrees per second Y-axis: `Degrees`
7. Degrees per second Z-axis: `Degrees`
8. Acceleration, degrees per second X-axis: `Degrees`
9. Acceleration, degrees per second Y-axis: `Degrees`
10. Acceleration, degrees per second Z-axis: `Degrees`
11. Destructable: `bool8`
12. On expression: `VarString`

## SCamera  (used 48)

1. Holder Position: `ObjectPos`
2. Holder Gamma: `Angle`
3. Holder Model: `String16`
4. Camera Alpha: `Angle`
5. Camera Gamma: `Angle`
6. Camera Model: `String16`
7. Camera Destroyed Model: `String16`
8. Rotate Gamma Right (d): `Int16`
9. Rotate Gamma Left (d): `Int16`
10. Rotate Gamma Speed (d/s): `Int16`
11. Gamma Delay (s): `Real32`
12. Viewcone Alpha (d): `Int16`
13. Viewcone Gamma (d): `Int16`
14. Viewcone length (m): `Real32`
15. On Expression: `VarString`

## SCameraControl  (used 9)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Destroyed model: `String16`
5. Damage scale: `Real32`
6. Explosion radius: `Real32`
7. Explosion falloff radius: `Real32`
8. Explosion damage scale: `Real32`
9. Explosion delay: `Real32`
10. Explosion fragments: `Int32`
11. Explosion fireballs: `Int32`
12. Explosion expression: `VarString`
13. Explosion sound: `String16`
14. On Expression: `VarString`
15. Hack Time (s): `Real32`
16. Detection Expression: `VarString`

## ScrollListBox  (used 0)

1. Font Resource: `String32`
2. Collect Items Script: `VarString`
3. Get Data Script: `VarString`
4. Set Data Script: `VarString`
5. Width: `Int32`
6. Height: `Int32`
7. On Select Item: `VarString`

## Siren  (used 34)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Destroyed model: `String16`
5. Damage scale: `Real32`
6. Explosion radius: `Real32`
7. Explosion falloff radius: `Real32`
8. Explosion damage scale: `Real32`
9. Explosion delay: `Real32`
10. Explosion fragments: `Int32`
11. Explosion fireballs: `Int32`
12. Explosion expression: `VarString`
13. Explosion sound: `String16`
14. Working Sound: `String32`
15. Faulty Sound: `String32`
16. On Expression: `VarString`

## SlideBar  (used 0)

1. Sprite Resource: `String32`
2. Horizontal: `bool8`
3. Size: `Int32`
4. Get Data Script: `VarString`
5. Set Data Script: `VarString`
6. Modify Data Script: `VarString`
7. Carret Speed: `VarString`
8. Number of options: `Int32`

## Smoke  (used 74)

1. Position: `ObjectPos`
2. Alpha: `Angle`
3. Gamma: `Angle`
4. Number of Particles: `Int32`
5. Radius: `Real32`
6. Maximum Random Angle: `Angle`
7. Minimum Velocity: `Real32`
8. Maximum Velocity: `Real32`
9. Colour: `RGB`
10. Life Time: `Real32`
11. Fade Time: `Real32`
12. Fade Mode: `Int32`
13. Sprite index: `Int32`
14. Particle Size: `Real32`
15. Particle Size Delta: `Real32`
16. Minimum Rotation Speed: `Angle`
17. Maximum Rotation Speed: `Angle`
18. Intensity: `Real32`
19. Initial generate factor value: `Real64`
20. Generate factor: `VarString`
21. Move Particles: `bool8`

## SoundDefSoundEdit  (used 0)

1. SoundDef: `String32`
2. Sound: `String16`
3. Position: `ObjectPos`
4. Volume: `Real32`
5. Falloff Begin: `Real32`
6. Falloff End: `Real32`
7. VolumeChannel: `Int32`
8. PitchChannel: `Int32`
9. SoundChannel: `Int32`
10. MinPlayLength: `Real32`
11. Looped: `bool8`

## SplineObj  (used 44)

1. Linear Segments: `bool8`
2. Display waypoints: `bool8`
3. Snap Length: `bool8`
4. Automatic Orientation: `bool8`
5. Number of Matrices / Segment: `Int32`
6. Collision LOD: `Int32`
7. Position: `Real32x3`
8. Gamma Orientation: `Angle`
9. Dirlight Angular Effect: `RGB`
10. Dirlight Ambient Effect: `RGB`

## SplineObjWaypoint  (used 225)

1. Orientation: `Real32x9`
2. Position: `ObjectPos`
3. Waypoint Model: `String16`
4. Segment Model: `String16`
5. NumAreas: `Int32`
6. Align: `bool8`
7. Flip: `bool8`
8. Automatic Orientation: `bool8`

## StationaryGun  (used 20)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Holder model: `String16`
4. Weapon ID: `String32`
5. Max up angle: `Degrees`
6. Max down angle: `Degrees`
7. Max sideways angle: `Degrees`
8. Ammo: `Int32`

## StatusMessage  (used 383)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Send: `VarString`
4. Text: `VarString`
5. Sprite: `String256`
6. Sound: `String16`
7. Is send once: `bool8`
8. Cutscene message: `bool8`
9. Duration: `Real32`

## Switch  (used 110)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. On: `VarString`
4. Initial on: `bool8`
5. On model: `String16`
6. On pressed model: `String16`
7. Off model: `String16`
8. Off pressed model: `String16`
9. Destroyed model: `String16`
10. Destructable: `bool8`

## TagItemReal32  (used 0)

1. Name: `String256`
2. Value: `Real32`

## TagItemString16  (used 0)

1. Name: `String256`
2. Value: `String16`

## Terminal  (used 32)

1. Position: `ObjectPos`
2. Orientation: `Real32x9`
3. Model: `String16`
4. Destroyed model: `String16`
5. Damage scale: `Real32`
6. Explosion radius: `Real32`
7. Explosion falloff radius: `Real32`
8. Explosion damage scale: `Real32`
9. Explosion delay: `Real32`
10. Explosion fragments: `Int32`
11. Explosion fireballs: `Int32`
12. Explosion expression: `VarString`
13. Explosion sound: `String16`
14. On Expression: `VarString`
15. Hack Time (s): `Real32`

## TerrainLightMap  (used 3599)

1. Position: `ObjectPos`
2. Level: `Int32`
3. Size: `Int32`
4. TextureIndex: `Int32`
5. GeneratedWhenCreated: `bool8`

## TextBox  (used 0)

1. Font Resource: `String32`
2. Width: `Int32`
3. Height: `Int32`
4. Collect Items: `VarString`
5. Get Active Picture: `VarString`

## TextureModifier  (used 79)

1. Position: `ObjectPos`
2. Level: `Int32`
3. Material Index: `Int32`
4. Bitmap ID: `Int32`
5. Size: `Int32`
6. isEdit: `bool8`

## ToggleBox  (used 0)

1. Get Data Script: `VarString`
2. Set Data Script: `VarString`

## Train  (used 55)

1. Position: `Real32`
2. Original thrust: `Real32`
3. RailroadQTaskID: `Int32`
4. Model: `String256`
5. ThrustStep: `Real32`
6. MaxSpeed: `Real32`
7. Flip Direction: `bool8`
8. Displacement X: `Real32`
9. Displacement Y: `Real32`
10. Play Sound: `VarString`

## TypeWriterBox  (used 0)

1. Width: `Int32`
2. Height: `Int32`

## WeaponConfig  (used 0)

1. Weapon ID: `Int32`
2. Script ID: `String256`
3. Name: `String256`
4. Manufacturer: `String256`
5. Description: `String256`
6. Weapon Type: `EnumInt32`
7. Sight Display Type: `EnumInt32`
8. Ammo Display Type: `EnumInt32`
9. Mass of Weapon (grams): `Int32`
10. Calibre ID: `Int32`
11. Damage Factor: `Real32`
12. Penetration Power: `Real32`
13. Reload Time: `Real32`
14. Muzzle Velocity: `Real32`
15. Bullets/Round: `Int32`
16. Rounds/Minute: `Int32`
17. Rounds/Clip: `Int32`
18. Maximum Rounds/Burst: `Int32`
19. Minimum random spread: `Real32`
20. Maximum random spread: `Real32`
21. Fixed view change around X axis (degrees): `Real32`
22. Fixed view change around Z axis (degrees): `Real32`
23. Random view change around X axis (degrees): `Real32`
24. Random view change around Z axis (degrees): `Real32`
25. Type of weapon: `String256`
26. Effective Range of Weapon: `Real32`
27. Weapon Users: `String256`
28. Weapon Length: `Int32`
29. Barrel Length: `Int32`
30. Gun Model: `String16`
31. Casing Model: `String16`
32. StandAnim: `Int32`
33. MoveAnim: `Int32`
34. FireAnim1: `Int32`
35. FireAnim2: `Int32`
36. FireAnim3: `Int32`
37. ReloadAnim: `Int32`
38. UpperBodyStandAnim: `Int32`
39. UpperBodyWalkAnim: `Int32`
40. UpperBodyCrouchAnim: `Int32`
41. UpperBodyCrouchRunAnim: `Int32`
42. UpperBodyRunAnim: `Int32`
43. UpperBodyFireAnim: `Int32`
44. UpperBodyReloadAnim: `Int32`
45. Fire Sound Loop/Single Sample: `String16`
46. Fire Sound Loop End Sample: `String16`
47. AI Detection Event Range: `EnumReal32`
48. Projectile Task Type: `EnumInt32`
49. Weapon Task Type: `EnumInt32`
50. Is weapon selectable when empty: `bool8`

## WeaponConfigContainer  (used 0)


## Wire  (used 10)

1. Start position: `ObjectPos`
2. Stop position: `ObjectPos`
3. Model: `String16`

