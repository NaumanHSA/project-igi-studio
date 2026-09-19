# Plan: the map looks and works like the game's map computer

Requested after the terrain layer landed. Goal: at a glance the plan reads like
the in-game map computer: real ground, buildings with their real shapes, and
recognisable vehicles, trees and items. The workspace is also reorganised so
the panels and tools you need are always in view.

## 1. Data

- [x] `studio/extract/meshes.py`: every structure/vehicle/prop render mesh
      (D3DR/DNER/XTRV decoded; collision mesh fallback) -> `editor/data/meshes.bin`
      + `meshes.json` (1205 models, 0.5 MB packed).
- [x] README: format notes, regenerate list.

## 2. One look: map computer only

- [x] Remove the blueprint theme: tokens, `SKIN` branches, the toggle button.

## 3. Ground

- [x] Relief rendered finer than the 1 m grid (up to 3x, capped pixel budget),
      bilinear heights, so contours stop stair-stepping.
- [x] More realistic: multi-directional hillshade, ridge/gully (curvature)
      shading, world-anchored rock/grain noise that follows the slope,
      anti-aliased contours (5 m faint, 25 m stronger).
- [x] Buildable-ground overlay in three states, sized to the building in hand
      (same rule as the placement check: height range under the footprint):
      clear < 1 m, **yellow** 1-3 m (sinks into the slope), **red** > 3 m.
      Also a toolbar toggle to show it without a building selected.

## 4. Things on the map

- [x] Buildings and large props: top-down render of the real mesh (painter's
      order, sun shading, height tint, edge lines), cached per model and zoom
      bucket, drawn at true size and rotation. The footprint still drives picking.
- [x] Vehicles, aircraft, trains, trees, bushes, crates, barrels, lights: SVG
      silhouettes in the same style, at true size where the model has one.
- [x] Pickups: an icon per weapon/item family (rifle, sniper rifle, SMG,
      shotgun, pistol, launcher, grenade, mine, medipack, ammo, binoculars,
      knife).
- [x] Guards: map-computer triangles pointing where they face; snipers,
      gunners and characters marked. Player spawn: hollow green triangle.
- [x] Inventory thumbnails use the same renders and icons.

## 5. Legend

- [x] A single "Legend" button in the map toolbar. Hover/click opens a panel
      listing only what is on the current map (guards by kind, player, pickups,
      vehicles, trees, walls/fences/climbable/electric, nodes, slope colours,
      contours), the first four with "more" for the rest.

## 6. Toolbar actions

- [x] View group: jump to player spawn, fit yard, fit all, zoom to selection,
      next of my changes, measure distance (ruler), all nodes on/off,
      grid on/off, save the view as PNG.

## 7. Workspace

- [x] Left edge: a vertical tab strip ("Inventory", "Navigation", rotated,
      centred vertically). Clicking a tab shows that panel; clicking the open
      tab hides it.
- [x] Inventory panel: Enemies, Weapons & items, Structures - each with its own
      share of the height and its own scroll; no page-level scroll. Structures
      keep their categories as sticky sub-headings with a category filter.
- [x] Navigation panel: add node, graph list, node counts (moved out of the
      inventory).
- [x] Denser rows: smaller font and thumbnails.

## 8. Feel

- [x] Map-computer zoom transition: a quick "CONNECTING" loading bar and thin
      horizontal static lines that flicker and fade (skipped with reduced motion).
- [x] Faint scanlines over the map.

## 9. Verify and ship

- [x] Headless screenshots of each part (level 3 yard, radar dome, hangar,
      watchtower, vehicles, legend open, both panels, building tool overlay).
- [x] README, commit, push.
