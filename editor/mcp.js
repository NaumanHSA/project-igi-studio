// The studio's MCP switch, and the road from an agent's calls to the editor's tools.
//
// An agent (Claude Desktop, Claude Code...) connects through the studio's server
// (studio/server/mcp.py) while this window is open and the person has pressed
// Start. This asks the server for the next call, runs it with the same registry
// the AI designer uses (StudioAI.run, by way of AIPanel.outsideCall, which shows it
// as a row and moves the map), and posts the answer back. So the person watches
// everything as it happens, and undo works as ever.
(function () {
"use strict";

var GEN = "w" + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
var ST = { on: false }, pumping = false, working = false, greeted = false, timer = 0, sheetOpen = false, conn = null;

function $(id) { return document.getElementById(id); }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
function A() { return window.StudioAI; }
function get(u) { return fetch(u).then(function (r) { return r.json(); }); }
function post(u, b) {
  return fetch(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) }).then(function (r) { return r.json(); });
}
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

var CSS = [
  ".mcp-btn{display:inline-flex;align-items:center;gap:7px}",
  ".mcp-dot{width:8px;height:8px;border-radius:50%;background:var(--faint);flex:none}",
  ".mcp-btn.on .mcp-dot{background:var(--player);box-shadow:0 0 7px var(--player)}",
  ".mcp-btn.busy .mcp-dot{animation:mcp-pulse .7s ease-in-out infinite}",
  "@keyframes mcp-pulse{50%{opacity:.25}}",
  "@media (prefers-reduced-motion:reduce){.mcp-btn.busy .mcp-dot{animation:none}}",
  ".mcp-state{display:flex;align-items:center;gap:12px;padding:12px 14px;border:1px solid var(--line);border-radius:6px;background:var(--sunken)}",
  ".mcp-state.on{border-color:color-mix(in srgb,var(--player) 55%,var(--line))}",
  ".mcp-state .mcp-t{flex:1;min-width:0}",
  ".mcp-state b{display:block;font-weight:600}",
  ".mcp-state small{display:block;margin-top:2px;color:var(--muted);font-size:12.5px;overflow-wrap:anywhere}",
  ".mcp-err{margin:10px 0 0;color:var(--danger,#ff8a7a)}",
  ".mcp-h{margin:18px 0 4px;font-weight:600}",
  ".mcp-row{margin:0 0 12px}",
  ".mcp-row p{margin:0 0 6px;color:var(--muted);font-size:13px}",
  ".mcp-code{display:flex;align-items:flex-start;gap:8px}",
  ".mcp-code pre{flex:1;min-width:0;margin:0;padding:8px 10px;max-height:150px;overflow:auto;font:11.5px/1.45 'IBM Plex Mono',monospace;background:var(--sunken);border:1px solid var(--line);border-radius:4px;white-space:pre-wrap;overflow-wrap:anywhere}",
  ".mcp-code .btn{flex:none}"
].join("");

function paint() {
  ["btnmcp", "lib-mcp"].forEach(function (id) {
    var b = $(id);
    if (!b) return;
    b.classList.toggle("on", !!ST.on);
    b.classList.toggle("busy", working);
    b.title = ST.on ? "MCP is on" + (ST.client ? ": " + ST.client.name + (working ? " is working" : " connected") : ", waiting for an agent to connect") + ". Click to stop it or connect another." :
      "MCP: let an agent such as Claude Desktop work in the studio";
  });
}

// ------------------------------------------------------------------ the road
function hello() {
  var brief = window.AIPanel && AIPanel.outsideBrief ? AIPanel.outsideBrief() : "";
  return post("api/mcp/hello", { gen: GEN, tools: A().catalog(), instructions: brief }).then(function (s) { greeted = true; return s; });
}
async function pump() {
  if (pumping) return;
  pumping = true;
  while (ST.on) {
    try {
      if (!greeted) await hello();
      var r = await get("api/mcp/next?gen=" + GEN + "&wait=20");
      if (!r.call) continue;
      working = true; paint();
      var res;
      try { res = await AIPanel.outsideCall(r.call); }
      catch (e) { res = { ok: false, error: String(e && e.message ? e.message : e) }; }
      working = false; paint();
      await post("api/mcp/result", { id: r.call.id, result: res });
    } catch (e) {
      working = false; paint();
      await sleep(1000);               // the server is busy or going away: ask again
    }
  }
  pumping = false;
}
function refresh() {
  return get("api/mcp/status").then(function (s) {
    var was = ST.on;
    ST = s;
    paint();
    if (ST.on && !was) { greeted = false; pump(); }
    if (sheetOpen && $("mcp-state")) paintState();
    clearTimeout(timer);
    timer = setTimeout(refresh, ST.on ? 2500 : 15000);
  }).catch(function () { timer = setTimeout(refresh, 5000); });
}

