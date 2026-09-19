# Alarm systems

How the game does it, and what the studio will offer. Everything here was read
out of the 14 shipped levels (`studio/extract/levels.py`, the QSC library and the
levels' own AI scripts).

## What an alarm is, in the game

An alarm system is one `AlarmControl` task plus whatever names it. Nothing is
implicit: every part points at the control by task id.

| Part | Task | How it joins the system |
|---|---|---|
| The system itself | `AlarmControl` | its **Trigger Expression** says what raises it, its **Alarm Expression** what keeps it ringing, its **On Expression** whether it works at all |
| Its memory | `EditVariable` | **Add** when `AlarmControl_N.isTrigger`, **Sub** when a button is pressed again; the control's Alarm Expression is `EditVariable_M.nValue == 1` |
| Cameras | `SCamera` | `SCamera_N.isDetection` in the trigger (directly, or through an `SCameraControl` that ORs a group of them) |
| Alarm buttons | `Switch` | `Switch_N.isLastPressed` in the trigger |
| Guards who answer | AI script | `SetAlarmControlID(N)` in the guard's own script, plus an `AIEVENT_ALARMON` handler that runs a patrol path |
| Sirens | `Siren` | On Expression `AlarmControl_N.isAlarm` (model `310_01_1`) |
| Flashing lights | `AlarmLight` | On expression `AlarmControl_N.isAlarm` (on `344_03_1`, off `344_01_1`) |
| The wailing sound | `ConditionalSound` | condition `AlarmControl_N.isAlarm`, sound `alarmsystem_working` |
| Reinforcements | `GuardGenerator` | "Generate guards" expression `AlarmControl_N.isAlarm`, a max-spawns count, and a `HumanSoldier` child it spawns |
| Doors, APCs, timers, messages | `Door`, `Car`, `LevelTimer`, `StatusMessage` | their own expression names `AlarmControl_N.isAlarm` |

Level 1 is the clearest example: one control (98), five cameras behind two
camera controls (90, 91), three wall buttons, 13 of its 37 guards carrying
`SetAlarmControlID(98)`, two alarm sounds, and an `EditVariable` (97) that holds
the alarm on until a button is pressed again.

There is no "area" anywhere in the data. **A system's area is its membership**:
the cameras and buttons in its trigger, and the guards that carry its id. Level 3
has two systems side by side — 70 (10 guards) and 80 (5 guards) — and that is
exactly how the game divides its base.

Counts across the game: 15 AlarmControls, 9 SCameraControls, 110 Switches,
34 Sirens, 16 AlarmLights, 82 GuardGenerators (9 of them alarm reinforcements).

## What the studio will offer

A fourth tab beside Inventory, Objectives and Navigation: **Security**. It lists
every alarm system in the mission — the level's own and the mission's — and each
one reads as a sentence:

> **Base alarm** · raised by 5 cameras and 3 buttons · answered by 13 guards ·
> sirens, lights, 4 reinforcements

with four groups under it, each a list you can click to fly to, and controls to
add or drop the mission's own parts:

1. **Raised by** — cameras, alarm buttons, and (for the level's own systems)
   whatever else its trigger names, shown as it reads.
2. **Answered by** — guards. The mission's own guards can be put on any system;
   the level's guards keep theirs.
3. **When it goes off** — sirens, flashing lights, reinforcements (a guard and
   how many times he comes back), the mission-fails flag, a message.
4. **Turning it off** — the buttons that silence it, and the hack time.

Placing parts stays in the inventory's **Security** section, which gets
everything alarm-related: security cameras (there already), alarm buttons,
sirens, alarm lights, and a new alarm system of your own. Each part's inspector
has one line: *Belongs to · <system>*, defaulting to the nearest one.

## Phases

- **A — see it.** Extract every level's alarm systems and the guard→control
  links from the AI scripts. The Security tab lists them, and the map draws
  the parts with a link to their control when a system is selected.
- **B — build it.** Alarm buttons, sirens and lights become placeable, each
  belonging to a system; Apply emits them and adds them to the trigger.
- **C — own systems.** An alarm control of the mission's own (with its
  `EditVariable` memory), for a corner of the map the level never alarmed.
- **D — answer it.** Own guards can be put on a system (`SetAlarmControlID`),
  and reinforcements: pick a guard, a spawn point and a count, wired to the
  alarm through a `GuardGenerator`.

## Engine notes to respect

- The map computer's 32-marker limit (see README) is unrelated but shares the
  budget of ids: every part takes a task id, and ids must stay ≤ 4095.
- A guard who answers an alarm needs an `AIEVENT_ALARMON` path out of his
  building, which the studio already generates.
- Models to import when a level lacks them: `202_01_1` (button), `310_01_1`
  (siren), `344_01_1`/`344_03_1` (light), `300_01_1` (alarm box).
