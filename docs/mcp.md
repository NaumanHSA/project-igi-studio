# The MCP server

Any agent that speaks MCP (Claude Desktop, Claude Code, Cursor and others) can work in
the open studio. The person presses **Start** in the studio's MCP panel and watches every
change as it happens. This page is how it is built; the manual has how to use it.

```
the agent's program
      |  stdio
studio mcp               studio/server/mcp_stdio.py: a small relay; the client starts it
      |  HTTP on 127.0.0.1, with a token, only while Start is on
the listener             studio/server/mcp.py, in the studio's server
      |  the page asks for the next call, and posts the answer
the open window          editor/mcp.js
      |
the one registry         StudioAI.tools and StudioAI.run, in editor/plotter.html
```

## One set of tools

There is one registry, the `T` list and `H` handlers of `AIB` in `editor/plotter.html`.
The built-in AI designer (`editor/ai.js`) and an agent from outside both go through
`callShown` and `StudioAI.run`, so a tool added or fixed is added or fixed for both. **Never
add a second list.** Tools that need the server (builds, tests) are still registry tools,
whose handler calls the server.

Each tool has a `kind`. An agent of the designer has a list of kinds (`AGENTS` in `ai.js`);
one from outside has them all. `mission` tools open and make missions, and only an outside
agent has them, since a designer's chat belongs to one mission. `see` tools return pictures,
and are left out for a model that can't look at them. Inside `AIB`, `H` is the tool table, not
the canvas's height: code that needs the height goes outside it, as `mapPicture` does.

A tool's picture is `image` or `images` in its answer, each `{url: a data: URL, ...}`. MCP
gets it as image content; the designer's model gets it in a message after that turn's results.

What any agent has to know is one function, `knowledge()` in `ai.js`.

## The protocol

`respond()` in `mcp.py` is the whole of it, written out with the standard library like the rest
of the server. It speaks both eras of MCP on one endpoint: a client that sends `initialize` gets
the handshake of its revision, and one that puts its version in each request's `_meta` (2026-07-28
on) is served statelessly. No session is kept for either.

The listener binds 127.0.0.1 only, refuses a browser's Origin or a foreign Host, and wants a
token. The relay reads the token and port from `mcp.json` in the user's folder, so a client's
settings never hold a secret. It answers with the studio closed too: from the tool list last
published (`mcp-tools.json`), with any call told to open the studio and press Start, because a
client that fails its first handshake often isn't tried again.

Claude Desktop holds its settings file in memory and writes it back as it closes, so an entry added
while it runs is lost on its next restart. Add to Claude Desktop waits until it is closed. Tell it from
Claude Code, which also runs as `claude.exe`, by its path.

Calls queue in `Bridge` and run one at a time in the window. Clients time a tool call out at about
a minute, so a long job (Apply, a test) answers within 50 s with a job id for `wait_for_job`.

## Testing in the game

`test_load` and `test_tour` (`studio/server/gametest.py`) try the mission in the real game, in a test
copy made beside the person's game (`testGamePath` in the settings, or `IGI-Test` next to it). Never
in their game: the build runs as a process of its own (`studio/build/testbuild.py`) with
`IGISTUDIO_GAME` and `IGISTUDIO_TESTRUN` set, so to it the copy is the connected game, and its
missions, backups and work folder are private ones inside the copy. The write gate does the rest.

The copy is started in a 1024 x 768 window and the menu's two clicks are made (`GOActiveMission` makes
the list open on the mission). The rest is from outside (`studio/server/gamewin.py`): the window's
picture, the text of a fatal error's dialog box, whether the process is there. Nothing is injected or
written to the game. A tour is a cutscene written into that build only.

What was found: simulated clicks work on the menu, but the window has to stay in front or the game
pauses. Starting a mission with no clicks does not work: a menu screen's On Init doesn't run for the
first screen, and calling `MenuManager_LeaveMenus` from an expression or the end of the script leaves a
black window with no level loading.

## Knowledge

`editor/guide/*.md` are written guides. `studio/extract/anatomy.py` measures the game's 14 levels from
the level data and writes `levels.md` and `level-<n>.md` into the user's folder (`guide/`). Those come
from the person's own game and must never be in the repository. All of them are `read_guide` topics and
MCP resources.

## Trying the tools

`tools/mcp-check.mjs` in the site repository is a scripted agent with no AI model, through the real relay
against the real page. `tests/test_mcp.py`, `test_gametest.py` and `test_anatomy.py` are the unit tests.