// ------------------------------------------------------------------ the sheet
function when(ms) {
  if (!ms) return "";
  var s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  return s < 5 ? "just now" : s < 90 ? s + " s ago" : Math.round(s / 60) + " min ago";
}
function paintState() {
  var box = $("mcp-state");
  if (!box) return;
  box.className = "mcp-state" + (ST.on ? " on" : "");
  var who = ST.client ? esc(ST.client.name) + (ST.calls ? ": " + ST.calls + " call" + (ST.calls > 1 ? "s" : "") + (ST.last ? ", last " + esc(ST.last) : "") + ", " + when(ST.clientSeen) : " is connected") : "No agent has connected yet";
  box.querySelector(".mcp-t").innerHTML = ST.on ?
    "<b>Running</b><small>Programs on this PC can work in the studio. " + who + ".</small>" :
    "<b>Stopped</b><small>Nothing can reach the studio from outside.</small>";
  var go = $("mcp-go");
  go.textContent = ST.on ? "Stop" : "Start";
  go.classList.toggle("primary", !ST.on);
  var err = $("mcp-err");
  err.hidden = !ST.error;
  err.textContent = ST.error || "";
}
function codeRow(id, code) {
  return '<div class="mcp-code"><pre id="' + id + '">' + esc(code) + '</pre><button class="btn" type="button" data-copy="' + id + '">Copy</button></div>';
}
function openSheet() {
  A().sheet("MCP server", '<p class="hint" style="margin:0 0 10px">Connect an AI agent, such as Claude Desktop, and it can make missions right here. You see every change as it happens, and undo works as usual. It uses your agent\'s own account, not the studio\'s AI settings.</p>' +
    '<div class="mcp-state" id="mcp-state"><div class="mcp-t"></div><button class="btn" id="mcp-go" type="button">Start</button></div>' +
    '<p class="mcp-err" id="mcp-err" hidden></p>' +
    '<div id="mcp-connect"><p class="hint" style="margin-top:14px">Loading…</p></div>');
  sheetOpen = true;
  paintState();
  $("mcp-go").addEventListener("click", function () {
    var b = this;
    b.disabled = true;
    post(ST.on ? "api/mcp/stop" : "api/mcp/start").then(function (s) {
      var was = ST.on;
      ST = s;
      paint(); paintState();
      if (ST.on && !was) { greeted = false; pump(); }
      clearTimeout(timer); timer = setTimeout(refresh, 2500);
    }).catch(function (e) { A().toast("Could not do that: " + e.message); }).then(function () { b.disabled = false; });
  });
  get("api/mcp/connect").then(function (c) { conn = c; paintConnect(); }).catch(function () {
    var box = $("mcp-connect");
    if (box) box.innerHTML = "";
  });
  // the sheet closed: stop repainting it
  var sh = $("sheet");
  (function watch() { if (sh.hidden || !$("mcp-state")) { sheetOpen = false; return; } setTimeout(watch, 800); })();
}
function paintConnect() {
  var box = $("mcp-connect"), c = conn;
  if (!box || !c) return;
  var cd = c.claudeDesktop || {};
  box.innerHTML = '<div class="mcp-h">Connect an agent</div>' +
    '<p class="hint" style="margin:0 0 12px">Once for each program. After that, press Start here and use it. If the studio is stopped, the agent is told to start it.</p>' +
    '<div class="mcp-row"><p><b>Claude Desktop</b></p>' +
    (cd.found ? (cd.added ? '<p>It is added. Restart Claude Desktop if it is running, and <b>igi-studio</b> shows among its connectors.</p>' :
      '<p>Adds the studio to its list of servers. Nothing else in its settings changes. Then restart Claude Desktop.</p><button class="btn" id="mcp-cd" type="button">Add to Claude Desktop</button>') :
      "<p>Not found on this PC. If you install it, add the settings below to its claude_desktop_config.json.</p>") + '</div>' +
    '<div class="mcp-row"><p><b>Claude Code</b>: run this once in a terminal.</p>' + codeRow("mcp-cc", c.claudeCode) + '</div>' +
    '<div class="mcp-row"><p><b>Any other program</b> (Cursor, VS Code, and so on): add this to its MCP settings.</p>' + codeRow("mcp-json", c.json) + '</div>';
  var add = $("mcp-cd");
  if (add) add.addEventListener("click", function () {
    add.disabled = true;
    post("api/mcp/claude-desktop").then(function (r) {
      if (!r.ok) { A().toast(r.error); add.disabled = false; return; }
      conn.claudeDesktop.added = true;
      paintConnect();
      A().toast("Added. Restart Claude Desktop");
    });
  });
  box.querySelectorAll("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      navigator.clipboard.writeText($(b.getAttribute("data-copy")).textContent)
        .then(function () { A().toast("Copied"); }).catch(function () { A().toast("Copy failed"); });
    });
  });
}

function start() {
  if (!document.getElementById("mcp-css")) {
    var st = document.createElement("style");
    st.id = "mcp-css";
    st.textContent = CSS;
    document.head.appendChild(st);
  }
  ["btnmcp", "lib-mcp"].forEach(function (id) { var b = $(id); if (b) b.addEventListener("click", openSheet); });
  refresh();
}

window.StudioMCP = { start: start, open: openSheet, status: function () { return ST; } };
})();
