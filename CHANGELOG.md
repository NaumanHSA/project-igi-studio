# Changelog

What changed in each release of Project IGI Studio, newest first. Each
section is also that release's notes on GitHub.

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
