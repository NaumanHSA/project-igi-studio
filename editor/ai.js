// The AI designer: a panel on the right edge that suggests
// missions for the open level and builds them in the editor while you watch.
//
// The loop runs here: each model turn goes through the studio server (POST
// api/ai/chat, studio/server/ai.py, which holds the API key) and streams back as
// JSON lines; the tools it asks for run in the editor (window.StudioAI, in
// plotter.html), one by one, and the map follows. The conversation is saved
// with the mission as chat threads (api/missions/<id>/ai/<thread>).
//
// Two models: the main one (OpenAI) plans and builds; the light one (a local
// qwen in LM Studio) titles chats, reads pictures, and is the "scout" the main
// one can send to look things up. A chat can run on either (the model chip).
(function () {
"use strict";

var S = null;                 // the server's AI settings (no key, just whether there is one)
var CHAT = blank();           // this mission's conversation
var RUN = null;               // the run going on now
var BEFORE = {};              // run id -> the plan before it, for "Undo these changes"
var KEY = null;               // which mission the chat belongs to
var el = {};
var FOLLOW = pref("follow", "1") === "1";
var TAB = pref("rtab", "sel");
var TAGS = [];                // places tagged on the map for the next message
var PICKING = false;
var THREADS = [];             // this mission's chats, newest first: {id, title, updated, count}
var ATT = [];                 // pictures, map snapshots and sketches for the next message

// ------------------------------------------------------------------ the agents
// The designer is a team: each agent has a job, its own instructions and the
// kinds of tool it may use (plotter.html gives every tool a kind). A chat is
// with one agent at a time; switching keeps the history, so the next agent
// reads what happened.
var AGENTS = {
  ideas: {
    label: "Ideas", kinds: ["look", "design"], changes: false,
    hint: "Looks at the level and suggests missions. Nothing changes.",
    placeholder: "Ask for mission ideas for this level",
    title: "Mission ideas",
    lead: function (lv) { return "Ask for ideas for " + lv + ". It looks at the level and suggests missions; each one has a Build button that hands it to the Mission builder."; },
    chips: function (lv) {
      return ["Suggest three missions for " + lv + ", each with a different style", "What would make this mission harder without being unfair?",
        "Where would the player most likely be seen? Suggest fixes"];
    },
    prompt: [
      "Your job: suggest missions that fit this level's real places. You can look (get_overview, find_places, look_around, list_catalog, get_item, check_mission, stealth_check) but not change anything.",
      "Write each suggestion as a heading \"### Design N: Title\", then a two line pitch and short lists: objectives, enemies and where they are, security, time and weather, difficulty. The user can press Build on one, which hands it to the Mission builder."
    ]
  },
  mission: {
    label: "Mission", kinds: ["look", "design", "build", "ground", "texts", "plan"], changes: true,
    hint: "Plans a whole mission, then builds it one area at a time.",
    placeholder: "Describe the mission to plan and build",
    title: "Build a whole mission",
    lead: function () { return "It surveys the map, writes a plan (the story, the areas, what goes in each, the objectives and events) and shows it to you. Once you agree, it builds the mission one area at a time while you watch."; },
    chips: function () {
      return ["Plan a stealth mission for this map: a guarded compound with the objective inside, and two ways in",
        "Plan a sniper mission: the player on high ground, the targets in a camp below, and a way out",
        "Plan a rescue: a prisoner held in a building in the middle of a patrolled camp",
        "Plan an assault on a radar post on a hill, with an alarm that brings reinforcements"];
    },
    prompt: [
      "Your job: a whole mission, planned first and then built one area at a time. Most often the map is an empty map: the level's terrain, sky, weather, walkways and player start, with no buildings, guards, pickups, objectives or mission logic of its own. Everything the mission needs, you build.",
      "1. Survey: get_overview, then look_around across the map (send the scout on broad sweeps): where the ground is flat, where it rises, where the walkways run, where the player starts.",
      "2. Plan: call propose_plan with the whole mission: 3 to 6 areas in the order they will be built (each with its centre and size in metres, its role, and what goes there: ground work, structures, guards with their posts or patrols, cameras and alarms, pickups), at most 6 objectives (each in an area, with its target), the events, the settings, the player start and a briefing. The studio checks it; fix what it says and propose again. The user sees the plan as a card with the areas outlined on the map. Then stop: one line saying the plan is ready. Build nothing until they agree. When they ask for changes, call update_plan.",
      "3. Building: the studio asks for one area at a time (\"Build area C now\"). Build that area only, inside its bounds: level the ground where a compound or building goes, lay walkways (add_walkways) before placing guards, then the structures, guards, security and pickups. Look at what you made (look_around), then call plan_progress for the area: built, or problem with what went wrong. Keep your reply to a line.",
      "4. Finishing: when asked to finish, add the objectives with their targets, the events, move the player start if the plan says so, set the time and weather, write the texts (write_texts), run check_mission and stealth_check, fix what they find, and end with a short summary.",
      "Keep a way on foot from the player start to every objective, and more than one way in where you can. On an empty map there are none of the level's terminals, so no hack objectives: use reach, collect, kill or destroy."
    ]
  },
  edit: {
    label: "Edit", kinds: ["look", "design", "build", "ground", "texts", "library"], changes: true,
    hint: "Changes the mission as it is, while you watch.",
    placeholder: "Say what to change, add or fix",
    title: "Edit the mission",
    lead: function () { return "Say what to change and watch it happen on the map, one step at a time. Select something or tag a place to say where. Everything it does is an ordinary change: undo works, and Apply stays yours."; },
    chips: function () {
      return ["Make the mission harder: more guards on the routes to the objectives, and an alarm that brings reinforcements",
        "Build a fenced compound near the player start with guards, a camera and a weapon to collect inside",
        "Check the mission and fix what you can",
        "Run a stealth check and tell me where the player will be seen",
        "Write the mission's name, briefing, objective texts and map labels",
        "Make easy and hard versions of this mission"];
    },
    prompt: [
      "Your job: change the mission as it is, the way the user asks. Read what is there first (get_overview, look_around, get_item), change only what is asked and keep the rest. The selection and the tagged places say where.",
      "How to work: look before you change. Tell the user in two to four short lines what you are going to do, then do it step by step. After changing, run check_mission and fix what it finds. End with a short summary: what you changed and where, and what to try when playing it."
    ]
  },
  workshop: {
    label: "Workshop", kinds: ["look", "design"], changes: false, drop: /^(check_mission|stealth_check|list_missions|make_campaign|focus_map)$/,
    hint: "Buildings, characters and objects for your inventory.",
    placeholder: "Describe a building, a character or an object",
    title: "Workshop",
    lead: function () { return "Buildings, characters and objects for your inventory, made from the game's parts and shown turning in 3D. Nothing on the map changes: add what you like to the inventory and place it yourself."; },
    chips: function () {
      return ["Design a sandbagged sniper nest", "Design a checkpoint: a barrier, a guard hut and two guards",
        "Design a weapons cache hidden among crates", "Design an officer: a pistol, sharp eyes, and a model of his kind",
        "Design a watchtower with a sniper on top"];
    },
    prompt: [
      "Your job: design things for the user's inventory: buildings and structures made of the game's parts (with guards and pickups when they belong), characters, and groups of objects. You change nothing in the mission; the user places what they like.",
      "How to work: look through the catalogue first (list_catalog structures with a search word, for the parts and their sizes; list_catalog guards for the character types and their models). Then design with design_structure or design_character; each design appears in the chat turning in 3D. Say in a line or two what it is and how to use it. If it could be better, make a second version rather than explaining.",
      "Make designs that hold together: parts meet or overlap slightly and never float, stand on the ground (dz 0) unless stacked on another part (dz = the top of the part under it: its dz plus its height), face sensibly (a gate across the road, a guard looking out), and keep to a sensible size (use the sizes from list_catalog). A part's origin is not always its middle: box_centre_from_origin_m and bottom_from_origin_m in list_catalog say where its box sits.",
      "The studio checks every design and lists its flaws (a part floating or sunk, the same part twice, a part far from the rest, a guard or pickup inside a wall or crate). When there are flaws, make a corrected version at once, before you describe it. New weapon types, new 3D models and new textures can't be made yet: design with what the game has."
    ]
  }
};
AGENTS.review = {
  label: "Review", kinds: ["look"], changes: false, drop: /^(make_campaign|list_missions)$/,
  hint: "Plays it on paper and lists what to fix.",
  placeholder: "Ask what would go wrong, or what to check",
  title: "Review the mission",
  lead: function () { return "It walks the mission as the player would: the ways in, who sees them, the objectives, the alarm, the texts. Each finding comes with a Fix button that hands it to Edit. Nothing changes until you press one."; },
  chips: function () {
    return ["Review the mission: what would go wrong for the player, and what is unfair?",
      "Where will the player be seen on the way to each objective?",
      "Check the objectives, the briefing and the map labels"];
  },
  prompt: [
    "Your job: review the mission as the player will meet it, and say what to fix. You change nothing: look (get_overview, check_mission, stealth_check, look_around at the start, the objectives and the guarded places, get_item) and judge.",
    "Look for: objectives the game can't complete or the player can't reach on foot; ways in that are watched all the way, or none that are; guards who stand alone, face walls or walk off (more than 25 m from a walkway); cameras with nothing to raise; an alarm that brings nothing; a time limit too tight for the distance; texts too long or unclear; and what makes it too easy.",
    "Write each finding as a heading \"### Finding N: <what, in a few words>\", then one to three lines: where (a place name, or x, y), why it matters to the player, and the fix, concrete enough to make (\"move the sniper at the water tower 10 m east so he sees the gate\"). Most important first; at most 8. End with a heading \"### What works\" and a line on what already works well. The user presses Fix on a finding to hand it to Edit."
  ]
};
var ORDER = ["ideas", "mission", "edit", "workshop", "review"];
function agentOf(d) { return d && AGENTS[d.agent] ? d.agent : d && d.mode === "ideas" ? "ideas" : "edit"; }
function AG() { return AGENTS[CHAT.agent] || AGENTS.edit; }
// the tools an agent is given
function agentTools(id) {
  var a = AGENTS[id] || AGENTS.edit, list = api().tools(a.kinds);
  if (a.kinds.indexOf("plan") >= 0) list = list.concat(PLAN_TOOLS);
  return a.drop ? list.filter(function (t) { return !a.drop.test(t.name); }) : list;
}

function newId() { return "t" + Date.now().toString(36) + Math.random().toString(36).slice(2, 5); }
function blank() { return { id: newId(), title: "", created: 0, items: [], view: [], responseId: null, synced: 0, agent: "edit", model: "main" }; }
// a saved chat, taken in: chats from before the agents have a mode instead
function adopt(d, tid) { var c = Object.assign(blank(), d, { id: tid }); c.agent = agentOf(d); delete c.mode; if (!c.plan) delete c.plan; return c; }
function pref(k, d) { try { var v = localStorage.getItem("ai:" + k); return v == null ? d : v; } catch (e) { return d; } }
function setPref(k, v) { try { localStorage.setItem("ai:" + k, v); } catch (e) { /* private window */ } }
function $(id) { return document.getElementById(id); }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function api() { return window.StudioAI; }
function hasServer() { var A = api(); return !!(A && !A.local()); }

// ------------------------------------------------------------------ look
var CSS = [
".rtabs{border-right:none;border-left:1px solid var(--line)}",
".rtabs .tab{transform:none;border-right:1px solid var(--line);border-left:none;border-radius:5px 0 0 5px;margin-right:0;margin-left:-1px}",
".rtabs .tab svg{transform:none}",
".aipanel{flex:none;width:var(--aw,384px);background:var(--surface);border-left:1px solid var(--line);display:flex;flex-direction:column;min-height:0;position:relative}",
".aipanel[hidden]{display:none}",
".ai-head{display:flex;align-items:center;gap:6px;padding:8px 10px 7px;border-bottom:1px solid var(--line)}",
".ai-head .lbl{margin:0;flex:none}",
".ai-model{font:500 11px 'IBM Plex Mono',monospace;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1}",
".ai-ib{background:transparent;border:1px solid transparent;color:var(--muted);border-radius:4px;width:28px;height:28px;display:grid;place-items:center;cursor:pointer;flex:none}",
".ai-ib:hover{color:var(--ink);border-color:var(--line)}",
".ai-ib svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:1.6}",
".ai-modes{display:flex;flex-wrap:wrap;gap:5px 8px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--line)}",
".ai-modes .seg .btn{padding:4px 8px;font-size:12.5px}",
".ai-modes .hint{margin:0;flex-basis:100%;font-size:11.5px}",
".ai-log{flex:1;min-height:0;overflow-y:auto;padding:10px 12px 14px;display:flex;flex-direction:column;gap:9px;scroll-behavior:smooth}",
".ai-log>*{flex:none}",
".ai-u{align-self:flex-end;max-width:88%;background:var(--accent-soft);border:1px solid color-mix(in srgb,var(--accent) 45%,var(--line));color:var(--ink);border-radius:9px 9px 2px 9px;padding:7px 10px;font-size:13px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere}",
".ai-a{font-size:13px;line-height:1.5;color:var(--ink);overflow-wrap:anywhere}",
".ai-a p{margin:0 0 6px}.ai-a p:last-child{margin-bottom:0}",
".ai-a h4{font:600 13px 'Barlow Condensed',sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--accent);margin:10px 0 4px}",
".ai-a ul,.ai-a ol{margin:2px 0 6px;padding-left:18px}.ai-a li{margin:1px 0}",
".ai-a code{font:12px 'IBM Plex Mono',monospace;background:var(--sunken);border:1px solid var(--line);border-radius:3px;padding:0 3px}",
".ai-a b{color:#fff}",
".ai-a .cursor{display:inline-block;width:7px;height:13px;background:var(--accent);vertical-align:-2px;margin-left:2px;animation:aiblink 1s steps(2) infinite}",
"@keyframes aiblink{50%{opacity:0}}",
".ai-design{margin:6px 0 10px;padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:var(--sunken)}",
".ai-design h4{margin-top:0}",
".ai-design .btn{margin-top:6px;font-size:12px;padding:3px 10px}",
".ai-finding{border-color:color-mix(in srgb,var(--warn) 45%,var(--line))}",
".ai-finding h4{color:var(--warn)}",
".ai-think{font-size:12px;color:var(--faint);border-left:2px solid var(--line);padding:2px 0 2px 8px}",
".ai-think summary{cursor:pointer;color:var(--muted);font-size:11.5px;list-style:none}",
".ai-think summary::-webkit-details-marker{display:none}",
".ai-think div{margin-top:3px;font-size:12px;color:var(--faint)}",
".ai-think .ai-a b{color:var(--muted)}",
".ai-tools{display:flex;flex-direction:column;gap:3px}",
".ai-t{border:1px solid var(--line);border-radius:5px;background:var(--sunken)}",
".ai-t-h{display:grid;grid-template-columns:16px 1fr auto;gap:7px;align-items:center;padding:4px 6px 4px 7px;cursor:pointer;font-size:12.5px;color:var(--ink)}",
".ai-t-h .ic{width:14px;height:14px;border-radius:50%;display:grid;place-items:center;font:700 10px 'IBM Plex Mono',monospace}",
".ai-t.ok .ic{background:color-mix(in srgb,var(--ok) 25%,transparent);color:var(--ok)}",
".ai-t.bad .ic{background:color-mix(in srgb,var(--danger) 25%,transparent);color:var(--danger)}",
".ai-t.run .ic{border:2px solid var(--line);border-top-color:var(--accent);animation:aispin .8s linear infinite}",
".ai-t.look .ai-t-h{color:var(--muted)}",
"@keyframes aispin{to{transform:rotate(360deg)}}",
".ai-t-h .go{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:4px;font-size:11px;padding:1px 6px;cursor:pointer}",
".ai-t-h .go:hover{color:var(--ink);border-color:var(--accent)}",
".ai-t-err{color:var(--danger);font-size:12px;padding:0 8px 5px 30px}",
".ai-t-note{color:var(--warn);font-size:12px;padding:0 8px 5px 30px}",
".ai-t pre{margin:0;padding:6px 8px;border-top:1px solid var(--line);font:11px/1.4 'IBM Plex Mono',monospace;color:var(--muted);white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto}",
".ai-err{border:1px solid color-mix(in srgb,var(--danger) 55%,var(--line));background:color-mix(in srgb,var(--danger) 10%,transparent);color:var(--danger);border-radius:6px;padding:7px 9px;font-size:12.5px}",
".ai-err .btn{margin-top:6px;font-size:12px;padding:2px 9px}",
".ai-note{font-size:12px;color:var(--faint);text-align:center}",
".ai-runf{display:flex;align-items:center;gap:8px;font:500 11px 'IBM Plex Mono',monospace;color:var(--faint);border-top:1px dashed var(--line);padding-top:6px}",
".ai-runf span{flex:1}",
".ai-runf .btn{font:500 11.5px 'IBM Plex Sans',sans-serif;padding:2px 9px}",
".ai-empty{margin:auto 0;padding:10px 4px;display:flex;flex-direction:column;gap:10px}",
".ai-empty h3{margin:0;font:600 18px 'Barlow Condensed',sans-serif;letter-spacing:.04em;color:var(--ink)}",
".ai-empty p{margin:0;font-size:13px;color:var(--muted);line-height:1.5}",
".ai-chips{display:flex;flex-direction:column;gap:6px}",
".ai-chip{text-align:left;background:var(--sunken);border:1px solid var(--line);color:var(--ink);border-radius:6px;padding:7px 10px;font:13px 'IBM Plex Sans',sans-serif;cursor:pointer;line-height:1.35}",
".ai-chip:hover{border-color:var(--accent)}",
".ai-card{border:1px solid var(--line);border-radius:6px;background:var(--sunken);padding:10px;font-size:12.5px;color:var(--muted);line-height:1.5}",
".ai-card b{color:var(--ink)}",
".ai-card .btn{margin-top:8px}",
".ai-foot{border-top:1px solid var(--line);padding:8px 12px 10px;display:flex;flex-direction:column;gap:6px;background:var(--surface)}",
".ai-status{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);min-height:18px}",
".ai-status[hidden]{display:none}",
".ai-status .dot{width:8px;height:8px;border-radius:50%;background:var(--accent);animation:aipulse 1.1s ease-in-out infinite}",
"@keyframes aipulse{50%{opacity:.25}}",
".ai-status span{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
".ai-compose{display:flex;gap:6px;align-items:flex-end}",
".ai-compose textarea{flex:1;resize:none;min-height:68px;max-height:240px;background:var(--sunken);border:1px solid var(--line);color:var(--ink);border-radius:6px;padding:8px 9px;font:13px/1.45 'IBM Plex Sans',sans-serif}",
".ai-tbar{display:flex;align-items:center;gap:4px}",
".ai-tbar .ai-ib{width:30px;height:28px;border-color:var(--line);background:var(--sunken)}",
".ai-tbar .ai-ib.on{border-color:var(--accent);color:var(--accent)}",
".ai-tbar span{flex:1;font-size:11px;color:var(--faint);text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
".ai-atts{display:flex;flex-wrap:wrap;gap:6px}.ai-atts[hidden]{display:none}",
".ai-att{position:relative;width:74px;height:54px;border:1px solid var(--line);border-radius:5px;overflow:hidden;background:var(--sunken)}",
".ai-att img{width:100%;height:100%;object-fit:cover;display:block}",
".ai-att i{position:absolute;left:3px;bottom:2px;font:600 9.5px 'IBM Plex Sans',sans-serif;font-style:normal;color:#fff;background:rgba(0,0,0,.6);border-radius:3px;padding:0 4px}",
".ai-att button{position:absolute;right:2px;top:2px;width:17px;height:17px;border-radius:50%;border:none;background:rgba(0,0,0,.65);color:#fff;cursor:pointer;font-size:12px;line-height:17px;padding:0}",
".ai-u .ai-uimgs{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}",
".ai-u .ai-uimgs img{width:96px;height:66px;object-fit:cover;border-radius:4px;border:1px solid var(--line)}",
".ai-reading{font-size:12px;color:var(--faint);border-left:2px solid var(--accent);padding:2px 0 2px 8px}",
".ai-reading summary{cursor:pointer;color:var(--muted);font-size:11.5px}",
".ai-reading div{margin-top:3px;white-space:pre-wrap}",
".ai-t-sub{padding:0 8px 5px 30px;font-size:11.5px;color:var(--faint)}",
".ai-thread{flex:1;min-width:0;display:flex;align-items:center;gap:5px;background:transparent;border:1px solid transparent;border-radius:4px;color:var(--ink);cursor:pointer;padding:3px 6px;text-align:left;font:600 13px 'IBM Plex Sans',sans-serif}",
".ai-thread:hover,.ai-thread[aria-expanded=\"true\"]{border-color:var(--line);background:var(--sunken)}",
".ai-thread span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
".ai-thread svg{width:10px;height:10px;flex:none;fill:none;stroke:var(--muted);stroke-width:2}",
".ai-model{background:transparent;border:1px solid var(--line);border-radius:10px;cursor:pointer;padding:1px 8px;max-width:150px}",
".ai-model.light{border-color:var(--ok);color:var(--ok)}",
".ai-threads{position:absolute;left:8px;right:8px;top:44px;z-index:9;background:var(--surface);border:1px solid var(--line);border-radius:7px;box-shadow:var(--shadow);max-height:60%;overflow-y:auto;padding:5px}",
".ai-threads[hidden]{display:none}",
".ai-th{display:grid;grid-template-columns:1fr auto auto;gap:4px;align-items:center;border-radius:5px;padding:5px 6px;cursor:pointer}",
".ai-th:hover{background:var(--sunken)}.ai-th.on{background:var(--accent-soft)}",
".ai-th b{font-weight:500;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}",
".ai-th small{font:10.5px 'IBM Plex Mono',monospace;color:var(--faint)}",
".ai-th button{background:transparent;border:1px solid transparent;color:var(--muted);border-radius:4px;cursor:pointer;font-size:11.5px;padding:1px 6px}",
".ai-th button:hover{color:var(--ink);border-color:var(--line)}.ai-th button.sure{color:var(--danger);border-color:var(--danger)}",
".ai-th input{width:100%;background:var(--sunken);border:1px solid var(--accent);color:var(--ink);border-radius:4px;padding:2px 5px;font:13px 'IBM Plex Sans',sans-serif}",
".ai-th-new{display:flex;align-items:center;gap:6px;color:var(--accent);font-size:13px;padding:6px;border-bottom:1px solid var(--line);margin-bottom:4px;cursor:pointer;border-radius:5px}",
".ai-th-new:hover{background:var(--sunken)}",
".ai-compose textarea:focus-visible{outline:2px solid var(--accent);outline-offset:0}",
".ai-compose .btn{height:38px;padding:0 14px}",
".ai-opts{display:flex;align-items:center;gap:10px;font-size:11.5px;color:var(--faint)}",
".ai-opts label{display:flex;align-items:center;gap:5px;cursor:pointer}",
".ai-opts span{flex:1;text-align:right}",
".ai-set .set-row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}",
".ai-set .ai-keyrow{display:flex;gap:6px}.ai-set .ai-keyrow input{flex:1}",
".ai-set .ai-msg{font-size:12px;margin-left:6px}",
".ai-set .ai-msg.good{color:var(--ok)}.ai-set .ai-msg.bad{color:var(--danger)}",
".ai-set .seg{margin-top:2px}",
".ai-tagbtn{height:38px;width:34px;border:1px solid var(--line);background:var(--sunken)}",
".ai-tagbtn.on{border-color:var(--accent);color:var(--accent)}",
".ai-tags{display:flex;flex-wrap:wrap;gap:5px}.ai-tags[hidden]{display:none}",
".ai-tag{display:inline-flex;align-items:center;gap:5px;max-width:100%;border:1px solid var(--accent);background:var(--accent-soft);color:var(--ink);border-radius:12px;padding:1px 4px 1px 3px;font-size:11.5px}",
".ai-tag i{font:700 10px 'IBM Plex Mono',monospace;font-style:normal;background:var(--accent);color:var(--accent-ink);border-radius:9px;min-width:16px;height:16px;display:grid;place-items:center}",
".ai-tag span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
".ai-tag button{background:transparent;border:none;color:var(--muted);cursor:pointer;padding:0 3px;font-size:13px;line-height:1}",
".ai-tag button:hover{color:var(--ink)}",
".ai-u .ai-tags{margin-top:5px}.ai-u .ai-tag{padding-right:7px}",
".ai-dcard{border:1px solid color-mix(in srgb,var(--accent) 55%,var(--line));border-radius:7px;background:var(--sunken);overflow:hidden}",
".ai-dcard .pv{position:relative;height:170px;background:radial-gradient(ellipse at 50% 70%,#163a1b,#0a1f0d)}",
".ai-dcard .pv canvas{position:absolute;inset:0;width:100%;height:100%;display:block}",
".ai-dcard .pv em{position:absolute;left:8px;top:6px;font:600 11px 'Barlow Condensed',sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);font-style:normal}",
".ai-dcard .dc-b{padding:8px 10px 10px;display:flex;flex-direction:column;gap:3px}",
".ai-dcard .dc-b b{font-size:14px;color:var(--ink)}",
".ai-dcard .dc-b span{font:11px 'IBM Plex Mono',monospace;color:var(--faint)}",
".ai-dcard .dc-b p{margin:2px 0 0;font-size:12.5px;color:var(--muted);line-height:1.4}",
".ai-dcard .dc-acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}",
".ai-dcard .dc-acts .btn{font-size:12px;padding:3px 10px}",
".ai-dcard .dc-acts .btn.done{background:transparent;border-color:var(--ok);color:var(--ok);cursor:default}",
".ai-step{align-self:flex-start;font:600 11px 'Barlow Condensed',sans-serif;letter-spacing:.07em;text-transform:uppercase;color:#6fb6ff;border:1px solid color-mix(in srgb,#6fb6ff 45%,var(--line));border-radius:10px;padding:2px 9px}",
".ai-plan{border:1px solid color-mix(in srgb,#6fb6ff 55%,var(--line));border-radius:7px;background:var(--sunken);padding:9px 10px 10px;font-size:12.5px;color:var(--muted);line-height:1.45}",
".ai-plan.old{opacity:.6;padding:6px 10px}",
".ai-plan p{margin:4px 0 0}.ai-plan .pl-sets{font:11px 'IBM Plex Mono',monospace;color:var(--faint)}",
".ai-plan .pl-note{color:#6fb6ff;font-size:12px}",
".pl-h{display:flex;align-items:baseline;gap:7px}",
".pl-h em{font:600 11px 'Barlow Condensed',sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#6fb6ff;font-style:normal}",
".pl-h b{flex:1;font-size:14px;color:var(--ink);min-width:0;overflow-wrap:anywhere}",
".pl-st{font:500 10.5px 'IBM Plex Mono',monospace;border:1px solid var(--line);border-radius:9px;padding:0 7px;white-space:nowrap;color:var(--muted)}",
".pl-st.building,.pl-st.finishing{color:var(--accent);border-color:var(--accent)}.pl-st.done{color:var(--ok);border-color:var(--ok)}",
".pl-areas{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-direction:column;gap:5px}",
".pl-areas li{display:grid;grid-template-columns:20px 1fr auto;gap:7px;align-items:start;border-top:1px solid var(--line);padding-top:5px}",
".pl-areas i{font:700 11px 'IBM Plex Mono',monospace;font-style:normal;width:20px;height:20px;border-radius:50%;display:grid;place-items:center;background:color-mix(in srgb,#6fb6ff 25%,transparent);color:#6fb6ff}",
".pl-areas li.built i{background:color-mix(in srgb,var(--ok) 25%,transparent);color:var(--ok)}",
".pl-areas li.building i{background:var(--accent);color:var(--accent-ink)}",
".pl-areas li.problem i{background:color-mix(in srgb,var(--danger) 25%,transparent);color:var(--danger)}",
".pl-areas b{color:var(--ink)}.pl-areas span{font-size:11.5px;color:var(--faint)}",
".pl-areas small{display:block;font:11px 'IBM Plex Mono',monospace;color:var(--faint)}",
".pl-areas li.built small{color:var(--ok)}.pl-areas li.building small{color:var(--accent)}.pl-areas li.problem small{color:var(--danger)}",
".pl-areas p{margin:2px 0 0;font-size:12px}",
".pl-areas .go{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:4px;font-size:11px;padding:1px 6px;cursor:pointer}",
".pl-areas .go:hover{color:var(--ink);border-color:#6fb6ff}",
".pl-areas .pl-b{display:flex;gap:4px}",
".pl-sub{margin-top:8px;font:600 11px 'Barlow Condensed',sans-serif;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}",
".pl-obj{margin:2px 0 0;padding-left:18px}.pl-obj span{color:var(--faint)}",
".pl-acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.pl-acts .btn{font-size:12px;padding:3px 10px}"
].join("\n");

var IC = {
  spark: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5 9.4 6.1 14 7.5 9.4 8.9 8 13.5 6.6 8.9 2 7.5 6.6 6.1z"/><path d="M13 1.5v3M11.5 3h3"/></svg>',
  sel: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 2.5 12.5 7 8.3 8.3 6.8 12.8z"/></svg>',
  gear: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="2.2"/><path d="M8 1.8v1.8M8 12.4v1.8M1.8 8h1.8M12.4 8h1.8M3.6 3.6l1.3 1.3M11.1 11.1l1.3 1.3M3.6 12.4l1.3-1.3M11.1 4.9l1.3-1.3"/></svg>',
  plus: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10"/></svg>',
  tag: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 5V2.5H5M11 2.5h2.5V5M13.5 11v2.5H11M5 13.5H2.5V11"/><circle cx="8" cy="8" r="1.6"/></svg>',
  clip: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10.5 4.5 5.8 9.2a1.4 1.4 0 0 0 2 2L12.6 6.4a2.8 2.8 0 0 0-4-4L3.8 7.2a4.2 4.2 0 0 0 6 6l3.6-3.6"/></svg>',
  map: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 4.5 6 3l4 1.5 4-1.5v8.5l-4 1.5-4-1.5-4 1.5z"/><path d="M6 3v8.5M10 4.5V13"/></svg>',
  pen: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 13 1-3.5 7-7 2.5 2.5-7 7z"/><path d="M9.5 4 12 6.5"/></svg>',
  caret: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5"/></svg>'
};

// ------------------------------------------------------------------ the panel
function build() {
  var st = document.createElement("style");
  st.textContent = CSS;
  document.head.appendChild(st);
  var ws = document.querySelector(".workspace"), rail = document.querySelector(".rail.right");
  if (!ws || !rail) return false;
  var panel = document.createElement("aside");
  panel.className = "aipanel";
  panel.id = "panel-ai";
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-label", "AI designer");
  panel.hidden = true;
  panel.innerHTML =
    '<div class="ai-head"><button class="ai-thread" id="ai-thread" aria-haspopup="true" aria-expanded="false" title="Chats\nYour conversations about this mission: open one, rename or delete it">' +
    '<span id="ai-thread-t">New chat</span>' + IC.caret + '</button>' +
    '<button class="ai-model" id="ai-model-chip" type="button"></button>' +
    '<button class="ai-ib" id="ai-new" title="New chat\nStart a new conversation. The others stay in the chat list." aria-label="New chat">' + IC.plus + '</button>' +
    '<button class="ai-ib" id="ai-cfg" title="Settings\nAPI keys, models and how it works" aria-label="AI settings">' + IC.gear + '</button></div>' +
    '<div class="ai-threads" id="ai-threads" hidden></div>' +
    '<div class="ai-modes"><div class="seg" role="radiogroup" aria-label="Agent">' +
    ORDER.map(function (k) { var a = AGENTS[k]; return '<button class="btn" data-agent="' + k + '" role="radio" title="' + esc(a.label + "\n" + a.hint) + '">' + esc(a.label) + '</button>'; }).join("") +
    '</div><p class="hint" id="ai-mode-hint"></p></div>' +
    '<div class="ai-log" id="ai-log" aria-live="polite"></div>' +
    '<div class="ai-foot">' +
    '<div class="ai-status" id="ai-status" hidden><i class="dot"></i><span id="ai-status-t"></span></div>' +
    '<div class="ai-tbar">' +
    '<button class="ai-ib" id="ai-tag" title="Tag a place\nDrag an area on the map, or click a thing or a spot. The next message is about it (A, B, C)" aria-label="Tag a place on the map">' + IC.tag + '</button>' +
    '<button class="ai-ib" id="ai-sketch" title="Sketch on the map\nDraw walls, routes, areas in colours; the drawing goes with the next message, exactly where you drew it" aria-label="Sketch on the map">' + IC.pen + '</button>' +
    '<button class="ai-ib" id="ai-snap" title="Attach the map\nThe map as you see it now, with a grid in metres, for the model to read" aria-label="Attach the map as it is now">' + IC.map + '</button>' +
    '<button class="ai-ib" id="ai-clip" title="Attach a picture\nA sketch, a screenshot or a photo of a plan; or paste one, or drop it here" aria-label="Attach a picture">' + IC.clip + '</button>' +
    '<input type="file" id="ai-file" accept="image/*" multiple hidden><span id="ai-tbar-t"></span></div>' +
    '<div class="ai-atts" id="ai-atts" hidden></div>' +
    '<div class="ai-tags" id="ai-tags" hidden></div>' +
    '<div class="ai-compose">' +
    '<textarea id="ai-in" rows="3" placeholder="Describe a mission, or ask for ideas" aria-label="Message to the AI designer"></textarea>' +
    '<button class="btn primary" id="ai-send" title="Send\nEnter sends, Shift+Enter starts a new line">Send</button></div>' +
    '<div class="ai-opts"><label title="Follow on the map\nThe map moves to each thing as it is built"><input type="checkbox" id="ai-follow"> Follow on the map</label><span id="ai-usage"></span></div>' +
    '</div>';
  rail.parentNode.insertBefore(panel, rail.nextSibling);
  var tabs = document.createElement("nav");
  tabs.className = "tabs rtabs";
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "Right panels");
  tabs.innerHTML =
    '<button class="tab" role="tab" id="tab-sel" aria-controls="insp" title="Selection\nWhat you picked on the map, and the change log">' + IC.sel + 'Selection</button>' +
    '<button class="tab" role="tab" id="tab-ai" aria-controls="panel-ai" title="AI designer\nIdeas for missions, and building them while you watch">' + IC.spark + 'AI designer</button>';
  panel.parentNode.insertBefore(tabs, panel.nextSibling);
  el = { panel: panel, rail: rail, log: $("ai-log"), input: $("ai-in"), send: $("ai-send"), status: $("ai-status"),
    statusT: $("ai-status-t"), chip: $("ai-model-chip"), usage: $("ai-usage"), hint: $("ai-mode-hint"), tags: $("ai-tags"), tagBtn: $("ai-tag"),
    atts: $("ai-atts"), threads: $("ai-threads"), threadBtn: $("ai-thread"), threadT: $("ai-thread-t"), tbarT: $("ai-tbar-t") };
  el.tagBtn.addEventListener("click", pickTag);
  $("ai-sketch").addEventListener("click", sketch);
  $("ai-snap").addEventListener("click", snapMap);
  $("ai-clip").addEventListener("click", function () { $("ai-file").click(); });
  $("ai-file").addEventListener("change", function () { Array.prototype.forEach.call(this.files || [], addImageFile); this.value = ""; });
  el.input.addEventListener("paste", function (e) {
    var files = Array.prototype.filter.call((e.clipboardData && e.clipboardData.files) || [], function (f) { return /^image\//.test(f.type); });
    if (files.length) { e.preventDefault(); files.forEach(addImageFile); }
  });
  panel.addEventListener("dragover", function (e) { if (e.dataTransfer && Array.prototype.some.call(e.dataTransfer.items || [], function (i) { return /^image\//.test(i.type); })) e.preventDefault(); });
  panel.addEventListener("drop", function (e) {
    var files = Array.prototype.filter.call((e.dataTransfer && e.dataTransfer.files) || [], function (f) { return /^image\//.test(f.type); });
    if (files.length) { e.preventDefault(); files.forEach(addImageFile); }
  });
  el.threadBtn.addEventListener("click", function () { toggleThreads(); });
  el.chip.addEventListener("click", switchModel);
  document.addEventListener("mousedown", function (e) {
    if (!el.threads.hidden && !e.target.closest("#ai-threads") && !e.target.closest("#ai-thread")) toggleThreads(false);
  });
  if (window.StudioUI) StudioUI.resizable(panel, "l", "--aw", 300, 760);
  $("tab-sel").addEventListener("click", function () { showTab("sel"); });
  $("tab-ai").addEventListener("click", function () { showTab("ai"); });
  $("ai-cfg").addEventListener("click", function () { if (api()) api().openSettings("ai"); });
  $("ai-new").addEventListener("click", newChat);
  panel.querySelectorAll("[data-agent]").forEach(function (b) {
    b.addEventListener("click", function () { if (!RUN) setAgent(b.getAttribute("data-agent")); });
  });
  $("ai-follow").checked = FOLLOW;
  $("ai-follow").addEventListener("change", function () { FOLLOW = this.checked; setPref("follow", FOLLOW ? "1" : "0"); });
  el.send.addEventListener("click", function () { if (RUN) stop(); else submit(); });
  el.input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!RUN) submit(); }
    e.stopPropagation();                       // the map's shortcuts are not for this box
  });
  el.input.addEventListener("keyup", function (e) { e.stopPropagation(); });
  el.input.addEventListener("input", grow);
  showTab(TAB);
  paintMode();
  return true;
}
function grow() { var t = el.input; t.style.height = "auto"; t.style.height = Math.max(68, Math.min(240, t.scrollHeight + 2)) + "px"; }
function showTab(t) {
  TAB = t === "ai" ? "ai" : "sel";
  setPref("rtab", TAB);
  el.panel.hidden = TAB !== "ai";
  el.rail.style.display = TAB === "ai" ? "none" : "";
  $("tab-sel").setAttribute("aria-selected", String(TAB === "sel"));
  $("tab-ai").setAttribute("aria-selected", String(TAB === "ai"));
  window.dispatchEvent(new Event("resize"));
  if (TAB === "ai") { loadSettings(); render(); setTimeout(function () { if (el.input && !RUN) el.input.focus(); }, 30); }
}
function paintMode() {
  el.panel.querySelectorAll("[data-agent]").forEach(function (b) {
    var on = b.getAttribute("data-agent") === CHAT.agent;
    b.classList.toggle("on", on); b.setAttribute("aria-checked", String(on));
  });
  el.hint.textContent = AG().hint;
  el.input.placeholder = AG().placeholder;
  if (!CHAT.view.length) render();
}
// hand the chat to another agent; it keeps the history
function setAgent(k) {
  if (!AGENTS[k] || k === CHAT.agent) return;
  CHAT.agent = k; setPref("agent", k);
  paintMode();
  if (CHAT.view.length) add({ k: "note", text: "Now with " + AGENTS[k].label + ": " + AGENTS[k].hint });
  saveSoon();
}
// the agent a new chat starts with: the Mission builder on an empty map of
// the user's, else the one used last
function startAgent() {
  var A = api(), c = A && A.ready() ? A.context() : null;
  if (c && c.editable && c.empty && !c.counts.yours) return "mission";
  var k = pref("agent", "edit");
  return AGENTS[k] ? k : "edit";
}

// ------------------------------------------------------------------ tagging a place
var LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ";
function pickTag() {
  var A = api();
  if (!A || !A.ready()) return;
  if (PICKING) { A.cancelPick(); return; }
  PICKING = true;
  el.tagBtn.classList.add("on");
  status("Tag a place: drag an area on the map, or click a thing or a spot. Esc cancels.");
  A.pickArea(function (tag) {
    PICKING = false;
    el.tagBtn.classList.remove("on");
    if (!RUN) status("");
    if (tag) { TAGS.push(tag); letter(); paintTags(); }
    el.input.focus();
  });
}
function letter() { TAGS.forEach(function (t, i) { t.letter = LETTERS.charAt(i % LETTERS.length); }); api().setTags(TAGS.concat(RUN && RUN.tags || [])); }
function tagName(t) {
  return t.kind === "area" ? "Area " + Math.round(t.x1 - t.x0) + " × " + Math.round(t.y1 - t.y0) + " m" :
    t.kind === "thing" ? t.name : "Spot " + Math.round(t.x) + ", " + Math.round(t.y);
}
function tagChips(list, removable) {
  return list.map(function (t, i) {
    return '<span class="ai-tag" title="' + esc(tagText([t]).split("\n")[1] || "") + '"><i>' + esc(t.letter) + '</i><span>' + esc(tagName(t)) + '</span>' +
      (removable ? '<button type="button" data-i="' + i + '" aria-label="Remove this tag">×</button>' : '') + '</span>';
  }).join("");
}
function paintTags() {
  el.tags.hidden = !TAGS.length;
  el.tags.innerHTML = tagChips(TAGS, true);
  el.tags.querySelectorAll("button[data-i]").forEach(function (b) {
    b.addEventListener("click", function () { TAGS.splice(+b.getAttribute("data-i"), 1); letter(); paintTags(); });
  });
}
// the tags as the model reads them, after the message
function tagText(list) {
  function n(v) { return Math.round(v * 10) / 10; }
  return "Places the user tagged on the map for this message:\n" + list.map(function (t) {
    return "- [" + t.letter + "] " + (t.kind === "area" ?
      "an area " + Math.round(t.x1 - t.x0) + " x " + Math.round(t.y1 - t.y0) + " m: x " + n(t.x0) + " to " + n(t.x1) + ", y " + n(t.y0) + " to " + n(t.y1) +
        " (centre " + n((t.x0 + t.x1) / 2) + ", " + n((t.y0 + t.y1) / 2) + ")" :
      t.kind === "thing" ? t.name + " (id " + t.id + ") at " + n(t.x) + ", " + n(t.y) :
      "a spot at " + n(t.x) + ", " + n(t.y) + " (about " + t.r + " m round it)");
  }).join("\n");
}

// ------------------------------------------------------------------ pictures and sketches
// Attached to the next message: a picture file (or pasted, or dropped), the
// map as it is now with a grid in metres, or a sketch drawn on the map (its
// strokes go as exact coordinates too). The light model reads each picture
// first when it can; the main model gets the pictures as well.
function shrink(url, max, q) {
  return new Promise(function (resolve) {
    var img = new Image();
    img.onload = function () {
      var k = Math.min(1, max / Math.max(img.width, img.height)), c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(img.width * k)); c.height = Math.max(1, Math.round(img.height * k));
      var g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(img, 0, 0, c.width, c.height);
      resolve({ url: c.toDataURL("image/jpeg", q || 0.85), w: c.width, h: c.height });
    };
    img.onerror = function () { resolve(null); };
    img.src = url;
  });
}
function addImageFile(file) {
  if (ATT.length >= 4) { api().toast("Four pictures at most in one message"); return; }
  var r = new FileReader();
  r.onload = function () {
    Promise.all([shrink(r.result, 1400, 0.85), shrink(r.result, 240, 0.7)]).then(function (s2) {
      if (!s2[0]) { api().toast("That picture could not be read"); return; }
      ATT.push({ kind: "picture", name: file.name || "picture", url: s2[0].url, thumb: s2[1].url });
      paintAtts();
    });
  };
  r.readAsDataURL(file);
}
function snapMap() {
  var A = api();
  if (!A || !A.ready()) return;
  var cap = A.captureMap();
  if (!cap) return;
  shrink(cap.url, 240, 0.7).then(function (t) {
    ATT.push({ kind: "map", name: "the map", url: cap.url, thumb: t && t.url, bounds: cap.bounds, grid: cap.grid });
    paintAtts();
  });
}
function sketch() {
  var A = api();
  if (!A || !A.ready()) return;
  if (A.sketching()) { A.sketchDone(); return; }
  $("ai-sketch").classList.add("on");
  el.tbarT.textContent = "Sketching on the map";
  A.sketchStart(function (res) {
    $("ai-sketch").classList.remove("on");
    el.tbarT.textContent = "";
    if (!res || !res.strokes.length) return;
    var cap = A.captureMap();
    shrink(cap.url, 240, 0.7).then(function (t) {
      ATT = ATT.filter(function (a) { return a.kind !== "sketch"; });
      ATT.push({ kind: "sketch", name: "your sketch", strokes: res.strokes, url: cap.url, thumb: t && t.url, bounds: cap.bounds, grid: cap.grid });
      paintAtts();
    });
  });
}
function paintAtts() {
  el.atts.hidden = !ATT.length;
  el.atts.innerHTML = ATT.map(function (a, i) {
    return '<span class="ai-att" title="' + esc(a.kind === "map" ? "The map as it was, with a grid in metres" : a.kind === "sketch" ? "Your sketch, on the map" : a.name) + '">' +
      (a.thumb ? '<img src="' + a.thumb + '" alt="">' : '') + '<i>' + (a.kind === "map" ? "Map" : a.kind === "sketch" ? "Sketch" : "Picture") + '</i>' +
      '<button type="button" data-i="' + i + '" aria-label="Remove it">×</button></span>';
  }).join("");
  el.atts.querySelectorAll("button[data-i]").forEach(function (b) {
    b.addEventListener("click", function () {
      var a = ATT.splice(+b.getAttribute("data-i"), 1)[0];
      if (a && a.kind === "sketch") api().setSketch(null);
      paintAtts();
    });
  });
}
function n1(v) { return Math.round(v * 10) / 10; }
// what the attachments are, for the model: where a map picture lies in the
// world, and a sketch's strokes as coordinates
function attText(list) {
  var out = [], pic = 0;
  list.forEach(function (a) {
    pic++;
    if (a.kind === "picture") out.push("Picture " + pic + " is a picture the user attached (" + a.name + ").");
    else {
      var b = a.bounds;
      out.push("Picture " + pic + " is " + (a.kind === "sketch" ? "the map with the user's sketch drawn on it" : "the map as the user sees it") +
        ": its left edge is x " + n1(b.x0) + ", its right edge x " + n1(b.x1) + ", its top y " + n1(b.y1) + " and its bottom y " + n1(b.y0) +
        " (north up); the grid lines are every " + a.grid + " m, labelled in metres.");
    }
    if (a.kind === "sketch") {
      out.push("The sketch's strokes in world metres (x east, y north), each simplified to its turning points:");
      a.strokes.forEach(function (st, i) {
        var pts = st.pts, closed = pts.length > 2 && Math.hypot(pts[0][0] - pts[pts.length - 1][0], pts[0][1] - pts[pts.length - 1][1]) < 4;
        out.push("- stroke " + (i + 1) + ", " + st.color + (closed ? ", a closed shape" : "") + ": " +
          pts.map(function (q) { return "(" + Math.round(q[0]) + ", " + Math.round(q[1]) + ")"; }).join(" "));
      });
    }
  });
  return out.join("\n");
}
var READER = "You read pictures for a mission designer working on a level of Project IGI (a 2000 stealth shooter). Say what the picture shows that matters for building a mission: the layout (what is where: left, right, top, bottom, rough sizes), buildings, walls and fences, paths and roads, marks and their colours, arrows, text written on it, how many of each thing. When it is a map with a grid in metres, give positions in those metres by reading the grid. Short plain lines, no advice.";

// ------------------------------------------------------------------ talking to a model
// One streamed turn: the events as they come (see studio/server/ai.py). Resolves
// to null, "abort", or an error message.
function streamChat(body, ev, signal) {
  if (window.AIPanel.mock) body.mock = true;
  return fetch("api/ai/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: signal })
    .then(function (res) {
      if (!res.ok || !res.body) throw new Error("The studio server answered " + res.status);
      var reader = res.body.getReader(), dec = new TextDecoder(), buf = "";
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) { if (buf.trim()) try { ev(JSON.parse(buf)); } catch (e) { /* half a line */ } return null; }
          buf += dec.decode(r.value, { stream: true });
          var lines = buf.split("\n");
          buf = lines.pop();
          lines.forEach(function (l) { if (l.trim()) try { ev(JSON.parse(l)); } catch (e) { /* not JSON */ } });
          return pump();
        });
      }
      return pump();
    })
    .catch(function (e) { return e && e.name === "AbortError" ? "abort" : "The request failed: " + (e && e.message ? e.message : e); });
}
// a light-model turn that has run 3 minutes is stopped: a small model can
// talk on without end
var LIGHT_LIMIT = 180000;
function limited(ctrl, body, got) {
  if (body.role !== "light") return 0;
  return setTimeout(function () { got.timedOut = true; try { ctrl.abort(); } catch (e) { /* over */ } }, LIGHT_LIMIT);
}
// a whole turn, quietly: {text, calls, error}
function turnOnce(body, signal) {
  var got = { text: "", calls: [], error: null }, own = new AbortController(), tm = limited(own, body, got);
  if (signal) signal.addEventListener("abort", function () { own.abort(); });
  signal = own.signal;
  return streamChat(body, function (e) {
    if (e.t === "text") got.text += e.d;
    else if (e.t === "call") got.calls.push({ id: e.id, name: e.name, args: e.args || "{}" });
    else if (e.t === "error") got.error = e.message;
    else if (e.t === "done" && RUN) { var u = e.usage || {}; RUN.lightTokens = (RUN.lightTokens || 0) + (u["in"] || 0) + (u.out || 0); }
  }, signal).then(function (err) {
    clearTimeout(tm);
    if (got.timedOut) got.error = "the light model took more than 3 minutes";
    else if (err && !got.error) got.error = err === "abort" ? "stopped" : err;
    return got;
  });
}
// one answer from the light model, no tools; null when it has none
function lightAsk(instr, text, images) {
  var ctrl = new AbortController();
  if (RUN) RUN.subs.push(ctrl);
  return turnOnce({ role: "light", instructions: instr, history: [{ k: "user", text: text, images: images || undefined }] }, ctrl.signal)
    .then(function (g) { return g.error ? null : g.text.trim(); });
}
// The scout: the light model, looking with the same tools, for the main model
var SCOUT_TOOL = { name: "scout", description: "Send the scout, a fast local model with the same looking tools (overview, places, look around, catalogue, items, the check list), to find something out; it answers briefly with ids and positions. Use it for broad look-ups (what stands round several places, which buildings could hold something, where the guards are spread) to save time and tokens; do the building and exact placing yourself.",
  parameters: { type: "object", properties: { question: { type: "string", description: "what to find out, in a sentence or two" } }, required: ["question"], additionalProperties: false } };
async function runScout(q, row, grp) {
  var A = api(), hist = [{ k: "user", text: q }], looked = [];
  var tools = A.tools("ideas").filter(function (x) { return !/^(design_|show_3d|focus_map)/.test(x.name); });
  var instr = "You are the scout for a mission designer working in Project IGI Studio (Project IGI, a 2000 stealth shooter). Find out what you are asked with the tools, then answer in at most 8 short lines with ids (L<number> for the level's things, p... for the mission's own) and positions (x, y in metres; x east, y north). Facts only, no advice.";
  for (var turn = 0; turn < 7; turn++) {
    if (!RUN || RUN.stop) return { ok: false, error: "Stopped by the user." };
    var ctrl = new AbortController(); RUN.subs.push(ctrl);
    var got = await turnOnce({ role: "light", instructions: instr, tools: tools, history: hist }, ctrl.signal);
    if (got.error) return { ok: false, error: "The scout could not answer: " + got.error };
    if (got.text.trim()) hist.push({ k: "assistant", text: got.text });
    if (!got.calls.length) return { ok: true, answer: got.text.trim().slice(0, 2500), looked: looked };
    for (var i = 0; i < got.calls.length; i++) {
      var c = got.calls[i], args = {};
      try { args = JSON.parse(c.args || "{}"); } catch (e) { args = {}; }
      hist.push({ k: "call", id: c.id, name: c.name, args: c.args });
      var r = await Promise.resolve(A.run(c.name, args, "ideas"));
      looked.push(label(c.name, args, r));
      row.sub = "Scout: " + looked.join(" · ");
      paintNode(grp); scroll();
      var o = JSON.stringify(r);
      hist.push({ k: "result", id: c.id, output: o.length > 3500 ? o.slice(0, 3500) + "…(cut)" : o });
    }
  }
  var last = await turnOnce({ role: "light", instructions: instr + " Answer now with what you have found.", history: hist });
  return { ok: !last.error, answer: (last.text || "").trim().slice(0, 2500), looked: looked, error: last.error || undefined };
}

// ------------------------------------------------------------------ the Mission builder's plan
// The Mission agent surveys, then proposes the whole mission as data
// (propose_plan): the studio checks it, shows it as a card, and outlines its
// areas on the map. Once the user agrees, the areas are built one run each
// ("Build area C now"), the agent reporting each with plan_progress, then a
// last run finishes what spans them (objectives, events, texts, checks). The
// plan and its progress are kept with the chat (CHAT.plan).
var PLAN_BEFORE = {};         // chat id -> the mission before the first area, for "Undo the whole build"
var KINDS = ["kill", "killAll", "collect", "reach", "hack", "destroy"];
var AREA_PROPS = {
  letter: { type: "string", description: "A, B, C... in the order they are built" },
  name: { type: "string", description: "a short name, e.g. \"Rail yard checkpoint\"" },
  role: { type: "string", description: "start, approach, outpost, patrol zone, objective, way out..." },
  x: { type: "number", description: "centre, metres east" }, y: { type: "number", description: "centre, metres north" },
  w: { type: "number", description: "width east-west in metres (with d: a rectangle)" }, d: { type: "number", description: "depth north-south in metres" },
  r: { type: "number", description: "or a radius in metres, for a round area" },
  turn_deg: { type: "number", description: "how far a rectangle is turned, anticlockwise" },
  ground: { type: "string", description: "ground work: level it, ramps, walkways to lay" },
  structures: { type: "string" }, guards: { type: "string", description: "how many, which kinds, posts and patrols" },
  security: { type: "string", description: "cameras, alarm system, buttons, sirens" }, pickups: { type: "string" }, notes: { type: "string" }
};
var PLAN_PROPS = {
  title: { type: "string" }, pitch: { type: "string", description: "two lines: what the mission is and what makes it good" },
  style: { type: "string", description: "stealth, assault, sniper, rescue, sabotage..." }, difficulty: { type: "string", enum: ["easy", "normal", "hard"] },
  time_of_day: { type: "string" }, weather: { type: "string", description: "as the level, clear, rain or snow" },
  time_limit_min: { type: "number" }, fail_on_alarm: { type: "boolean" },
  player_start: { type: "object", properties: { x: { type: "number" }, y: { type: "number" }, facing_deg: { type: "number" } }, required: ["x", "y"] },
  briefing: { type: "string", description: "one to three short lines" },
  way_through: { type: "string", description: "the way the player is meant to get through" }, other_ways: { type: "string" },
  areas: { type: "array", items: { type: "object", properties: AREA_PROPS, required: ["letter", "name", "role", "x", "y"] } },
  objectives: { type: "array", items: { type: "object", properties: {
    number: { type: "integer" }, kind: { type: "string", enum: KINDS }, area: { type: "string", description: "the area's letter" },
    target: { type: "string", description: "what or whom: the officer, the radio, the codes..." }, text: { type: "string", description: "under 60 characters" } }, required: ["kind", "area", "text"] } },
  events: { type: "array", items: { type: "object", properties: { when: { type: "string" }, then: { type: "string" } }, required: ["when", "then"] } }
};
var PLAN_TOOLS = [
  { name: "propose_plan", description: "Propose the whole mission as a plan: 3 to 6 areas in build order (each with its centre, size, role and what goes there), at most 6 objectives (each in an area), the events, the settings, the player start and a briefing. The studio checks it (fix what it says and propose again); the user then sees it as a card, with the areas outlined on the map. Build nothing until the user agrees.",
    parameters: { type: "object", properties: PLAN_PROPS, required: ["title", "pitch", "areas", "objectives"] } },
  { name: "update_plan", description: "Change the plan the user is looking at, as they ask: any of propose_plan's fields. Areas are matched by letter (a new letter adds an area); remove_areas drops some; objectives or events, when given, replace the lists. Say what changed in note.",
    parameters: { type: "object", properties: Object.assign({}, PLAN_PROPS, { remove_areas: { type: "array", items: { type: "string" } }, note: { type: "string" } }) } },
  { name: "plan_progress", description: "Report an area as built, or as a problem you could not solve (say what in note), once you have built it and looked at it.",
    parameters: { type: "object", properties: { area: { type: "string" }, status: { type: "string", enum: ["built", "problem"] }, note: { type: "string" } }, required: ["area", "status"] } },
  { name: "get_plan", description: "The plan as it stands, with each area's progress.", parameters: { type: "object", properties: {} } }
];
var PLAN_NAMES = PLAN_TOOLS.map(function (t) { return t.name; });
function r1(v) { return Math.round(v * 10) / 10; }
// an area as the map draws it and the tools take it
function areaBox(a) {
  var r = +a.r > 0 ? +a.r : 0, w = +a.w > 0 ? +a.w : r * 2, d = +a.d > 0 ? +a.d : r * 2;
  return { x0: a.x - w / 2, x1: a.x + w / 2, y0: a.y - d / 2, y1: a.y + d / 2, w: w, d: d, r: r };
}
function paintPlanAreas() {
  var A = api(), p = CHAT.plan;
  if (!A || !A.setPlanAreas) return;
  A.setPlanAreas(p && p.stage !== "replaced" ? p.areas.map(function (a) {
    return { letter: a.letter, name: a.name, x: a.x, y: a.y, w: areaBox(a).w, d: areaBox(a).d, r: +a.r > 0 ? +a.r : 0, turn: +a.turn_deg || 0, status: a.status };
  }) : []);
}
function cleanArea(a) {
  var o = {};
  Object.keys(AREA_PROPS).forEach(function (k) { if (a[k] != null && a[k] !== "") o[k] = a[k]; });
  o.letter = String(o.letter || "").trim().toUpperCase().slice(0, 2);
  ["x", "y", "w", "d", "r", "turn_deg"].forEach(function (k) { if (o[k] != null) o[k] = +o[k]; });
  o.status = a.status || "planned";
  if (a.note) o.note = a.note;
  return o;
}
// what is wrong with a plan (it is not shown until there is nothing), and
// what is worth a second look
function planProblems(p) {
  var A = api(), c = A.context(), ext = A.extent ? A.extent() : null, bad = [], warn = [], seen = {};
  if (!p.title) bad.push("It needs a title.");
  if (!p.areas.length) bad.push("It needs areas: 3 to 6, in the order they are built.");
  if (p.areas.length > 8) bad.push("At most 8 areas; merge some.");
  p.areas.forEach(function (a) {
    var L = a.letter || "?";
    if (!/^[A-Z]$/.test(a.letter)) bad.push("Area \"" + (a.name || L) + "\": its letter is one of A to Z.");
    if (seen[a.letter]) bad.push("Two areas are lettered " + L + ".");
    seen[a.letter] = 1;
    if (!isFinite(a.x) || !isFinite(a.y)) { bad.push("Area " + L + " needs its centre (x, y)."); return; }
    var b = areaBox(a);
    if (!(b.w > 0 && b.d > 0)) bad.push("Area " + L + " needs its size: w and d in metres, or r.");
    else if (b.w < 6 || b.d < 6 || b.w > 900 || b.d > 900) bad.push("Area " + L + " is " + Math.round(b.w) + " x " + Math.round(b.d) + " m; keep areas between 6 and 900 m across.");
    if (ext && (a.x < ext.x0 - 30 || a.x > ext.x1 + 30 || a.y < ext.y0 - 30 || a.y > ext.y1 + 30))
      bad.push("Area " + L + " at " + r1(a.x) + ", " + r1(a.y) + " is off the map (x " + Math.round(ext.x0) + " to " + Math.round(ext.x1) + ", y " + Math.round(ext.y0) + " to " + Math.round(ext.y1) + ").");
  });
  for (var i = 0; i < p.areas.length; i++) for (var j = i + 1; j < p.areas.length; j++) {
    var a = areaBox(p.areas[i]), b = areaBox(p.areas[j]);
    var ox = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0), oy = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
    if (ox > 0 && oy > 0 && ox * oy > 0.5 * Math.min(a.w * a.d, b.w * b.d))
      warn.push("Areas " + p.areas[i].letter + " and " + p.areas[j].letter + " mostly overlap.");
  }
  if (!p.objectives.length) bad.push("It needs objectives (1 to 6).");
  if (p.objectives.length > 6) bad.push("The map computer shows 6 objectives at most.");
  p.objectives.forEach(function (o, n) {
    if (KINDS.indexOf(o.kind) < 0) bad.push("Objective " + (n + 1) + ": kind is one of " + KINDS.join(", ") + ".");
    if (!seen[String(o.area || "").toUpperCase()]) bad.push("Objective " + (n + 1) + " is in area \"" + o.area + "\", which the plan doesn't have.");
    if (o.kind === "hack" && c.empty) bad.push("Objective " + (n + 1) + " is a hack, but an empty map has none of the level's terminals; make it reach, collect, kill or destroy.");
    if (o.text && o.text.length > 60) warn.push("Objective " + (n + 1) + "'s text is over 60 characters.");
  });
  if (p.player_start && ext && (p.player_start.x < ext.x0 || p.player_start.x > ext.x1 || p.player_start.y < ext.y0 || p.player_start.y > ext.y1))
    bad.push("The player start is off the map.");
  return { bad: bad, warn: warn };
}
function planOf(a, old) {
  var p = old ? JSON.parse(JSON.stringify(old)) : { areas: [], objectives: [], events: [] };
  Object.keys(PLAN_PROPS).forEach(function (k) { if (k !== "areas" && a[k] != null) p[k] = a[k]; });
  if (Array.isArray(a.areas)) a.areas.forEach(function (x) {
    var L = String(x.letter || "").trim().toUpperCase(), cur = p.areas.filter(function (y) { return y.letter === L; })[0];
    if (cur) { var st = cur.status, note = cur.note; Object.assign(cur, cleanArea(Object.assign({}, cur, x))); cur.status = st; if (note) cur.note = note; }
    else p.areas.push(cleanArea(x));
  });
  if (Array.isArray(a.remove_areas)) {
    var gone = a.remove_areas.map(function (s) { return String(s).toUpperCase(); });
    p.areas = p.areas.filter(function (x) { return gone.indexOf(x.letter) < 0; });
  }
  p.objectives = (p.objectives || []).map(function (o, i) { return Object.assign({}, o, { number: o.number || i + 1, area: String(o.area || "").toUpperCase() }); });
  p.events = p.events || [];
  return p;
}
function planTool(name, a) {
  var p = CHAT.plan;
  if (name === "get_plan") return p ? { ok: true, plan: planBrief(p) } : { ok: false, error: "There is no plan yet: survey the map, then propose_plan." };
  if (name === "plan_progress") {
    if (!p) return { ok: false, error: "There is no plan." };
    var L = String(a.area || "").toUpperCase(), ar = p.areas.filter(function (x) { return x.letter === L; })[0];
    if (!ar) return { ok: false, error: "The plan has no area " + a.area + "." };
    // built means something was: a run that changed nothing reports a problem
    if (a.status !== "problem" && RUN && RUN.planArea === L && !RUN.changes)
      return { ok: false, error: "Nothing in area " + L + " was built in this run: every change failed or none was made. Read the errors and build it another way (guards need walkways within 35 m: add_walkways first), or report status problem with what stops you." };
    ar.status = a.status === "problem" ? "problem" : "built";
    ar.note = a.note ? String(a.note).slice(0, 300) : "";
    paintPlan(); saveSoon();
    return { ok: true, area: L, status: ar.status };
  }
  var building = p && p.areas.some(function (x) { return x.status !== "planned"; });
  var next = planOf(a, name === "update_plan" ? p : null);
  if (name === "update_plan" && !p) return { ok: false, error: "There is no plan to change yet: use propose_plan." };
  var chk = planProblems(next);
  if (chk.bad.length) return { ok: false, error: "The plan isn't shown yet. Fix these and " + name + " again: " + chk.bad.join(" "), problems: chk.bad };
  next.v = (p && p.v || 0) + 1;
  next.stage = name === "update_plan" && building ? (p.stage === "done" ? "done" : "paused") : "proposed";
  if (name === "propose_plan" && p) p.stage = "replaced";
  CHAT.plan = next;
  add({ k: "plan", v: next.v, note: name === "update_plan" ? String(a.note || "The plan changed").slice(0, 200) : "" });
  paintPlan(); saveSoon();
  return { ok: true, shown: true, areas: next.areas.length, objectives: next.objectives.length, warnings: chk.warn.length ? chk.warn : undefined,
    next: "The user sees the plan now. Say in one line that it is ready and wait for their answer: they build it, or ask for changes (update_plan)." };
}
// the plan in short, for the model
function planBrief(p) {
  return { title: p.title, stage: p.stage, areas: p.areas.map(function (a) {
    var b = areaBox(a);
    return { letter: a.letter, name: a.name, role: a.role, x: r1(a.x), y: r1(a.y), size: Math.round(b.w) + " x " + Math.round(b.d) + " m", status: a.status, note: a.note || undefined };
  }), objectives: p.objectives, events: p.events };
}
// repaint every card of this chat's plan and the areas on the map
function paintPlan() {
  CHAT.view.forEach(function (b) { if (b.k === "plan") paintNode(b); });
  paintPlanAreas();
}
function planStatus(p) {
  var n = p.areas.length, built = p.areas.filter(function (a) { return a.status === "built"; }).length;
  return { n: n, built: built, left: p.areas.filter(function (a) { return a.status === "planned"; }).length };
}
function paintPlanCard(b, d) {
  var p = CHAT.plan, old = !p || b.v !== p.v;
  d.className = "ai-plan" + (old ? " old" : "");
  if (old) { d.innerHTML = '<div class="pl-h"><em>Plan</em><b>An earlier version of the plan</b></div>' + (b.note ? '<p class="pl-note">' + esc(b.note) + '</p>' : ''); return; }
  var s = planStatus(p), sets = [p.style, p.difficulty, p.time_of_day, p.weather, p.time_limit_min ? p.time_limit_min + " min" : "", p.fail_on_alarm ? "fails on alarm" : ""].filter(Boolean);
  var chip = { proposed: "Proposed", building: "Building " + s.built + " of " + s.n, finishing: "Finishing", paused: s.built + " of " + s.n + " built", done: "Built" }[p.stage] || "";
  var h = '<div class="pl-h"><em>Plan</em><b>' + esc(p.title) + '</b><span class="pl-st ' + esc(p.stage) + '">' + esc(chip) + '</span></div>' +
    (b.note ? '<p class="pl-note">' + esc(b.note) + '</p>' : '') +
    '<p>' + esc(p.pitch || "") + '</p>' + (sets.length ? '<p class="pl-sets">' + esc(sets.join(" · ")) + '</p>' : '') + '<ol class="pl-areas">';
  p.areas.forEach(function (a) {
    var bx = areaBox(a), what = [a.structures, a.guards, a.security, a.pickups].filter(Boolean).join("; ");
    h += '<li class="' + esc(a.status) + '"><i>' + esc(a.letter) + '</i><div><b>' + esc(a.name) + '</b> <span>' + esc(a.role || "") + ' · ' + Math.round(bx.w) + ' × ' + Math.round(bx.d) + ' m</span>' +
      '<small>' + (a.status === "built" ? "✓ built" : a.status === "building" ? "building…" : a.status === "problem" ? "! " + esc(a.note || "a problem") : "planned") + '</small>' +
      (what ? '<p>' + esc(what.length > 170 ? what.slice(0, 170) + "…" : what) + '</p>' : '') + '</div>' +
      '<span class="pl-b">' + (a.status === "problem" && !RUN && p.stage !== "building" && p.stage !== "finishing" ?
        '<button class="go" data-retry="' + esc(a.letter) + '" title="Try again\nBuild this area once more">Try again</button>' : '') +
      '<button class="go" data-area="' + esc(a.letter) + '" title="Show it on the map">Show</button></span></li>';
  });
  h += '</ol>';
  if (p.objectives.length) h += '<div class="pl-sub">Objectives</div><ol class="pl-obj">' + p.objectives.map(function (o) { return '<li>' + esc(o.text) + ' <span>(' + esc(o.area) + ')</span></li>'; }).join("") + '</ol>';
  if (p.events.length) h += '<div class="pl-sub">Events</div><ul class="pl-obj">' + p.events.map(function (e) { return '<li>' + esc(e.when) + ': ' + esc(e.then) + '</li>'; }).join("") + '</ul>';
  var acts = "";
  if (!RUN) {
    if (p.stage === "proposed") acts = '<button class="btn primary" data-p="all" title="Build it\nEvery area in turn, then the objectives, events and texts">Build it</button>' +
      '<button class="btn" data-p="step" title="Area by area\nIt stops after each area for you to look">Area by area</button>';
    else if (p.stage === "paused" && s.left) acts = '<button class="btn primary" data-p="all">Build the rest</button><button class="btn" data-p="next">Build the next area</button>';
    else if (p.stage === "paused") acts = '<button class="btn primary" data-p="finish" title="Finish\nObjectives, events, texts and the checks">Finish the mission</button>';
    if (PLAN_BEFORE[CHAT.id] && s.built) acts += '<button class="btn" data-p="undo" title="Undo the whole build\nThe mission goes back to how it was before area ' + esc(p.areas[0].letter) + '. Ctrl+Z brings it back.">Undo the whole build</button>';
  }
  h += acts ? '<div class="pl-acts">' + acts + '</div>' : '';
  d.innerHTML = h;
  d.querySelectorAll("[data-area]").forEach(function (bt) {
    bt.addEventListener("click", function () {
      var a = p.areas.filter(function (x) { return x.letter === bt.getAttribute("data-area"); })[0];
      if (a) api().jump(a.x, a.y);
    });
  });
  d.querySelectorAll("[data-retry]").forEach(function (bt) {
    bt.addEventListener("click", function () {
      var a = p.areas.filter(function (x) { return x.letter === bt.getAttribute("data-retry"); })[0];
      if (!a || RUN) return;
      a.status = "planned"; delete a.note;
      if (p.stage === "done") p.stage = "paused";
      planStart(false);
    });
  });
  d.querySelectorAll("[data-p]").forEach(function (bt) {
    bt.addEventListener("click", function () {
      var k = bt.getAttribute("data-p");
      if (k === "all") planStart(true); else if (k === "step" || k === "next") planStart(false);
      else if (k === "finish") planFinish(); else if (k === "undo") planUndo();
    });
  });
}
// build the plan: every area in turn (auto), or the next one and a pause
function planStart(auto) {
  var A = api(), p = CHAT.plan;
  if (RUN || !p) return;
  if (!A.editable()) { A.toast("Built-in missions are never changed. Make your own mission to build it"); return; }
  if (!PLAN_BEFORE[CHAT.id] || p.stage === "proposed") PLAN_BEFORE[CHAT.id] = A.state();
  p.auto = !!auto;
  planNext();
}
function planNext() {
  var p = CHAT.plan;
  if (!p || RUN) return;
  var a = p.areas.filter(function (x) { return x.status === "planned"; })[0];
  if (!a) { planFinish(); return; }
  p.stage = "building"; a.status = "building"; p.cur = a.letter;
  paintPlan();
  var b = areaBox(a), done = p.areas.filter(function (x) { return x.status === "built"; }).map(function (x) { return x.letter; });
  var parts = [["ground", a.ground], ["structures", a.structures], ["guards", a.guards], ["security", a.security], ["pickups", a.pickups], ["notes", a.notes]]
    .filter(function (x) { return x[1]; }).map(function (x) { return x[0] + ": " + x[1]; });
  var objs = p.objectives.filter(function (o) { return o.area === a.letter; }).map(function (o) { return o.kind + (o.target ? " " + o.target : "") + " (\"" + o.text + "\")"; });
  var text = "Build area " + a.letter + " now, and only area " + a.letter + ": \"" + a.name + "\" (" + (a.role || "area") + "), centre " + r1(a.x) + ", " + r1(a.y) + ", " +
    Math.round(b.w) + " x " + Math.round(b.d) + " m" + (a.turn_deg ? " turned " + a.turn_deg + " degrees" : "") + ". From the plan: " + (parts.join("; ") || "as the plan says") + "." +
    (objs.length ? " Objectives here, added when the mission is finished, so build what they need: " + objs.join(", ") + "." : "") +
    " Stay inside x " + r1(b.x0) + " to " + r1(b.x1) + ", y " + r1(b.y0) + " to " + r1(b.y1) + "." +
    (done.length ? " Built so far: " + done.join(", ") + "." : "") + " When it is done, look at it and call plan_progress for " + a.letter + ".";
  planRun(text, "Area " + a.letter + ": " + a.name, { planArea: a.letter });
}
function planFinish() {
  var p = CHAT.plan;
  if (!p || RUN) return;
  p.stage = "finishing"; paintPlan();
  var text = "Every area is built. Finish the mission now: the objectives with their targets as the plan says (" +
    p.objectives.map(function (o) { return o.kind + " in " + o.area + ": \"" + o.text + "\""; }).join("; ") + ")" +
    (p.events.length ? ", the events (" + p.events.map(function (e) { return e.when + ": " + e.then; }).join("; ") + ")" : "") +
    (p.player_start ? ", the player start at " + r1(p.player_start.x) + ", " + r1(p.player_start.y) : "") +
    ", the settings (" + [p.time_of_day, p.weather, p.time_limit_min ? p.time_limit_min + " minutes" : "", p.fail_on_alarm ? "fail on alarm" : ""].filter(Boolean).join(", ") + ")" +
    ", and the texts (write_texts: name \"" + p.title + "\", the briefing" + (p.briefing ? " \"" + p.briefing.replace(/\n/g, " / ") + "\"" : "") + ", objective texts, labels). Then run check_mission and stealth_check, fix what they find, and end with a short summary.";
  planRun(text, "Finishing: objectives, events, texts and the checks", { planFinish: true });
}
function planUndo() {
  var A = api(), p = CHAT.plan, s = PLAN_BEFORE[CHAT.id];
  if (RUN || !p || !s) return;
  if (!A.restore(s)) return;
  delete PLAN_BEFORE[CHAT.id];
  p.areas.forEach(function (a) { a.status = "planned"; delete a.note; });
  p.stage = "proposed";
  add({ k: "note", text: "The whole build is undone: the mission is back as it was before area " + p.areas[0].letter + ". Ctrl+Z brings it back." });
  paintPlan(); saveSoon();
}
// one step of the plan, sent the way a message is, shown as a step row
function planRun(text, label, flags) {
  var A = api();
  if (RUN || !A || !A.ready()) return;
  add({ k: "step", text: label });
  var item = { k: "user", text: text };
  CHAT.items.push(item);
  run([], item, [], flags);
}
// after a plan step's run: its area's outcome, and the next step or a pause
function planAfter(r) {
  var p = CHAT.plan;
  if (!p) return;
  if (r.planArea) {
    var a = p.areas.filter(function (x) { return x.letter === r.planArea; })[0];
    if (a && a.status === "building") {
      a.status = r.stop || r.failed ? "planned" : r.changes ? "built" : "problem";
      if (a.status === "problem") a.note = "nothing was built";
    }
    p.stage = r.stop || r.failed || !p.auto ? "paused" : "building";
  } else if (r.planFinish) p.stage = r.stop || r.failed ? "paused" : "done";
  paintPlan(); saveSoon();
  if (p.stage === "building" && p.auto) setTimeout(planNext, 500);
}
// a plan left mid-build (the page closed) picks up as paused
function planLoaded() {
  var p = CHAT.plan;
  if (p) {
    p.areas.forEach(function (a) { if (a.status === "building") a.status = "planned"; });
    if (p.stage === "building" || p.stage === "finishing") p.stage = "paused";
  }
  paintPlanAreas();
}

// ------------------------------------------------------------------ settings
function loadSettings(force) {
  if (!hasServer()) { S = null; paintChip(); return Promise.resolve(null); }
  if (S && !force) { paintChip(); return Promise.resolve(S); }
  return fetch("api/ai/settings").then(function (r) { return r.json(); }).then(function (s) {
    S = s; paintChip(); if (!CHAT.view.length) render(); return s;
  }).catch(function () { S = null; paintChip(); return null; });
}
function lightOn() { return !!(S && S.light && S.light.enabled); }
function paintChip() {
  if (!el.chip) return;
  var light = CHAT.model === "light" && lightOn();
  el.chip.hidden = !S;
  el.chip.classList.toggle("light", light);
  el.chip.textContent = !S ? "" : light ? S.light.model.replace(/^.*\//, "") + " · light" : S.model + (S.effort && S.effort !== "none" ? " · " + S.effort : "");
  el.chip.title = !S ? "" : (light ? "This chat runs on the light model\n" + S.light.model + " at " + S.light.baseUrl :
    "This chat runs on the main model\n" + S.model + ", thinking " + (S.effort || "default") + ", " + S.protocolInUse + " protocol") +
    (lightOn() ? ". Click to switch to the " + (light ? "main" : "light") + " model." : "");
}
// the chat on the other model: the light one is quicker and costs nothing, the
// main one plans better
function switchModel() {
  if (RUN || !lightOn()) { if (!lightOn() && api()) api().toast("The light model is off. Turn it on in Settings, Light model"); return; }
  CHAT.model = CHAT.model === "light" ? "main" : "light";
  paintChip(); saveSoon();
  api().toast(CHAT.model === "light" ? "This chat now runs on " + S.light.model + " (light)" : "This chat now runs on " + S.model);
}
// The AI panes of the Settings sheet: the main model (role "main") or the light
// one. Each model has a provider: OpenAI (an API key and a model) or a server
// that speaks OpenAI's API (LM Studio, vLLM, Ollama, OpenRouter: a model, its
// address, its context window, and a key if it asks for one).
var PROVIDERS = [["openai", "OpenAI"], ["compatible", "OpenAI-compatible: LM Studio, vLLM, Ollama, OpenRouter"]];
function renderSettings(host, role) {
  if (!host) return;
  role = role === "light" ? "light" : "main";
  if (!hasServer()) { host.innerHTML = '<p class="hint">The AI designer needs the studio server.</p>'; return; }
  host.innerHTML = '<p class="hint">Loading…</p>';
  loadSettings(true).then(function (s) {
    if (!s) { host.innerHTML = '<p class="hint">The AI settings did not load.</p>'; return; }
    var light = role === "light", m = light ? (s.light || {}) : s, P = light ? "ail-" : "ais-";
    // what is on the form, kept while the provider changes under it
    var st = { provider: m.provider || "openai", model: m.model || "", base: m.provider === "compatible" ? (m.baseUrl || "") : "",
      ctx: m.contextWindow || s.defaultContext || 16384, effort: m.effort || "none", on: light ? m.enabled !== false : true };
    function id(x) { return P + x; }
    function val(x) { var e = $(id(x)); return e ? e.value.trim() : ""; }
    function keep() {
      if ($(id("prov"))) st.provider = $(id("prov")).value;
      if ($(id("model"))) st.model = val("model");
      if ($(id("base"))) st.base = val("base");
      if ($(id("ctx"))) st.ctx = +val("ctx") || st.ctx;
      if ($(id("on"))) st.on = $(id("on")).checked;
    }
    function keyField(optional) {
      var saved = m.keySaved, hint = saved ? "Saved (" + esc(m.keyHint || "…") + "). Type a new one to replace it" :
        !light && m.hasKey && m.keyFrom ? "From " + esc(m.keyFrom) + " (" + esc(m.keyHint) + "). Type one to use instead" :
        light && st.provider === "openai" ? "Empty: it uses the main model's key" : optional ? "Only if the server asks for one" : "sk-...";
      return '<div class="field"><span class="lbl">API key' + (optional ? ", if it needs one" : "") + '</span><div class="ai-keyrow">' +
        '<input id="' + id("key") + '" type="password" autocomplete="off" placeholder="' + hint + '">' +
        (saved ? '<button class="btn" id="' + id("clear") + '" title="Forget the key\nThe studio no longer keeps it">Forget</button>' : '') + '</div></div>';
    }
    function paint() {
      var h = '<h3 class="set-h">' + (light ? "Light model" : "AI designer") + '</h3>' +
        '<p class="set-lead">' + (light ?
          "A quick model, local or cheap, for the chores: naming chats, reading pictures, and looking things up for the main model. A chat can also run on it (click the model name in the AI panel)." :
          "The model that plans and builds missions with you in the AI panel.") + '</p>';
      if (light) h += '<label class="set-check"><input type="checkbox" id="' + id("on") + '"' + (st.on ? " checked" : "") + '> Use a light model</label>';
      h += '<div class="set-block"' + (light && !st.on ? ' hidden' : '') + '>' +
        '<div class="field"><span class="lbl">Provider</span><select id="' + id("prov") + '">' + PROVIDERS.map(function (p) {
          return '<option value="' + p[0] + '"' + (st.provider === p[0] ? " selected" : "") + '>' + p[1] + '</option>'; }).join("") + '</select></div>';
      if (st.provider === "openai") {
        h += keyField(false) +
          '<p class="hint">A key typed here is encrypted for your Windows account and kept by the studio, never in its settings file. The page never sees it again.</p>' +
          '<div class="field"><span class="lbl">Model</span><input id="' + id("model") + '" list="' + id("models") + '" value="' + esc(st.model) + '" placeholder="gpt-5-mini">' +
          '<datalist id="' + id("models") + '"></datalist></div>' +
          '<p class="hint" id="' + id("note") + '"></p>';
      } else {
        h += '<div class="set-row2"><div class="field"><span class="lbl">Model</span><input id="' + id("model") + '" list="' + id("models") + '" value="' + esc(st.model) + '" placeholder="qwen/qwen3.5-9b">' +
          '<datalist id="' + id("models") + '"></datalist></div>' +
          '<div class="field" title="Context window\nHow much the model reads at once, in tokens, as the server loaded it"><span class="lbl">Context window (tokens)</span>' +
          '<input id="' + id("ctx") + '" type="number" min="1024" step="1024" value="' + (+st.ctx || 16384) + '"></div></div>' +
          '<div class="field"><span class="lbl">Server address</span><input id="' + id("base") + '" value="' + esc(st.base) + '" placeholder="http://localhost:1234/v1" spellcheck="false"></div>' +
          '<p class="hint">The context window is the model\'s, as the server loaded it: LM Studio calls it Context Length. Every request is fitted into it: in a long chat the oldest parts are left out first, never the newest.</p>' +
          keyField(true);
      }
      if (!light) {
        var efforts = [["none", "Off"], ["low", "Low"], ["medium", "Medium"], ["high", "High"]];
        h += '<div class="set-row2" style="margin-top:6px"><div class="field"><span class="lbl">Thinking</span><div class="seg" id="' + id("effort") + '">' + efforts.map(function (e) {
            return '<button class="btn' + (st.effort === e[0] ? " on" : "") + '" data-v="' + e[0] + '">' + e[1] + '</button>'; }).join("") + '</div></div>' +
          '<div class="set-row2"><div class="field" title="Pace\nHow long each step stays before the next, to watch it build"><span class="lbl">Pace (ms a step)</span>' +
          '<input id="' + id("pace") + '" type="number" min="0" max="3000" step="50" value="' + (s.pace != null ? s.pace : 350) + '"></div>' +
          '<div class="field" title="Steps per run\nThe most tool calls one request may make"><span class="lbl">Steps per run</span>' +
          '<input id="' + id("steps") + '" type="number" min="5" max="200" value="' + (s.maxSteps || 60) + '"></div></div></div>';
      } else {
        h += '<label class="set-check" title="Thinking\nOff answers in a couple of seconds; on, a small model can think for a minute"><input type="checkbox" id="' + id("think") + '"' +
            (st.effort && st.effort !== "none" ? " checked" : "") + '> Let it think first (much slower)</label>' +
          '<label class="set-check"><input type="checkbox" id="' + id("vision") + '"' + (m.vision !== false ? " checked" : "") + '> It reads pictures</label>';
      }
      h += '</div><div class="set-foot"><span class="ai-msg" id="' + id("msg") + '"></span>' +
        '<button class="btn" id="' + id("test") + '" title="Test\nSaves, then sends one short request with these settings">Test</button>' +
        '<button class="btn primary" id="' + id("save") + '">Save</button></div>';
      host.innerHTML = h;
      wire();
    }
    function msg(t, good) { var e = $(id("msg")); if (e) { e.textContent = t; e.className = "ai-msg " + (good === true ? "good" : good === false ? "bad" : ""); } }
    function body() {
      keep();
      var b = { provider: st.provider, model: st.model };
      if (st.provider === "compatible") { b.baseUrl = st.base; b.contextWindow = +st.ctx || 16384; }
      if (val("key")) b.apiKey = val("key");
      if (light) {
        b.enabled = st.on;
        b.effort = $(id("think")) && $(id("think")).checked ? "default" : "none";
        if ($(id("vision"))) b.vision = $(id("vision")).checked;
        return { light: b };
      }
      b.effort = st.effort;
      b.pace = +val("pace") || 0;
      b.maxSteps = +val("steps") || 60;
      return b;
    }
    function problem(b) {
      var x = light ? b.light : b;
      if (light && !x.enabled) return null;
      if (!x.model) return "Say which model";
      if (x.provider === "compatible" && !/^https?:\/\/.+/.test(x.baseUrl || "")) return "The server address starts with http:// or https://";
      if (x.provider === "compatible" && !(x.contextWindow >= 1024)) return "The context window is at least 1024 tokens";
      return null;
    }
    function save() {
      var b = body(), bad = problem(b);
      if (bad) { msg(bad, false); return Promise.reject(new Error(bad)); }
      return fetch("api/ai/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })
        .then(function (r) { return r.json(); }).then(function (n) { S = n; paintChip(); return n; });
    }
    function models() {
      var note = $(id("note"));
      fetch("api/ai/models" + (light ? "?role=light" : "")).then(function (r) { return r.json(); }).then(function (x) {
        if (!x.ok) { if (note) note.textContent = "The model list did not come: " + (x.error || "unknown error") + ". You can type a model name."; return; }
        if ($(id("models"))) $(id("models")).innerHTML = x.models.map(function (v) { return '<option value="' + esc(v) + '">'; }).join("");
        if (note) note.textContent = x.models.length + " chat models on your account. Type to pick one; the newest come first.";
      }).catch(function () { if (note) note.textContent = "The model list did not come. You can type a model name."; });
    }
    function wire() {
      $(id("prov")).addEventListener("change", function () { keep(); paint(); });
      if ($(id("on"))) $(id("on")).addEventListener("change", function () { keep(); host.querySelector(".set-block").hidden = !st.on; });
      host.querySelectorAll("#" + id("effort") + " [data-v]").forEach(function (b) {
        b.addEventListener("click", function () {
          st.effort = b.getAttribute("data-v");
          host.querySelectorAll("#" + id("effort") + " [data-v]").forEach(function (x) { x.classList.toggle("on", x === b); });
        });
      });
      $(id("save")).addEventListener("click", function () {
        save().then(function () { msg("Saved", true); m = light ? (S.light || {}) : S; if ($(id("key"))) $(id("key")).value = ""; models(); })
          .catch(function () { /* said above */ });
      });
      $(id("test")).addEventListener("click", function () {
        save().then(function () { msg("Testing…"); return fetch("api/ai/test" + (light ? "?role=light" : ""), { method: "POST" }); })
          .then(function (r) { return r.json(); }).then(function (t) { msg(t.message, !!t.ok); })
          .catch(function (e) { if (!/^(Say|The )/.test(e.message)) msg(String(e.message || e), false); });
      });
      if ($(id("clear"))) $(id("clear")).addEventListener("click", function () {
        fetch("api/ai/settings", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(light ? { light: { clearKey: true } } : { clearKey: true }) })
          .then(function (r) { return r.json(); }).then(function (n) { S = n; renderSettings(host, role); });
      });
      models();
    }
    paint();
  });
}

// ------------------------------------------------------------------ the chat on screen
function render() {
  if (!el.log) return;
  el.log.innerHTML = "";
  if (!CHAT.view.length) { el.log.appendChild(emptyState()); return; }
  CHAT.view.forEach(function (b) { el.log.appendChild(node(b)); });
  el.log.scrollTop = el.log.scrollHeight;
}
function emptyState() {
  var d = document.createElement("div");
  d.className = "ai-empty";
  var A = api(), c = A && A.ready() ? A.context() : null;
  if (!hasServer()) {
    d.innerHTML = '<h3>AI designer</h3><div class="ai-card">The AI designer needs the studio server: run <b>python -m studio</b> and open the studio from it.</div>';
    return d;
  }
  if (S && !S.hasKey) {
    d.innerHTML = '<h3>AI designer</h3><div class="ai-card"><b>Connect a model.</b> In Settings, AI designer: an OpenAI API key, or a server of your own (LM Studio, vLLM, Ollama), and a model.' +
      '<br><button class="btn primary" id="ai-go-cfg">Open settings</button></div>';
    d.querySelector("#ai-go-cfg").addEventListener("click", function () { api().openSettings("ai"); });
    return d;
  }
  var lv = c ? c.levelName : "this level", ag = AG(), card = "";
  var emptyBtn = c && c.hasEmpty ? '<button class="btn primary" id="ai-empty">New mission on an empty map</button> ' : "";
  if (c && !c.editable && ag.changes)
    card = '<div class="ai-card"><b>' + esc(c.mission || c.levelName) + ' is a built-in mission</b>, which is never changed. ' +
      (CHAT.agent === "mission" ? "Start a mission of your own, on this level's empty map or as a copy of this one." : "Make your own mission from it to change it.") +
      '<br>' + (CHAT.agent === "mission" ? emptyBtn : "") + '<button class="btn' + (CHAT.agent === "mission" && emptyBtn ? "" : " primary") + '" id="ai-copy">New mission from this</button></div>';
  else if (c && c.editable && CHAT.agent === "mission" && !c.empty)
    card = '<div class="ai-card"><b>This mission already has the level\'s buildings and guards.</b> The Mission builder builds on top of them. For a fresh start, make a mission on an empty map: terrain, sky and walkways, nothing built.' +
      (emptyBtn ? '<br>' + emptyBtn.replace(" primary", "") : "") + '</div>';
  d.innerHTML = '<h3>' + esc(ag.title) + '</h3><p>' + esc(ag.lead(lv)) + '</p>' + card +
    '<div class="ai-chips">' + ag.chips(lv).map(function (t) { return '<button class="ai-chip">' + esc(t) + '</button>'; }).join("") + '</div>';
  d.querySelectorAll(".ai-chip").forEach(function (b) { b.addEventListener("click", function () { el.input.value = b.textContent; grow(); submit(); }); });
  if (d.querySelector("#ai-copy")) d.querySelector("#ai-copy").addEventListener("click", function () { api().makeCopy(); });
  if (d.querySelector("#ai-empty")) d.querySelector("#ai-empty").addEventListener("click", function () { api().makeEmpty(); });
  return d;
}
function node(b) {
  var d = document.createElement("div");
  b._n = d;
  paintNode(b);
  return d;
}
function paintNode(b) {
  var d = b._n;
  if (!d) return;
  if (b.k === "user") {
    d.className = "ai-u"; d.textContent = b.text;
    if (b.tags && b.tags.length) { var tg = document.createElement("div"); tg.className = "ai-tags"; tg.innerHTML = tagChips(b.tags, false); d.appendChild(tg); }
    if (b.atts && b.atts.length) {
      var im = document.createElement("div"); im.className = "ai-uimgs";
      im.innerHTML = b.atts.map(function (a) { return a.thumb ? '<img src="' + a.thumb + '" alt="' + esc(a.kind) + '" title="' + esc(a.kind === "map" ? "The map" : a.kind === "sketch" ? "Your sketch" : a.name) + '">' : ""; }).join("");
      d.appendChild(im);
    }
  }
  else if (b.k === "reading") {
    d.className = "ai-reading";
    d.innerHTML = '<details><summary>Picture ' + b.n + ', as the light model reads it</summary><div>' + esc(b.text) + '</div></details>';
  }
  else if (b.k === "design") paintDesign(b, d);
  else if (b.k === "plan") paintPlanCard(b, d);
  else if (b.k === "step") { d.className = "ai-step"; d.textContent = b.text; }
  else if (b.k === "assistant") { d.className = "ai-a"; d.innerHTML = md(b.text, b.live) + (b.live ? '<span class="cursor"></span>' : ""); bindDesigns(d); }
  else if (b.k === "think") {
    d.className = "ai-think";
    d.innerHTML = '<details' + (b.live ? " open" : "") + '><summary>Thinking</summary><div class="ai-a">' + md(b.text) + '</div></details>';
  }
  else if (b.k === "tools") {
    d.className = "ai-tools";
    d.innerHTML = "";
    b.list.forEach(function (t) { d.appendChild(toolNode(t)); });
  }
  else if (b.k === "error") {
    d.className = "ai-err";
    d.innerHTML = esc(b.text) + (b.code === "nokey" || /key|auth|401|model/i.test(b.text) ? '<br><button class="btn">Open settings</button>' : "");
    var bt = d.querySelector(".btn"); if (bt) bt.addEventListener("click", function () { api().openSettings("ai"); });
  }
  else if (b.k === "note") { d.className = "ai-note"; d.textContent = b.text; }
  else if (b.k === "run") {
    d.className = "ai-runf";
    var parts = [];
    if (b.changes) parts.push(b.changes + " change" + (b.changes > 1 ? "s" : ""));
    if (b.secs) parts.push(b.secs.toFixed(1) + " s");
    if (b.tokens) parts.push(fmtK(b.tokens) + " tokens" + (b.cached ? ", " + fmtK(b.cached) + " from the cache" : ""));
    if (b.light) parts.push(fmtK(b.light) + " on the light model");
    d.innerHTML = '<span>' + esc(parts.join(" · ") || "done") + (b.undone ? " · undone" : "") + '</span>' +
      (b.changes && BEFORE[b.id] && !b.undone ? '<button class="btn" title="Undo these changes\nThe mission goes back to how it was before this request. Ctrl+Z brings the changes back.">Undo these changes</button>' : "");
    var ub = d.querySelector(".btn");
    if (ub) ub.addEventListener("click", function () {
      if (RUN) return;
      if (api().restore(BEFORE[b.id])) { b.undone = true; delete BEFORE[b.id]; paintNode(b); saveSoon(); api().toast("The mission is back as it was before that request"); }
    });
  }
}
// a design the AI made: its 3D model turning, and what to do with it
var SPINNING = null;
function paintDesign(b, d) {
  var A = api();
  d.className = "ai-dcard";
  if (A && !A.design(b.id) && b.data) A.registerDesign({ id: b.id, kind: b.kind, name: b.name, description: b.description, data: b.data, summary: b.summary });
  d.innerHTML = '<div class="pv"><em>' + (b.kind === "character" ? "New character" : "New design") + '</em></div><div class="dc-b"><b>' + esc(b.name) + '</b><span>' +
    esc(b.summary + (b.size ? " · " + b.size[0] + " × " + b.size[1] + " m" : "")) + '</span>' + (b.description ? '<p>' + esc(b.description) + '</p>' : '') +
    '<div class="dc-acts"><button class="btn" data-a="view" title="View in 3D\nA bigger turning view of it">View in 3D</button>' +
    '<button class="btn" data-a="place" title="Place it\nClick on the map where it goes; R turns it">Place</button>' +
    (b.added ? '<button class="btn done" data-a="none" disabled>In your inventory</button>' :
      '<button class="btn primary" data-a="add" title="Add to inventory\nKeep it: it appears in the inventory, for any mission">Add to inventory</button>') + '</div></div>';
  var key = A && A.designMesh(b.id);
  if (key && window.MeshSprites) {
    if (!b._viewer) b._viewer = MeshSprites.viewer();
    d.querySelector(".pv").appendChild(b._viewer.el);
    b._viewer.set(key, "own");
    if (SPINNING && SPINNING !== b && SPINNING._viewer) SPINNING._viewer.turn(-0.75, 0.5);   // one turning at a time
    SPINNING = b;
  }
  d.querySelectorAll("[data-a]").forEach(function (bt) {
    bt.addEventListener("click", function () {
      var a = bt.getAttribute("data-a");
      if (a === "view") A.designView(b.id);
      else if (a === "place") { if (!A.designPlace(b.id)) A.toast(A.editable() ? "That design is no longer here" : "Built-in missions are never changed. Make your own mission from it to place it"); }
      else if (a === "add") {
        bt.disabled = true; bt.textContent = "Adding…";
        A.designAdd(b.id).then(function () {
          b.added = true; paintDesign(b, d); saveSoon();
          A.toast("“" + b.name + "” is in your inventory, under " + (b.kind === "character" ? "Characters, Your characters" : "Structures & objects, Your designs"));
        }).catch(function (e) { bt.disabled = false; bt.textContent = "Add to inventory"; A.toast("Not added: " + (e && e.message ? e.message : e)); });
      }
    });
  });
}
function fmtK(n) { return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n); }
function toolNode(t) {
  var d = document.createElement("div");
  d.className = "ai-t " + (t.status === "run" ? "run" : t.ok ? "ok" : "bad") + (t.look ? " look" : "");
  var at = t.at && isFinite(t.at.x) ? t.at : null;
  d.innerHTML = '<div class="ai-t-h" role="button" tabindex="0" aria-expanded="false"><i class="ic">' + (t.status === "run" ? "" : t.ok ? "✓" : "!") + '</i><span>' +
    esc(t.label) + '</span>' + (at ? '<button class="go" title="Show it\nThe map goes there and selects it">Show</button>' : '<i></i>') + '</div>' +
    (t.error ? '<div class="ai-t-err">' + esc(t.error) + '</div>' : "") +
    (t.notes && t.notes.length ? '<div class="ai-t-note">' + esc(t.notes.join(" ")) + '</div>' : "") +
    (t.sub ? '<div class="ai-t-sub">' + esc(t.sub) + '</div>' : "");
  var h = d.querySelector(".ai-t-h");
  function toggle() {
    var pre = d.querySelector("pre");
    if (pre) { pre.remove(); h.setAttribute("aria-expanded", "false"); return; }
    pre = document.createElement("pre");
    pre.textContent = t.name + " " + pretty(t.args) + (t.result ? "\n\n" + pretty(t.result) : "");
    d.appendChild(pre); h.setAttribute("aria-expanded", "true");
  }
  h.addEventListener("click", function (e) { if (!e.target.closest(".go")) toggle(); });
  h.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } e.stopPropagation(); });
  var go = d.querySelector(".go");
  if (go) go.addEventListener("click", function () { api().show(t.ids || [], at, true); });
  return d;
}
function pretty(s) {
  try { var j = typeof s === "string" ? JSON.parse(s) : s; var out = JSON.stringify(j, null, 1); return out.length > 3000 ? out.slice(0, 3000) + "\n…" : out; }
  catch (e) { return String(s).slice(0, 3000); }
}
// a little markdown: headings, lists, bold, italics, code; a "Design N" heading
// becomes a card with its Build button, a "Finding N" one (Review) a card with
// its Fix button
function md(text, live) {
  var lines = String(text || "").replace(/\r/g, "").split("\n"), out = [], list = null, design = false, finding = null;
  function inline(s) {
    return esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>").replace(/(^|[\s(])_([^_\s][^_]*)_/g, "$1<i>$2</i>");
  }
  function endList() { if (list) { out.push("</" + list + ">"); list = null; } }
  function endDesign() {
    endList();
    if (design) { out.push(live ? "</div>" : '<button class="btn primary ai-build" data-design="' + esc(design) + '">Build this</button></div>'); design = false; }
    if (finding) {
      out.push(live ? "</div>" : '<button class="btn ai-fix" data-finding="' + esc(finding.t) + '" data-body="' + esc(finding.body.join(" ").slice(0, 900)) + '">Fix</button></div>');
      finding = null;
    }
  }
  lines.forEach(function (ln) {
    var m;
    if (finding && !/^\s{0,3}#{1,4}\s/.test(ln) && ln.trim()) finding.body.push(ln.replace(/^\s*[-*•]\s+|^\s*\d+[.)]\s+/, "").trim());
    if ((m = /^\s{0,3}#{1,4}\s+(.*)$/.exec(ln))) {
      var t = m[1].replace(/\*\*/g, "");
      endDesign();
      if (/^design\s+\d+/i.test(t)) { design = t; out.push('<div class="ai-design"><h4>' + inline(t) + '</h4>'); }
      else if (/^finding\s+\d+/i.test(t)) { finding = { t: t, body: [] }; out.push('<div class="ai-design ai-finding"><h4>' + inline(t) + '</h4>'); }
      else { endList(); out.push("<h4>" + inline(t) + "</h4>"); }
    } else if ((m = /^\s*[-*•]\s+(.*)$/.exec(ln))) {
      if (list !== "ul") { endList(); out.push("<ul>"); list = "ul"; }
      out.push("<li>" + inline(m[1]) + "</li>");
    } else if ((m = /^\s*\d+[.)]\s+(.*)$/.exec(ln))) {
      if (list !== "ol") { endList(); out.push("<ol>"); list = "ol"; }
      out.push("<li>" + inline(m[1]) + "</li>");
    } else if (!ln.trim()) { endList(); }
    else { endList(); out.push("<p>" + inline(ln) + "</p>"); }
  });
  endDesign();
  endList();
  return out.join("");
}
function bindDesigns(d) {
  d.querySelectorAll(".ai-build").forEach(function (b) {
    b.addEventListener("click", function () {
      if (RUN) return;
      var A = api();
      if (!A.editable()) { A.toast("Built-in missions are never changed. Make your own mission from it to build"); return; }
      setAgent("mission");
      el.input.value = "Plan and build " + b.getAttribute("data-design") + ", from the suggestions above.";
      submit();
    });
  });
  // a Review finding, handed to Edit to fix
  d.querySelectorAll(".ai-fix").forEach(function (b) {
    b.addEventListener("click", function () {
      if (RUN) return;
      var A = api();
      if (!A.editable()) { A.toast("Built-in missions are never changed. Make your own mission from it to fix it"); return; }
      setAgent("edit");
      el.input.value = "Fix " + b.getAttribute("data-finding").replace(/^finding\s+\d+:\s*/i, "the review's finding: ") + ". " + b.getAttribute("data-body");
      submit();
    });
  });
}
function add(b) {
  if (!CHAT.view.length) el.log.innerHTML = "";
  CHAT.view.push(b);
  el.log.appendChild(node(b));
  scroll();
  return b;
}
var scrollPending = false;
function scroll() {
  if (scrollPending) return;
  scrollPending = true;
  requestAnimationFrame(function () { scrollPending = false; el.log.scrollTop = el.log.scrollHeight; });
  setTimeout(function () { el.log.scrollTop = el.log.scrollHeight; }, 0);
}
function status(t) {
  if (!el.status) return;
  el.status.hidden = !t;
  el.statusT.textContent = t || "";
}

// ------------------------------------------------------------------ what a step is called
var LOOKS = { get_overview: "Looked at the mission and the level", check_mission: "Ran the check list", focus_map: "Showed you the map there",
  stealth_check: "Checked how stealthy it is", list_missions: "Looked through your missions", scout: "Asked the scout",
  list_catalog: "Looked through the catalogue", show_3d: "Opened the 3D view" };
function label(name, a, r) {
  a = a || {}; r = r || {};
  var where = a.place ? " at " + a.place : "";
  switch (name) {
    case "find_places": return "Looked for places" + (a.query ? " named “" + a.query + "”" : "");
    case "look_around": return "Looked around" + (a.place ? " " + a.place : r.at && r.at.name ? " " + r.at.name : a.x != null ? " " + Math.round(a.x) + ", " + Math.round(a.y) : "");
    case "list_catalog": return "Looked through the " + (a.kind || "catalogue");
    case "get_item": return "Looked at " + ((r.item && r.item.name) || a.id || "a thing");
    case "check_mission": return r.ok ? "Checked the mission: " + r.problems + " problem" + (r.problems === 1 ? "" : "s") + ", " + r.warnings + " warning" + (r.warnings === 1 ? "" : "s") : "Checked the mission";
    case "place_guards": return "Placed " + ((r.placed && r.placed.length) || a.count || (a.positions || []).length || "") + " × " + (r.type_label || typeName(a.type) || "guard") + where;
    case "edit_guard": return "Changed " + ((r.guard && r.guard.name) || "a guard");
    case "set_patrol": return "Patrol of " + ((r.stops && r.stops.length) || 0) + " stops for " + ((r.guard && r.guard.name) || "a guard");
    case "place_object": return "Placed " + ((r.placed && r.placed[0] && r.placed[0].name) || a.model || "a structure") + where;
    case "place_fence": return "Ran a " + (a.kind === "wall" ? "wall" : "fence") + (r.panels ? ", " + r.panels + " panels, " + r.length_m + " m" : "");
    case "build_compound": return "Built a fenced compound" + where + (r.pieces ? ", " + r.pieces + " pieces" : "");
    case "place_pickup": return "Placed " + ((r.placed && r.placed[0] && r.placed[0].name) || a.item || "an item") + where;
    case "place_camera": return "Camera " + (r.mounted_on ? "on " + r.mounted_on : "placed") + (r.mounted_on && a.place && r.mounted_on.toLowerCase() === String(a.place).toLowerCase() ? "" : where);
    case "place_alarm_part": return "Added " + ({ button: "an alarm button", siren: "a siren", light: "an alarm light", system: "an alarm system" }[a.kind] || "alarm hardware") + where;
    case "move_item": return "Moved " + ((r.item && r.item.name) || a.id || "a thing");
    case "remove_item": return "Removed " + (r.removed || a.id || "a thing");
    case "add_objective": return "Objective " + (r.number || "") + ": " + ({ kill: "eliminate", killAll: "eliminate everyone", collect: "collect", reach: "reach", hack: "hack", destroy: "destroy" }[a.kind] || a.kind) + (a.text ? ", “" + a.text + "”" : "");
    case "remove_objectives": return "Removed " + (r.removed != null ? r.removed : "") + " objective" + (r.removed === 1 ? "" : "s");
    case "add_event": return "Event " + (r.number || "") + (a.name ? " “" + a.name + "”" : "") + (r.event ? ": " + r.event.does : "");
    case "set_settings": return "Time and weather" + (r.settings ? ": " + settingsText(r.settings) : "");
    case "set_mission_info": return "Named the mission" + (r.name ? " “" + r.name + "”" : "");
    case "set_player_start": return "Moved the player start";
    case "design_structure": return "Designed “" + (a.name || "a structure") + "”";
    case "design_character": return "Designed a character, “" + (a.name || "") + "”";
    case "place_design": return "Placed “" + (r.name || a.id) + "”" + where;
    case "scout": return "Scout: " + (r.answer ? "“" + String(a.question || "").slice(0, 70) + "”" : String(a.question || "").slice(0, 80));
    case "add_walkways": return "Walkways" + where + (r.added ? ": " + r.added + " points" + (r.length_m ? ", " + Math.round(r.length_m) + " m" : "") : "");
    case "shape_ground": return ({ level: "Levelled", raise: "Raised", lower: "Lowered", smooth: "Smoothed", ramp: "A ramp in" }[a.mode] || "Shaped") + " the ground" + where + (r.area ? ", " + r.area.size : "");
    case "remove_ground_area": return "Took out a ground area";
    case "stealth_check": return "Stealth check" + (r.overall ? ": " + r.overall : "");
    case "write_texts": return "Wrote the texts" + (r.wrote ? ": " + r.wrote.join(", ") : "");
    case "make_versions": return "Made " + ((r.made && r.made.length) || "") + " version" + (r.made && r.made.length === 1 ? "" : "s") + (r.made ? ": " + r.made.map(function (m) { return m.difficulty; }).join(", ") : "");
    case "list_missions": return "Looked through your missions";
    case "propose_plan": return r.ok ? "Proposed the plan “" + (a.title || "") + "”: " + r.areas + " areas" : "Tried a plan; the studio found problems";
    case "update_plan": return r.ok ? "Changed the plan" + (a.note ? ": " + String(a.note).slice(0, 60) : "") : "Tried to change the plan";
    case "plan_progress": return "Area " + String(a.area || "").toUpperCase() + ": " + (r.ok === false ? "not taken as built" :
      a.status === "problem" ? "a problem" + (a.note ? ", " + String(a.note).slice(0, 60) : "") : "built");
    case "get_plan": return "Read the plan";
    case "make_campaign": return "A campaign" + (a.name ? ", “" + a.name + "”" : "") + (r.missions ? " of " + r.missions + " missions" : "");
  }
  return LOOKS[name] || name.replace(/_/g, " ");
}
function typeName(t) { if (!t) return ""; var s = String(t).replace(/^AITYPE_/, "").replace(/_/g, " ").toLowerCase(); return s.charAt(0).toUpperCase() + s.slice(1); }
function settingsText(s) {
  var p = [];
  if (s.time_limit_s) p.push(Math.floor(s.time_limit_s / 60) + ":" + ("0" + s.time_limit_s % 60).slice(-2));
  if (s.weather && s.weather !== "as the level") p.push(s.weather);
  if (s.haze != null) p.push("haze");
  if (s.fail_on_alarm) p.push("fails on alarm");
  return p.join(", ") || "as the level";
}

// ------------------------------------------------------------------ the prompt
function instructions() {
  var c = api().context(), ag = AG(), has = function (k) { return ag.kinds.indexOf(k) >= 0; };
  var team = ORDER.map(function (k) { return AGENTS[k].label + " (" + AGENTS[k].hint.replace(/\.$/, "").toLowerCase() + ")"; }).join("; ");
  var P = [
    "You are the " + ag.label + " agent of the AI designer inside Project IGI Studio, an editor for Project IGI: I'm Going In (2000). The designer is a team of agents, each with its own job: " + team + ". The user picks the agent above the chat; when they ask for another agent's job, say which one does it. You work on the mission open in the editor through tools; each change appears on the user's map as it is made.",
    "",
    "The game: the player, David Jones, is a lone infiltrator who gets into enemy bases on foot with a few weapons, binoculars and a map computer. A mission is a set of objectives (eliminate a guard or everyone, collect an item, reach an area, hack a terminal, destroy something) in a base held by soldiers who stand guard or patrol walkways, snipers on towers, security cameras and alarm systems that bring reinforcements. A good mission has a clear goal, more than one way in, guards who cover each other, cover to move through, risk that rises near the objective, and a reward for staying unseen.",
    "",
    "The map: metres, x east, y north, z up. Facing is a compass bearing: 0 north, 90 east. Ids: the level's things are L<number>, yours start with p. Use the names the map has for places (find_places).",
    "",
    "Rules of the game engine (break them and the mission misbehaves):",
    "- Guards walk to the level's walkways (its navmesh) when the mission starts. Give place_guards a point or a place and it puts them on walkway points there. A guard more than 25 m from a walkway walks off towards it.",
    "- Snipers and lookouts on a tower: place_guards with positions inside the tower and floor \"top\" (look_around shows a building's floors).",
    "- Cameras mount on a wall within 4 m, else on a 3 m post; each raises the nearest alarm system when it sees the player. An area with no alarm system needs one (place_alarm_part system) for cameras and buttons to matter.",
    "- The map computer shows 6 objectives. The level's own objectives stay until removed: for a new mission, remove them (remove_objectives with level_objectives true) and add your own. Give each objective a short text.",
    "- hack targets are the level's own terminals; kill, destroy and collect need targets the game can test (no_task_id means it can't).",
    "- Keep a way on foot from the player start to every objective, and don't wall the player in.",
    "- Building the mission into the game (Apply) is the user's action. Never say the mission is in the game.",
    "",
    "Places the user tags: a message can end with places tagged on the map ([A], [B]...). Then \"here\", \"this area\" and the like mean them: look_around a tagged place first, and keep what you build for an area inside its bounds.",
    ""
  ];
  if (has("design")) P.push("New things for the inventory: design_structure makes a design out of the game's structures (with guards and pickups if it needs them): a guard post, a sniper nest, a checkpoint, a weapons cache, a bunker entrance. design_character makes a character: a guard type with a model of its kind, a weapon and sight of its own. The user sees each in 3D in the chat and adds it to the inventory if they like it" +
    (has("build") ? "; place_design places one" : "") + ". Make designs that look right: parts meet or overlap slightly, stand on the ground (dz 0) unless stacked, face sensibly, and keep to a sensible size (use sizes from list_catalog). New weapon types and new 3D models can't be made: design with what the game has.", "");
  if (has("ground")) P.push("Walkways and ground: add_walkways lays walkway points from the nearest walkway to a place (and round it), so guards can stand and patrol where there were none; put guards there after. shape_ground levels, raises, lowers, smooths or ramps the ground (the game moves it 4 m at most); sculpt_terrain makes big natural shapes.", "");
  if (!ag.drop || !ag.drop.test("stealth_check")) P.push("Stealth: stealth_check works out the quietest way on foot from the player start to each objective, how much of it the guards and cameras watch, and who watches it. Use it to judge and tune a mission (the user sees the routes on the map), then suggest or make fixes.", "");
  if (has("texts")) P.push("Texts: write_texts sets the mission's name and one-line description (what the game's mission list shows), the objective texts, the map computer labels of the mission's buildings, and a short briefing shown at the start. Write them the way the game does: terse military orders in plain English, like \"Infiltrate the airbase and locate the flight recorder.\" or \"Destroy the SAM radar.\"; objectives under 60 characters, labels under 20.", "");
  if (has("library")) P.push("Versions and campaigns: make_versions makes easy and hard copies of this mission in the user's library (fewer or more guards, sight, time limit, alarm). list_missions lists the user's missions; make_campaign puts several in order under a name and a briefing, for the user to export as one pack.", "");
  P.push(
    "Pictures: a message can come with pictures: a sketch, a screenshot, the map with a grid in metres, or a sketch drawn on the map (its strokes are given as exact coordinates; use those). Turn what they show into " + (has("build") ? "the mission: walls and fences where lines are drawn, guards and objectives where marked" : "what you make") + ". If it is unclear which colour means what, say what you assume.",
    "",
    "The scout: when there is a scout tool, it is a fast local model with the looking tools; send it on broad look-ups to save time, and keep the planning and " + (has("build") ? "building" : "designing") + " to yourself.",
    "",
    "Always: keep messages short and plain, and never use long dashes. When a call fails, read the error and try another way; don't repeat a failing call unchanged.",
    "");
  P.push.apply(P, ag.prompt);
  P.push("",
    "Now: the mission \"" + c.mission + "\" on " + c.levelName + " (level " + c.level + ")" + (c.empty ? ", made from the level's empty map" : "") + ", " +
      (c.editable ? "which can be changed" : "a built-in mission, read only") +
      ". Yours so far: " + c.counts.yours + " things, " + c.counts.objectives + " objectives, " + c.counts.events + " events." +
      (c.selected ? " The user has selected " + c.selected.name + " (" + c.selected.id + ") at " + c.selected.x + ", " + c.selected.y + "." : "") +
      (c.group ? " The user has " + c.group + " things selected as a group." : ""));
  return P.join("\n");
}
// what goes to the model when the whole history has to be sent: old tool
// results cut short, and pictures only with the latest message
function history() {
  var n = CHAT.items.length, last = -1;
  CHAT.items.forEach(function (it, i) { if (it.k === "user") last = i; });
  return CHAT.items.map(function (it, i) {
    if (it.k === "result" && i < n - 40 && it.output && it.output.length > 400) return { k: "result", id: it.id, output: it.output.slice(0, 400) + "…(cut)" };
    if (it.images && i !== last) return { k: "user", text: it.text + "\n(Pictures were attached to this message.)" };
    return it;
  });
}

// ------------------------------------------------------------------ a run
function submit() {
  var text = el.input.value.trim();
  if (!text || RUN) return;
  var A = api();
  if (!A || !A.ready()) { A && A.toast("The level is still loading. Try again in a moment"); return; }
  if (!hasServer()) { render(); return; }
  if (S && !S.hasKey) { render(); return; }
  if (AG().changes && !A.editable()) {
    CHAT.agent = "ideas"; paintMode();
    add({ k: "note", text: "Built-in missions are never changed, so this goes to Ideas. Make your own mission from it to build." });
  }
  // a plain yes to the Mission builder's plan builds it
  var pl = CHAT.plan;
  if (CHAT.agent === "mission" && pl && !TAGS.length && !ATT.length && (pl.stage === "proposed" || pl.stage === "paused") &&
      /^(yes|yep|yeah|ok(ay)?|sure|go( ahead| on)?|build( it| it all| the plan| the rest)?|do it|looks good|start|continue|next( area)?)[\s.!]*$/i.test(text)) {
    el.input.value = ""; grow();
    add({ k: "user", text: text });
    if (!pl.areas.some(function (a) { return a.status === "planned"; })) planFinish();
    else planStart(!/^next/i.test(text));
    return;
  }
  el.input.value = ""; grow();
  var tags = TAGS.slice(), atts = ATT.slice();
  if (!CHAT.title) CHAT.title = text.replace(/\s+/g, " ").split(" ").slice(0, 7).join(" ").slice(0, 48);
  add({ k: "user", text: text, tags: tags, atts: atts.map(function (a) { return { kind: a.kind, name: a.name, thumb: a.thumb }; }) });
  var full = text + (tags.length ? "\n\n" + tagText(tags) : "") + (atts.length ? "\n\n" + attText(atts) : "");
  var item = { k: "user", text: full };
  if (atts.length) item.images = atts.map(function (a) { return { url: a.url }; });
  CHAT.items.push(item);
  TAGS = []; paintTags();
  ATT = []; paintAtts();
  paintThread();
  run(tags, item, atts);
}
function stop() {
  if (!RUN) return;
  RUN.stop = true;
  if (RUN.ctrl) try { RUN.ctrl.abort(); } catch (e) { /* already over */ }
  (RUN.subs || []).forEach(function (c) { try { c.abort(); } catch (e) { /* over */ } });
  status("Stopping…");
}
function run(tags, item, atts, flags) {
  var A = api(), ag = AG();
  RUN = { id: "r" + Date.now().toString(36), stop: false, ctrl: null, subs: [], steps: 0, changes: 0, t0: performance.now(), tokens: 0, cached: 0,
    agent: CHAT.agent, kinds: ag.kinds, planArea: flags && flags.planArea || null, planFinish: !!(flags && flags.planFinish),
    before: ag.changes && A.editable() ? A.state() : null, max: (S && S.maxSteps) || 60, pace: S && S.pace != null ? S.pace : 350, tags: tags || [] };
  A.setTags(RUN.tags.concat(TAGS));
  if (CHAT.plan) paintPlan();                // no plan buttons while it works
  el.send.textContent = "Stop";
  el.send.classList.remove("primary");
  el.send.title = "Stop\nEnds this request now";
  el.panel.querySelectorAll("[data-agent]").forEach(function (b) { b.disabled = true; });
  (async function () {
    try {
      // the light model reads the pictures first, and what it sees goes with them
      if (atts && atts.length && lightOn() && S.light.vision !== false && CHAT.model !== "light") {
        for (var pi = 0; pi < atts.length && !RUN.stop; pi++) {
          status("The light model is reading picture " + (pi + 1) + "…");
          var ctx = "The level is " + A.context().levelName + ". " + attText([atts[pi]]).replace(/^Picture 1/, "This picture");
          var seen = await lightAsk(READER, ctx, [{ url: atts[pi].url }]);
          if (seen) {
            item.text += "\n\nPicture " + (pi + 1) + ", as the light model reads it:\n" + seen.slice(0, 1800);
            add({ k: "reading", n: pi + 1, text: seen.slice(0, 1800) });
          }
        }
      }
      while (!RUN.stop) {
        status("Thinking…");
        var turn = await ask();
        if (turn.error) { RUN.failed = true; add({ k: "error", text: turn.error, code: turn.code }); break; }
        if (turn.aborted) break;
        if (!turn.calls.length) break;
        for (var i = 0; i < turn.calls.length; i++) {
          var c = turn.calls[i];
          if (RUN.stop) { CHAT.items.push({ k: "result", id: c.id, output: JSON.stringify({ ok: false, error: "Stopped by the user before this ran." }) }); continue; }
          await step(c);
        }
        RUN.steps += turn.calls.length;
        if (RUN.steps >= RUN.max) { add({ k: "note", text: "Stopped after " + RUN.steps + " steps, the most one request may take (Settings). Say \"go on\" to continue." }); break; }
      }
    } catch (e) {
      RUN.failed = true;
      add({ k: "error", text: "Something went wrong: " + (e && e.message ? e.message : e) });
    }
    finish();
  })();
}
function finish() {
  var r = RUN;
  RUN = null;
  status("");
  el.send.textContent = "Send";
  el.send.classList.add("primary");
  el.send.title = "Send\nEnter sends, Shift+Enter starts a new line";
  el.panel.querySelectorAll("[data-agent]").forEach(function (b) { b.disabled = false; });
  if (r.stop) add({ k: "note", text: "Stopped." });
  if (r.before && r.changes) BEFORE[r.id] = r.before;
  api().setTags(TAGS);
  api().setSketch(ATT.some(function (a) { return a.kind === "sketch"; }) ? undefined : null);
  add({ k: "run", id: r.id, changes: r.changes, secs: (performance.now() - r.t0) / 1000, tokens: r.tokens, cached: r.cached, light: r.lightTokens || 0 });
  el.usage.textContent = r.tokens ? fmtK(r.tokens) + " tokens last request" + (r.lightTokens ? ", " + fmtK(r.lightTokens) + " on the light model" : "") : "";
  save();
  nameChat();
  if (r.planArea || r.planFinish) planAfter(r);
  else if (CHAT.plan) paintPlan();          // its buttons come back
  el.input.focus();
}
// one model turn, streamed in
function ask() {
  return new Promise(function (resolve) {
    var ctrl = new AbortController(), turn = { text: "", calls: [], responseId: null, error: null, aborted: false }, block = null, think = null;
    RUN.ctrl = ctrl;
    var light = CHAT.model === "light" && lightOn(), tools = agentTools(RUN.agent);
    if (lightOn() && !light) tools = tools.concat([SCOUT_TOOL]);
    var body = { instructions: instructions(), tools: tools, history: history(), previousId: light ? null : CHAT.responseId,
      fresh: light ? 0 : CHAT.synced, role: light ? "light" : "main", agent: RUN.agent };
    var paintT = 0;
    function paint(b) { var now = performance.now(); if (now - paintT > 40) { paintT = now; paintNode(b); scroll(); } }
    function ev(e) {
      if (e.t === "text") {
        if (!block) block = add({ k: "assistant", text: "", live: true });
        if (think && think.live) { think.live = false; paintNode(think); }
        turn.text += e.d; block.text = turn.text; paint(block); status("Writing…");
      } else if (e.t === "think") {
        if (!think) think = add({ k: "think", text: "", live: true });
        think.text += e.d; paint(think); status("Thinking…");
      } else if (e.t === "callstart") {
        status("Getting ready: " + (LOOKS[e.name] || e.name.replace(/_/g, " ")) + "…");
      } else if (e.t === "call") {
        turn.calls.push({ id: e.id, name: e.name, args: e.args || "{}" });
      } else if (e.t === "done") {
        turn.responseId = e.responseId || null;
        var u = e.usage || {};
        RUN.tokens += (u["in"] || 0) + (u.out || 0);
        RUN.cached += u.cached || 0;
        if (e.status === "incomplete" && e.why) turn.note = "The answer was cut short (" + e.why + ").";
      } else if (e.t === "error") {
        turn.error = e.message; turn.code = e.code;
      }
    }
    var tm = limited(ctrl, body, turn);
    streamChat(body, ev, ctrl.signal)
      .then(function (err) {
        clearTimeout(tm);
        if (turn.timedOut) turn.error = "The light model took more than 3 minutes on one answer, so it was stopped. Try the main model for this.";
        else if (err === "abort") turn.aborted = true;
        else if (err) turn.error = turn.error || err;
        if (block) { block.live = false; if (!block.text.trim()) { CHAT.view.splice(CHAT.view.indexOf(block), 1); block._n.remove(); } else paintNode(block); }
        if (think) { think.live = false; paintNode(think); }
        if (turn.text.trim()) CHAT.items.push({ k: "assistant", text: turn.text });
        if (!turn.error && !turn.aborted) {
          turn.calls.forEach(function (c) { CHAT.items.push({ k: "call", id: c.id, name: c.name, args: c.args }); });
          if (!light) {                 // the light model gets the whole history each time; the main one chains
            CHAT.responseId = turn.responseId;
            CHAT.synced = CHAT.items.length;
          }
        }
        if (turn.note) add({ k: "note", text: turn.note });
        resolve(turn);
      });
  });
}
// one tool call: run in the editor, shown as a row, the map following
async function step(c) {
  var A = api(), args = {};
  try { args = c.args ? JSON.parse(c.args) : {}; } catch (e) { args = null; }
  var look = c.name === "scout" || PLAN_NAMES.indexOf(c.name) >= 0 || A.isLook(c.name);
  var grp = CHAT.view[CHAT.view.length - 1];
  if (!grp || grp.k !== "tools") grp = add({ k: "tools", list: [] });
  var t = { name: c.name, args: c.args, look: look, status: "run", label: label(c.name, args || {}, {}) };
  grp.list.push(t); paintNode(grp); scroll();
  status(t.label + "…");
  var res;
  if (args == null) res = { ok: false, error: "The arguments were not valid JSON." };
  else if (c.name === "scout") res = await runScout(String(args.question || ""), t, grp);
  else if (PLAN_NAMES.indexOf(c.name) >= 0) {
    if (RUN.kinds.indexOf("plan") < 0) res = { ok: false, error: "Plans are the Mission builder's; this agent has none." };
    else res = planTool(c.name, args);
  }
  else {
    try { res = await Promise.resolve(A.run(c.name, args, RUN.kinds)); }
    catch (e) { res = { ok: false, error: String(e && e.message ? e.message : e) }; }
  }
  if (!res || typeof res !== "object") res = { ok: false, error: "No answer from the tool." };
  t.status = "done"; t.ok = !!res.ok; t.error = res.ok ? null : res.error; t.notes = res.notes || null;
  t.label = label(c.name, args || {}, res); t.at = res.at || null; t.ids = res.ids || null;
  var out = JSON.stringify(res);
  t.result = out.length > 4000 ? out.slice(0, 4000) + "…" : out;
  if (res.ok && !look) { RUN.changes++; A.show(res.ids || [], res.at, FOLLOW); }
  paintNode(grp); scroll();
  if (res.ok && res.design) {
    var dsg = A.design(res.design.id) || {};
    add({ k: "design", id: res.design.id, kind: res.design.kind, name: res.design.name, summary: res.design.summary, size: res.design.size_m || null,
      description: res.design.description || "", data: dsg.data || null, added: false });
  }
  CHAT.items.push({ k: "result", id: c.id, output: out.length > 6000 ? out.slice(0, 6000) + "…(cut)" : out });
  await sleep(look ? 40 : RUN.pace);
}

// ------------------------------------------------------------------ keeping it: chat threads
// Each mission keeps its chats on the server (a file each); a built-in
// mission's stay in this browser. A chat is written once it has a message.
var TS = {
  server: function () { return !!(KEY && KEY.indexOf("m:") === 0 && hasServer()); },
  url: function (tid) { return "api/missions/" + encodeURIComponent(KEY.slice(2)) + "/ai" + (tid ? "/" + tid : ""); },
  all: function () { try { return JSON.parse(localStorage.getItem("ai:threads:" + KEY) || "{}"); } catch (e) { return {}; } },
  put: function (all) { try { localStorage.setItem("ai:threads:" + KEY, JSON.stringify(all)); } catch (e) { /* full: kept in memory */ } },
  list: function () {
    if (TS.server()) return fetch(TS.url()).then(function (r) { return r.json(); }).then(function (d) { return (d && d.threads) || []; });
    var all = TS.all();
    return Promise.resolve(Object.keys(all).map(function (k) {
      var t = all[k];
      return { id: k, title: t.title, updated: t.updated, count: (t.view || []).filter(function (b) { return b.k === "user"; }).length };
    }).sort(function (a, b) { return (b.updated || 0) - (a.updated || 0); }));
  },
  load: function (tid) {
    if (TS.server()) return fetch(TS.url(tid)).then(function (r) { return r.json(); }).then(function (d) { return d && d.ok ? d.thread : null; });
    return Promise.resolve(TS.all()[tid] || null);
  },
  save: function (tid, data) {
    if (TS.server()) return fetch(TS.url(tid), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
      .then(function (r) { return r.json(); });
    var all = TS.all();
    data.updated = Math.round(Date.now() / 1000);
    (data.view || []).forEach(function (b) { if (b.atts) b.atts.forEach(function (a) { delete a.thumb; }); });   // a browser keeps little
    all[tid] = data; TS.put(all);
    return Promise.resolve({ updated: data.updated });
  },
  remove: function (tid) {
    if (TS.server()) return fetch(TS.url(tid), { method: "DELETE" }).then(function (r) { return r.json(); });
    var all = TS.all(); delete all[tid]; TS.put(all);
    return Promise.resolve({ ok: true });
  }
};
function snapshot() {
  // pictures go to the model once; only the latest message keeps its own
  var last = -1;
  CHAT.items.forEach(function (it, i) { if (it.k === "user") last = i; });
  return { title: CHAT.title, titled: !!CHAT.titled, created: CHAT.created, responseId: CHAT.responseId, synced: CHAT.synced, agent: CHAT.agent, model: CHAT.model, plan: CHAT.plan || null,
    items: CHAT.items.map(function (it, i) { if (it.images && i !== last) { var c = Object.assign({}, it); delete c.images; return c; } return it; }),
    view: CHAT.view.map(function (b) { var c = {}; for (var k in b) if (k !== "_n" && k !== "live" && k !== "_viewer") c[k] = b[k]; return c; }) };
}
var saveTimer = 0;
function saveSoon() { clearTimeout(saveTimer); saveTimer = setTimeout(save, 600); }
function save() {
  clearTimeout(saveTimer);
  if (!KEY || !CHAT.view.some(function (b) { return b.k === "user"; })) return Promise.resolve();
  if (!CHAT.created) CHAT.created = Math.round(Date.now() / 1000);
  var tid = CHAT.id, data = snapshot(), key = KEY;
  var row = THREADS.filter(function (t) { return t.id === tid; })[0];
  if (!row) { row = { id: tid }; THREADS.unshift(row); }
  row.title = CHAT.title || "Chat"; row.updated = Math.round(Date.now() / 1000);
  row.count = CHAT.view.filter(function (b) { return b.k === "user"; }).length;
  if (!el.threads.hidden) paintThreads();
  return TS.save(tid, data).catch(function () { /* the next save tries again */ }).then(function () { return key; });
}
function paintThread() {
  if (!el.threadT) return;
  el.threadT.textContent = CHAT.title || (CHAT.view.length ? "Chat" : "New chat");
  paintChip();
}
function openThread(tid) {
  if (RUN || tid === CHAT.id) { toggleThreads(false); return; }
  var want = KEY;
  save();
  TS.load(tid).then(function (d) {
    if (KEY !== want || !d) return;
    CHAT = adopt(d, tid); planLoaded();
    toggleThreads(false);
    paintMode(); paintThread(); render();
  });
}
function newChat() {
  if (RUN) return;
  save();
  var agent = CHAT.agent, model = CHAT.model;
  CHAT = blank(); CHAT.agent = agent; CHAT.model = model; paintPlanAreas();
  toggleThreads(false);
  render(); paintMode(); paintThread();
  el.input.focus();
}
function toggleThreads(on) {
  var open = on == null ? el.threads.hidden : on;
  el.threads.hidden = !open;
  el.threadBtn.setAttribute("aria-expanded", String(open));
  if (open) {
    paintThreads();
    TS.list().then(function (list) {
      // what is on the server, with this chat's latest (not written yet) in front
      var mine = THREADS.filter(function (t) { return t.id === CHAT.id; })[0];
      THREADS = list.filter(function (t) { return !mine || t.id !== mine.id; });
      if (mine) THREADS.unshift(mine);
      paintThreads();
    }).catch(function () { /* the list as it is */ });
  }
}
function ago(sec) {
  if (!sec) return "";
  var d = Date.now() / 1000 - sec;
  return d < 60 ? "just now" : d < 3600 ? Math.round(d / 60) + " min ago" : d < 86400 ? Math.round(d / 3600) + " h ago" : new Date(sec * 1000).toLocaleDateString();
}
function paintThreads() {
  var h = '<div class="ai-th-new" role="button" tabindex="0">' + IC.plus.replace("<svg", '<svg style="width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:1.8"') + 'New chat</div>';
  if (!THREADS.length) h += '<p class="hint" style="margin:6px">No chats yet about this mission.</p>';
  THREADS.forEach(function (t) {
    h += '<div class="ai-th' + (t.id === CHAT.id ? " on" : "") + '" data-t="' + esc(t.id) + '"><span><b>' + esc(t.title || "Chat") + '</b><small>' +
      esc((t.count || 0) + " message" + (t.count === 1 ? "" : "s") + " · " + ago(t.updated)) + '</small></span>' +
      '<button type="button" data-a="ren" title="Rename\nGive the chat a name of your own">Rename</button>' +
      '<button type="button" data-a="del" title="Delete\nClick twice: the chat goes for good">Delete</button></div>';
  });
  el.threads.innerHTML = h;
  el.threads.querySelector(".ai-th-new").addEventListener("click", newChat);
  el.threads.querySelectorAll(".ai-th").forEach(function (row) {
    var tid = row.getAttribute("data-t");
    row.addEventListener("click", function (e) { if (!e.target.closest("button") && !e.target.closest("input")) openThread(tid); });
    row.querySelector('[data-a="ren"]').addEventListener("click", function () {
      var t = THREADS.filter(function (x) { return x.id === tid; })[0], b = row.querySelector("b");
      var inp = document.createElement("input"); inp.value = t.title || ""; b.replaceWith(inp); inp.focus(); inp.select();
      function done(keep) {
        var v = inp.value.trim().slice(0, 60);
        if (keep && v) {
          t.title = v;
          if (tid === CHAT.id) { CHAT.title = v; CHAT.titled = true; save(); paintThread(); }
          else TS.load(tid).then(function (d) { if (d) { d.title = v; TS.save(tid, d); } });
        }
        paintThreads();
      }
      inp.addEventListener("keydown", function (e) { e.stopPropagation(); if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
      inp.addEventListener("blur", function () { done(true); });
    });
    var del = row.querySelector('[data-a="del"]');
    del.addEventListener("click", function () {
      if (!del.classList.contains("sure")) { del.classList.add("sure"); del.textContent = "Sure?"; setTimeout(function () { del.classList.remove("sure"); del.textContent = "Delete"; }, 3000); return; }
      TS.remove(tid).then(function () {
        THREADS = THREADS.filter(function (x) { return x.id !== tid; });
        if (tid === CHAT.id) { var m = CHAT.agent; CHAT = blank(); CHAT.agent = m; render(); paintMode(); paintThread(); paintPlanAreas(); }
        paintThreads();
      });
    });
  });
}
function missionChanged() {
  var A = api();
  var key = A && A.missionId() ? "m:" + A.missionId() : "builtin:" + (A && A.ready() ? A.context().level : 0);
  if (key === KEY) { if (el.log && !CHAT.view.length) render(); return; }
  if (RUN) stop();
  if (KEY) save();
  KEY = key;
  CHAT = blank(); CHAT.agent = startAgent(); THREADS = []; paintPlanAreas();
  if (el.log) { paintMode(); paintThread(); render(); }
  var want = key;
  TS.list().then(function (list) {
    if (KEY !== want) return;
    THREADS = list;
    if (list.length) {
      return TS.load(list[0].id).then(function (d) {
        if (KEY !== want || !d || CHAT.view.length) return;
        CHAT = adopt(d, list[0].id); planLoaded();
        if (el.log) { paintMode(); paintThread(); render(); }
      });
    }
  }).catch(function () { /* a new chat then */ });
}
// a better name for a chat, from the light model, once it has had its first answer
function nameChat() {
  if (CHAT.titled || !lightOn()) return;
  var first = CHAT.items.filter(function (it) { return it.k === "user"; })[0], reply = CHAT.items.filter(function (it) { return it.k === "assistant"; }).pop();
  if (!first) return;
  CHAT.titled = true;
  var tid = CHAT.id;
  lightAsk("Name this chat in 3 to 6 plain words, like a file name a person would give it. Answer with the name only, no quotes, no full stop.",
    "The user asked: " + first.text.slice(0, 600) + (reply ? "\n\nThe answer began: " + reply.text.slice(0, 400) : "")).then(function (t) {
    t = (t || "").replace(/^["'\s]+|["'.\s]+$/g, "").replace(/\s+/g, " ").slice(0, 60);
    if (!t || CHAT.id !== tid) return;
    CHAT.title = t; paintThread(); save();
  });
}

window.AIPanel = {
  missionChanged: missionChanged, renderSettings: renderSettings, show: function () { showTab("ai"); },
  // for the tests
  // the agent by id, or the old mode names ("build" is Edit)
  send: function (t, agent) { if (agent) { CHAT.agent = agent === "build" ? "edit" : AGENTS[agent] ? agent : CHAT.agent; paintMode(); } el.input.value = t; submit(); },
  agent: function () { return CHAT.agent; }, agents: function () { return ORDER.slice(); }, setAgent: function (k) { if (!RUN) setAgent(k); },
  busy: function () { return !!RUN; }, chat: function () { return CHAT; }, stop: stop,
  threads: function () { return THREADS; }, openThread: openThread, newChat: newChat, attach: function (a) { ATT.push(a); paintAtts(); },
  settings: function () { return S; }, useModel: function (m) { CHAT.model = m; paintChip(); },
  // a piece of writing, no tools: the light model when it is on, else the main one
  write: function (instr, text) {
    return lightOn() ? lightAsk(instr, text) :
      turnOnce({ role: "main", instructions: instr, history: [{ k: "user", text: text }] }).then(function (g) { return g.error ? null : g.text.trim(); });
  }
};
function boot() { if (!build()) return; if (api()) missionChanged(); }
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
