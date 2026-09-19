# AI designer: plan

An AI panel in the studio that designs missions with you: it suggests designs
for the open level, and builds them on the map while you watch, one guard,
camera and objective at a time. It works through the same editing the studio
already has, so everything it does is an ordinary change: undo, the change
log, saving, the 3D view and Apply all work on it.

## What you do with it

- **Ideas:** "Suggest three missions for this level". It looks at the level
  (its named places, buildings, guards, alarms, walkways) and answers with
  designs, each a short pitch with objectives, where the enemies are, the
  security, weather and time, and how hard it is. It changes nothing. Each
  design has a **Build this** button.
- **Build:** "A stealth mission at the radar dome: two snipers on the towers,
  cameras on the gate, hack the terminal, snow, 15 minutes". It looks at the
  places it will use, says in a few lines what it will do, then builds: each
  step appears on the map as it happens (the map follows it), and a row in
  the chat says what was done with a button to find it. At the end it runs
  the check list the Apply button runs and fixes what it can.
- **Review and change:** "Make it harder", "Why would the player be seen at
  the gate?", "Move the snipers so they cover the road". It reads the
  mission as it is now, including your own changes since.
- **Stop** ends a run at once. **Undo these changes** after a run puts the
  mission back as it was before the run (one step, itself undoable).
- The selection is context: select a tower and say "put a sniper up there".

## Where it lives

- A right-edge tab strip, like the left one: **Selection** (the panel there
  now) and **AI designer**. The AI panel takes the right column's place while
  open; the choice is remembered.
- Panel: header (model in use, new chat, settings), **Ideas / Build** switch,
  the conversation, a status line while it works (with Stop), quick prompts
  when the chat is empty, the message box, and *Follow on the map*.
- Built-in missions are read-only: Ideas works, Build asks for a mission of
  your own first (the existing *New mission from this*).

## Settings (Settings button, new "AI designer" section)

- **API key:** kept by the studio server in `config.json` (ignored by git),
  or taken from `.env` (`OPENAI_API_KEY`) or the environment. The browser
  never gets it back, only whether there is one and its last 4 characters.
- **Model:** a list fetched from the account (chat models only), or typed.
  Default: `MODEL_QUALITY` from `.env`, else `gpt-5-mini`.
- **Thinking:** none, low, medium, high (reasoning effort; left out for models
  without it).
- **Provider address:** `https://api.openai.com/v1` by default. Any
  OpenAI-compatible server (OpenRouter, a local Ollama or LM Studio) works
  through the Chat Completions protocol.
- **Pace:** how long each step stays before the next (for watching it build),
  and the most steps one run may take (default 60).
- **Test** sends a one-line request and says what came back.

## How it works

```
 browser (editor/ai.js)                 studio server (studio/server/ai.py)      OpenAI
 ------------------------               ---------------------------------      ------
 history, tools, prompt  -- POST /api/ai/chat -->  key, model, protocol  -->  /v1/responses
 runs each tool call in  <-- NDJSON events ---    normalises the stream  <--  SSE events
 the editor, live
```

- **The loop runs in the browser**, because the tools act on the editor's
  plan (placements, objectives, events...), and the map redraws after each.
  One request per model turn; while the answer asks for tools, they run one
  by one (with the pace between them), their results go back, and the next
  turn starts, until the model answers with text only or the step limit.
- **The server holds the key** and speaks the provider's protocol:
  - **Responses** (`/v1/responses`, OpenAI): the only way to use tools with
    reasoning on the newest models (Chat Completions refuses tools with
    reasoning on `gpt-5.6-luna`, found 2026-09-18). Turns chain with
    `previous_response_id`; when that fails (expired, new server) the whole
    history is sent again, tool calls included.
  - **Chat Completions** (`/v1/chat/completions`) for other providers.
  - Both streamed back to the browser as the same small events, one JSON a
    line: `text`, `think` (a reasoning summary, when the model gives one),
    `callstart`, `call` (name, arguments, id), `done` (response id, tokens),
    `error`.
  - A 400 naming a parameter the model does not take (reasoning, summary,
    stream options) is retried once without it.
- **History** in the browser, in one simple form (user, assistant, call,
  result), converted by the server to either protocol. Saved with the mission
  (`missions/custom/<id>/ai/chat.json`, ignored by git) and loaded with it.
  Tool results are cut to a few thousand characters; old runs' results are
  shortened before they are sent again.
- **Test provider:** base address `mock` answers from a script (look, place,
  check, summarise) without any network, for the headless UI tests.

## The tools

Ids: your things by their uid (`p…`), the level's as `L<index>`. Positions in
metres, x east, y north; facing as a compass bearing in degrees (0 north,
90 east), or `face_toward` a point. Every result is small JSON with `ok`, and
an `error` the model can act on.

Looking (Ideas and Build):

| tool | what it gives |
|---|---|
| `get_overview` | the mission and level, the map's extent, the player start, counts, objectives, events, time and weather, alarm systems, the named places |
| `find_places` | named places (map labels, buildings, gates, terminals, the sides of the map) matching words, with positions |
| `look_around` | everything within a radius of a point, nearest first; ground heights; the nearest walkway; the building there and its floors |
| `list_catalog` | guard types, weapons, items, structures (with sizes), alarm parts, camera kinds |
| `get_item` | one thing in full, with what refers to it |
| `check_mission` | the check list Apply shows |
| `focus_map`, `show_3d` | move the map, or open the 3D view, to show the user something |

Building (Build only):

| tool | what it does |
|---|---|
| `place_guards` | n guards of a type near a point or a named place, on walkway spots (or at given points, on a floor of a building) |
| `edit_guard` | type, weapon, sight |
| `set_patrol` | a guard's patrol through points, snapped to his walkway graph |
| `place_object` | a structure or prop, checked like a placement by hand |
| `place_fence` | a straight run of fence or wall panels from a point to a point |
| `build_compound` | the fenced compound (gate, switch, towers, light, guards, level ground) |
| `place_pickup` | a weapon, ammo or item |
| `place_camera` | a camera, mounted on the nearest wall |
| `place_alarm_part` | button, siren, light or a new alarm system |
| `move_item`, `remove_item` | yours or the level's (the player start moves, is never removed) |
| `add_objective`, `remove_objectives` | the six objective kinds; the level's own can be dropped |
| `add_event` | when, then: message, alarm, guards arrive, doors open, mission fails |
| `set_settings` | time limit, rain or snow, haze, fail on alarm |
| `set_mission_info` | name and description |
| `set_player_start` | where the player begins |

## What it is told (system prompt)

Built in the browser for each turn: its role; the game in a paragraph (a
lone infiltrator, objectives on the map computer, alarms, cameras, snipers);
the rules the build needs (guards within 25 m of walkways or they walk off,
cameras need a wall within 4 m, six objectives on the map computer, 4095 task
ids, the level's own objectives stay until dropped); how to work (look, say
the plan in a few lines, build, check, summarise); the mode; and the live
context (mission, level, what is selected, counts).

## Safety

- Only the open mission, only through the editor: nothing is installed or
  started; Apply stays yours. Built-in missions are never changed.
- Every change is an ordinary undo step; a run can be undone as one.
- Step limit per run, Stop at any time, errors shown with what to do.
- The key stays on the server and out of git (`config.json`, `.env`).

## Added 2026-09-19

- **Tagging places:** a button by the message box; drag an area or click a
  thing or spot on the map; lettered tags (A, B...) drawn on the map, shown on
  the message and sent with their bounds.
- **Designs for the inventory:** `design_structure` (parts, guards, pickups
  round a centre) and `design_character` (type, model, weapon, sight), shown
  as a card with the model turning in 3D (`MeshSprites.composite`), with View
  in 3D, Place and Add to inventory (a saved group of kind `blueprint` or
  `character`, listed under Your designs and Your characters);
  `place_design` for the AI to place one. They work in Ideas mode too, since
  they change nothing. New weapon types and new models can't be made.
- The panel's width can be dragged, like every side panel.

## Added 2026-09-19 (second round)

- **Chats:** threads per mission (`GET /api/missions/<id>/ai`, `GET/PUT/DELETE
  .../ai/<thread>`), the chat list in the header, no alerts; the old single
  chat is taken in as the first thread.
- **Two models:** the main one plans and builds; the light one (`ai_light`,
  LM Studio's qwen by default) names chats, reads pictures and is the scout
  (a tool of the main model's that runs the light model with the looking
  tools). A chat can run on either. Turns on the light model send the whole
  history (chat completions); the main one keeps chaining by response id.
- **Pictures:** user items carry `images`; the server turns them into
  `input_image` (Responses) or `image_url` parts (chat completions). Sketches
  on the map go as coordinates as well.
- **Tools:** `add_walkways`, `shape_ground`, `remove_ground_area`,
  `stealth_check` (asynchronous: it waits for the coverage), `write_texts`,
  `list_missions`, `make_versions`, `make_campaign`; `show_3d` takes design
  ids. Tools may answer with a promise.
- **Fixes:** a design card squeezed to nothing in a long chat (the log's items
  no longer shrink); the message box is taller.

## Phases

1. Server: settings (key from config or `.env`), model list, test, the chat
   stream in both protocols, the test provider, chat storage.
2. Settings sheet: the AI designer section.
3. Editor bridge: the tools, run on the live plan, with results.
4. Panel: right-edge tabs, chat, streaming, tool rows, follow, pace, stop,
   undo the run, Ideas and Build, design cards, saved chats.
5. Prompt and tool descriptions, tuned against the real model.
6. Tests: headless with the test provider; real runs with the account's
   model on a throwaway copy of a mission.
7. README, roadmap.
