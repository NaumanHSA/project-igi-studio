// The community: missions people share with each other - a page of its own
// over the whole window. Discover (a featured mission, the community in
// numbers, filters and cards), a mission's page (its pictures, objectives,
// intel, votes, comments, versions, where it came from and its remixes), a
// person's page, signing in (a page of two halves: what the community is, and
// the forms), and sharing (a page with its steps, and a way to frame the cover
// in the 3D view or on the map behind it).
//
// Everything goes through the studio's server (api/community/..., see
// studio/server/community.py), which holds the account and talks to the
// community's database; the rules live there (cloud/migrations). Guests
// browse and look; pulling, sharing, voting and commenting need an account.
//
// The editor's side is window.StudioCommunity (plotter.html): the open
// mission, its objectives and facts, pictures of the map and the 3D view,
// the dialog sheet, opening a mission or a preview. The look is community.css.
(function () {
"use strict";

var H = null;                         // the editor (window.StudioCommunity)
var ST = { configured: null, signed_in: false, profile: null, suggest: null };
var EL = null;                        // the page
var VIEW = null;                      // what it shows: {kind: discover | mission | profile | profile-edit | auth | share | pick | mod, ...}
var BACK = [];                        // the views before it
var LIST = { q: "", sort: "week", difficulty: "", tag: "", remixes: "", items: [], next: null, busy: false, loaded: false, err: null };
var STATS = null;                     // the community in numbers
var UPDATES = {};                     // mission here -> newer version there
var TAGS = ["stealth", "assault", "sniper", "rescue", "sabotage", "escape", "defence", "story", "timed", "hardcore", "beginner", "short"];
var TAG_IC = { stealth: "eyeOff", assault: "burst", sniper: "target", rescue: "person", sabotage: "bolt", escape: "run",
  defence: "shield", story: "film", timed: "clock", hardcore: "skull", beginner: "sparkle", short: "timer" };
var SORTS = [["week", "Trending", "fire", "Trending this week"], ["top", "Top rated", "trophy", "Top rated"],
  ["new", "Newest", "sparkle", "Newest"], ["pulled", "Most pulled", "pull", "Most pulled"], ["month", "Best this month", "star", "Best this month"]];
var DIFFS = ["easy", "normal", "hard"];
var COMMON = ["password", "password1", "12345678", "123456789", "1234567890", "qwerty123", "qwertyui", "iloveyou", "11111111",
  "00000000", "abc12345", "password123", "letmein1", "welcome1", "igistudio", "projectigi", "admin123"];

// ------------------------------------------------------------------ icons and graphics
var IC = {
  back: '<path d="M15 5l-7 7 7 7"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.3 3.6 5.1 3.6 8.5s-1.2 6.2-3.6 8.5c-2.4-2.3-3.6-5.1-3.6-8.5s1.2-6.2 3.6-8.5z"/>',
  up: '<path d="M12 4.5l7.5 8.5h-4.5v6.5h-6V13H4.5z"/>',
  down: '<path d="M12 19.5l-7.5-8.5H9V4.5h6V11h4.5z"/>',
  comment: '<path d="M4.5 5h15v10.5h-8l-4.5 4v-4h-2.5z"/>',
  pull: '<path d="M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 19.5h14"/>',
  upload: '<path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 19.5h14"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M3 3l18 18M10.6 6.1c.5-.1.9-.1 1.4-.1 6 0 9.5 6 9.5 6a16 16 0 01-3 3.7M6.6 6.6A16 16 0 002.5 12s3.5 6.5 9.5 6.5c1.6 0 3-.4 4.3-1.1M9.9 9.9a3 3 0 004.2 4.2"/>',
  cube: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  map: '<path d="M3.5 6.5l5.5-2 6 2 5.5-2v13l-5.5 2-6-2-5.5 2z"/><path d="M9 4.5v13M15 6.5v13"/>',
  flag: '<path d="M5 21V4M5 4.5h11l-2 3.5 2 3.5H5"/>',
  target: '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  pin: '<path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0113 0c0 4.8-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
  box: '<path d="M4 8l8-4 8 4v8.5l-8 4-8-4z"/><path d="M4 8l8 4 8-4M12 12v8.5M8 6l8 4"/>',
  terminal: '<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M7 9.5l3 2.5-3 2.5M12.5 15h4.5"/>',
  burst: '<path d="M12 2.5l1.9 5.4 5.4-1.9-2.8 4.9 4.9 2.9-5.6.6.5 5.7-4.3-3.7-4.3 3.7.5-5.7-5.6-.6 4.9-2.9-2.8-4.9 5.4 1.9z"/>',
  skull: '<path d="M12 3.5c-4.4 0-7.5 3-7.5 7 0 2.4 1.1 4.3 3 5.4V19h9v-3.1c1.9-1.1 3-3 3-5.4 0-4-3.1-7-7.5-7z"/><circle cx="9.3" cy="11" r="1.6"/><circle cx="14.7" cy="11" r="1.6"/><path d="M10.5 19v-2M13.5 19v-2"/>',
  shield: '<path d="M12 3l7.5 3v5.5c0 4.5-3.2 7.6-7.5 9-4.3-1.4-7.5-4.5-7.5-9V6z"/>',
  shieldCheck: '<path d="M12 3l7.5 3v5.5c0 4.5-3.2 7.6-7.5 9-4.3-1.4-7.5-4.5-7.5-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  timer: '<circle cx="12" cy="13" r="7.5"/><path d="M12 9v4l2.5 1.5M10 3h4M12 3v2.5"/>',
  snow: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M9.5 4.5L12 7l2.5-2.5M9.5 19.5L12 17l2.5 2.5"/>',
  cloud: '<path d="M7 18.5h10a4 4 0 00.6-8 6 6 0 00-11.5 1.5A3.3 3.3 0 007 18.5z"/>',
  music: '<path d="M9 18V5.5l11-2V16"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
  film: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 9.5h4M3 14.5h4M17 9.5h4M17 14.5h4"/>',
  bolt: '<path d="M13 2.5L5 13.5h6l-1 8 8-11h-6z"/>',
  camera: '<path d="M4 7.5h3l1.5-2.5h7L17 7.5h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  cctv: '<path d="M3 8.5l12-4 2 5.5-12 4z"/><path d="M15.5 10l3.5 1v3l-3 .5M6 14v5M3.5 19h5"/>',
  bell: '<path d="M6 16.5V11a6 6 0 0112 0v5.5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 004 0"/>',
  person: '<circle cx="12" cy="7.5" r="3.5"/><path d="M5 20.5c.7-4 3.4-6.5 7-6.5s6.3 2.5 7 6.5"/>',
  users: '<circle cx="9" cy="8" r="3.2"/><path d="M3 19.5c.6-3.6 3-5.8 6-5.8s5.4 2.2 6 5.8"/><path d="M15.5 4.8a3.2 3.2 0 010 6.4M17 13.9c2.2.6 3.6 2.6 4 5.6"/>',
  run: '<circle cx="14.5" cy="4.5" r="2"/><path d="M8 21l3-6 3 2.5V21M6.5 11.5l3-3.5 4 1 2.5 3 3 .5M11 8l-1.5 6"/>',
  branch: '<circle cx="6" cy="5.5" r="2.2"/><circle cx="6" cy="18.5" r="2.2"/><circle cx="18" cy="8" r="2.2"/><path d="M6 7.7v8.6M18 10.2c0 4-6 3-11 6.3"/>',
  star: '<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.3-4.1 5.9-.8z"/>',
  trophy: '<path d="M8 4.5h8v5a4 4 0 01-8 0z"/><path d="M8 6.5H5v1.5A3 3 0 008 11M16 6.5h3v1.5a3 3 0 01-3 3M12 13.5v3M8.5 20h7M10 16.5h4l.5 3.5h-5z"/>',
  fire: '<path d="M12 21c-3.9 0-6.5-2.6-6.5-6.2 0-3.3 2.6-5.3 3.6-8.3.6 1.8 1.6 2.8 2.9 3.3-.3-3 .9-5.4 3-6.8-.2 2.9 1.4 4.6 2.7 6.3 1.1 1.5 1.8 3.2 1.8 5.4 0 3.7-3 6.3-7.5 6.3z"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  mail: '<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="M3.5 7l8.5 6 8.5-6"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 018 0v2.5"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l8.5-8.5M16 7l2.5 2.5M14 9l1.5 1.5"/>',
  at: '<circle cx="12" cy="12" r="3.8"/><path d="M15.8 12v1.5a2.7 2.7 0 005.2 1V12a9 9 0 10-3.6 7.2"/>',
  logout: '<path d="M14 4.5h4.5v15H14M10 8l-4 4 4 4M6 12h10"/>',
  edit: '<path d="M4 20l1-4.5L15.5 5l3.5 3.5L8.5 19z"/><path d="M13.5 7l3.5 3.5"/>',
  trash: '<path d="M4.5 6.5h15M9.5 6.5V4.5h5v2M6.5 6.5l1 13h9l1-13"/>',
  report: '<path d="M5 21V4M5 4.5h11l-2 3.5 2 3.5H5"/><path d="M10 7v2M10 10.5v.01"/>',
  history: '<path d="M3.5 12a8.5 8.5 0 102.5-6"/><path d="M3.5 4v4h4M12 7.5V12l3 2"/>',
  tag: '<path d="M3.5 12.5V4h8.5l8.5 8.5-8 8z"/><circle cx="8" cy="8.5" r="1.5"/>',
  image: '<rect x="3" y="4.5" width="18" height="15" rx="2"/><circle cx="8.5" cy="9.5" r="1.8"/><path d="M21 16l-5-5-8 8"/>',
  layers: '<path d="M12 3.5l9 4.5-9 4.5-9-4.5z"/><path d="M3 12l9 4.5 9-4.5M3 16l9 4.5 9-4.5"/>',
  gauge: '<path d="M4.5 17a8.5 8.5 0 1115 0"/><path d="M12 14l4-5"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.01"/>',
  warn: '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17v.01"/>',
  link: '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
  file: '<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4M9 12h6M9 15.5h6"/>',
  radar: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12l6-6"/><circle cx="16" cy="9.5" r=".8"/>',
  reply: '<path d="M10 7L5 12l5 5M5 12h9a5 5 0 015 5v1"/>',
  chevron: '<path d="M6 9l6 6 6-6"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  wand: '<path d="M4 20l11-11M14 4v2M19 9h2M17.5 5.5l1.5-1.5M9.5 4l.5 1.5M19 14l1.5.5"/><path d="M13 8l3 3"/>',
  google: ''
};
function ic(n, cls) { return '<svg class="ci ' + (cls || "") + '" viewBox="0 0 24 24" aria-hidden="true">' + (IC[n] || "") + '</svg>' }
var GOOGLE = '<svg viewBox="0 0 18 18" aria-hidden="true"><path fill="#4285F4" d="M17.6 9.2c0-.6-.1-1.2-.2-1.7H9v3.3h4.8a4.1 4.1 0 0 1-1.8 2.7v2.2h2.9c1.7-1.6 2.7-3.9 2.7-6.5z"/><path fill="#34A853" d="M9 18c2.4 0 4.5-.8 6-2.2l-2.9-2.2c-.8.5-1.8.9-3.1.9-2.4 0-4.4-1.6-5.1-3.8H.9v2.3A9 9 0 0 0 9 18z"/><path fill="#FBBC05" d="M3.9 10.7a5.4 5.4 0 0 1 0-3.4V5H.9a9 9 0 0 0 0 8z"/><path fill="#EA4335" d="M9 3.6c1.3 0 2.5.5 3.5 1.4l2.6-2.6A9 9 0 0 0 .9 5l3 2.3C4.6 5.1 6.6 3.6 9 3.6z"/></svg>';
// a radar: rings, a sweep going round, blips that light as it passes
var RID = 0;
function radar(cls) {
  var id = "cmr" + (++RID);
  var blips = [[140, 60], [62, 128], [128, 150], [52, 70], [158, 118]].map(function (b) {
    var a = Math.atan2(b[1] - 100, b[0] - 100) * 180 / Math.PI;        // where the sweep's edge must be
    var d = (((a + 30) % 360) + 360) % 360 / 360 * 4;
    return '<circle class="blip" cx="' + b[0] + '" cy="' + b[1] + '" r="3.2" fill="#ffd24a" style="animation-delay:' + d.toFixed(2) + 's"/>';
  }).join("");
  return '<svg class="cmx-radar ' + (cls || "") + '" viewBox="0 0 200 200" aria-hidden="true">' +
    '<defs><radialGradient id="' + id + 'g" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#8dff9a" stop-opacity=".2"/><stop offset="1" stop-color="#8dff9a" stop-opacity="0"/></radialGradient>' +
    '<linearGradient id="' + id + 's" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#8dff9a" stop-opacity="0"/><stop offset="1" stop-color="#8dff9a" stop-opacity=".5"/></linearGradient></defs>' +
    '<circle cx="100" cy="100" r="96" fill="url(#' + id + 'g)"/>' +
    '<g fill="none" stroke="#8dff9a"><circle cx="100" cy="100" r="96" stroke-opacity=".45"/><circle cx="100" cy="100" r="72" stroke-opacity=".3"/>' +
    '<circle cx="100" cy="100" r="48" stroke-opacity=".3"/><circle cx="100" cy="100" r="24" stroke-opacity=".3"/>' +
    '<path d="M100 4v192M4 100h192" stroke-opacity=".2"/><path d="M32 32l136 136M168 32L32 168" stroke-opacity=".08"/></g>' +
    '<g class="sweep"><path d="M100 100L100 4A96 96 0 0 1 183 52Z" fill="url(#' + id + 's)"/><path d="M100 100L183 52" stroke="#b3ffbc" stroke-width="1.6"/></g>' +
    blips + '<circle cx="100" cy="100" r="3" fill="#8dff9a"/></svg>';
}

// ------------------------------------------------------------------ small things
function $(id) { return document.getElementById(id) }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] }) }
function toast(t) { if (H) H.toast(t) }
function when(iso) {
  if (!iso) return "";
  var d = new Date(iso), s = (Date.now() - d.getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  if (s < 86400 * 30) return Math.round(s / 86400) + " days ago";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")) }
function fmt(n) { n = +n || 0; return n >= 10000 ? Math.round(n / 1000) + "k" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n) }
function clock(s) { return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0") }
function hue(s) { var h = 0; s = String(s || "?"); for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0; return h % 360 }

// ------------------------------------------------------------------ the server
function api(method, path, body) {
  return fetch("api/community/" + path, {
    method: method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined
  }).then(function (r) {
    return r.json().catch(function () { return { ok: false, error: "The studio did not answer." } });
  }, function () {
    return { ok: false, error: "The studio did not answer.", code: "offline" };
  }).then(function (j) {
    if (!j.ok) { var e = new Error(j.error || "Something went wrong."); e.code = j.code; throw e }
    return j;
  });
}
function call(fn, p) { return api("POST", "rpc/" + fn, { p: p || {} }).then(function (j) { return j.result }) }
function media(id) { return id ? "api/community/media/" + id : "" }
function avatarSrc(p) {
  if (!p) return "";
  if (p.avatar) return media(p.avatar);
  if (p.avatar_url) return "api/community/avatar?u=" + encodeURIComponent(p.avatar_url);
  return "";
}
// a picture of someone, or their initial on a colour of their own
function avatar(p, size) {
  var src = avatarSrc(p), n = (p && (p.name || p.handle) || "?").trim(), h = hue(p && (p.handle || p.name));
  return src ? '<img class="cmx-av ' + (size || "") + '" src="' + esc(src) + '" alt="" loading="lazy">'
    : '<span class="cmx-av ' + (size || "") + '" style="background:linear-gradient(135deg,hsl(' + h + ' 70% 68%),hsl(' + ((h + 40) % 360) + ' 60% 48%))" aria-hidden="true">' +
      esc(n.charAt(0).toUpperCase()) + '</span>';
}
function who(p, size) {
  if (!p) return '<span class="cmx-who"><span class="cmx-av ' + (size || "") + '">?</span><i>someone who left</i></span>';
  return '<button type="button" class="cmx-who" data-profile="' + esc(p.handle) + '">' + (size === "none" ? "" : avatar(p, size)) +
    '<span><b>' + esc(p.name || p.handle) + '</b> <i>@' + esc(p.handle) + '</i></span></button>';
}
function diffPill(d) { return d ? '<span class="cmx-diff ' + esc(d) + '">' + esc(d) + '</span>' : '' }
function objIcon(kind) {
  var k = String(kind || "").toLowerCase();
  return /all/.test(k) ? "skull" : /elim|kill/.test(k) ? "target" : /reach|go to|escape/.test(k) ? "pin" : /collect|take|grab/.test(k) ? "box"
    : /hack/.test(k) ? "terminal" : /destroy|blow/.test(k) ? "burst" : "flag";
}

function refreshState() {
  return api("GET", "status").then(function (s) {
    ST = s; paintAccount();
    if (H && H.communityChanged) H.communityChanged();
    return s;
  }).catch(function (e) {
    ST = { configured: ST.configured, signed_in: false, profile: null, error: e.message };
    paintAccount();
    return ST;
  });
}
function member() { return !!(ST.signed_in && ST.profile) }
// Something that needs an account: done at once when signed in, else after
// signing in (and choosing a name) - or not at all if the person gives up.
function needAccount(why, then) {
  if (member()) { then(); return }
  if (!isOpen()) open({ kind: "discover" });
  go({ kind: "auth", step: ST.signed_in ? "name" : "signin", why: why, then: then });
}
function stats() {
  return STATS ? Promise.resolve(STATS) : call("community_stats", {}).then(function (s) { STATS = s; return s }).catch(function () { return null });
}
function statTiles(s) {
  if (!s) return "";
  return [["layers", s.missions, s.missions === 1 ? "mission" : "missions"], ["users", s.people, s.people === 1 ? "player" : "players"],
    ["pull", s.pulls, s.pulls === 1 ? "pull" : "pulls"], ["comment", s.comments, s.comments === 1 ? "comment" : "comments"]].map(function (t) {
    return '<div class="cmx-stat"><span class="ico">' + ic(t[0]) + '</span><div><b>' + fmt(t[1]) + '</b><span>' + t[2] + '</span></div></div>';
  }).join("");
}

// ------------------------------------------------------------------ the page and its header
function build() {
  if (EL) return;
  EL = document.createElement("div");
  EL.className = "cmx";
  EL.id = "community";
  EL.hidden = true;
  EL.setAttribute("role", "dialog");
  EL.setAttribute("aria-label", "Community");
  EL.innerHTML =
    '<header class="cmx-bar">' +
      '<button class="cmx-exit" id="cm-exit" title="Back to the studio (Esc)">' + ic("back") + 'Studio</button>' +
      '<div class="cmx-brand"><img src="icon.png" alt=""><span><b>Community</b><i>IGI Studio</i></span></div>' +
      '<nav class="cmx-nav" aria-label="Community">' +
        '<button data-nav="discover">' + ic("globe") + '<span>Discover</span></button>' +
        '<button data-nav="mine">' + ic("layers") + '<span>My missions</span></button>' +
        '<button data-nav="mod" hidden>' + ic("shieldCheck") + '<span>Reports</span></button>' +
      '</nav>' +
      '<label class="cmx-search">' + ic("search") + '<input id="cm-q" type="search" placeholder="Search missions, objectives, people…" aria-label="Search the community"></label>' +
      '<button class="cmx-btn primary" id="cm-share">' + ic("upload") + 'Share a mission</button>' +
      '<div class="cmx-acct" id="cm-account"></div>' +
    '</header>' +
    '<main class="cmx-main" id="cm-main"><div class="cmx-page" id="cm-body"></div></main>';
  document.body.appendChild(EL);
  $("cm-exit").addEventListener("click", hide);
  $("cm-share").addEventListener("click", function () { share() });
  EL.querySelectorAll("[data-nav]").forEach(function (b) {
    b.addEventListener("click", function () { nav(b.getAttribute("data-nav")) });
  });
  var t = null;
  $("cm-q").addEventListener("input", function () {
    clearTimeout(t);
    var v = this.value;
    t = setTimeout(function () {
      var had = !!LIST.q;
      LIST.q = v.trim();
      if (LIST.q && !had) LIST.sort = "relevance";
      if (!LIST.q && LIST.sort === "relevance") LIST.sort = "week";
      if (!VIEW || VIEW.kind !== "discover") { BACK = []; VIEW = { kind: "discover" } }
      reload();
    }, 300);
  });
  EL.addEventListener("click", function (e) {
    var t = e.target.closest("[data-profile]");
    if (t) { e.preventDefault(); go({ kind: "profile", handle: t.getAttribute("data-profile") }); return }
    t = e.target.closest("[data-mission]");
    if (t && !e.target.closest("button:not([data-mission])")) { e.preventDefault(); go({ kind: "mission", id: t.getAttribute("data-mission") }); return }
  });
  EL.addEventListener("keydown", function (e) {
    var t = e.target.closest && e.target.closest(".cmx-card[data-mission]");
    if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); go({ kind: "mission", id: t.getAttribute("data-mission") }) }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (CAP) { capEnd(null); return }
    if (!isOpen()) return;
    var sh = document.getElementById("sheet");
    if (sh && !sh.hidden) return;
    var m = $("cm-menu");
    if (m && !m.hidden) { m.hidden = true; return }
    if (BACK.length) back(); else hide();
  });
  document.addEventListener("mousedown", function (e) {
    var m = $("cm-menu");
    if (m && !m.hidden && !e.target.closest(".cmx-acct")) m.hidden = true;
  });
}
function isOpen() { return !!(EL && !EL.hidden) }
function open(view) {
  build();
  var lib = document.getElementById("start");
  if (lib) lib.hidden = true;
  EL.hidden = false;
  BACK = [];
  VIEW = view || { kind: "discover" };
  // each time it opens, what is new: from the first page again
  LIST.items = []; LIST.next = null; LIST.err = null; LIST.loaded = false; STATS = null;
  refreshState().then(function () { show() });
  show();
}
function hide() {
  if (EL) EL.hidden = true;
  if (H && H.communityClosed) H.communityClosed();
}
function go(view) {
  if (VIEW) BACK.push(VIEW);
  VIEW = view;
  show();
  var m = $("cm-main"); if (m) m.scrollTop = 0;
}
function back() { VIEW = BACK.pop() || { kind: "discover" }; show() }
function nav(where) {
  if (where === "discover") { BACK = []; VIEW = { kind: "discover" }; show(); return }
  if (where === "mod") { go({ kind: "mod" }); return }
  needAccount("see your missions", function () { go({ kind: "profile", handle: ST.profile.handle }) });
}
function paintAccount() {
  if (!EL) return;
  var a = $("cm-account");
  EL.querySelector('[data-nav="mod"]').hidden = !(ST.profile && /mod|admin/.test(ST.profile.role || ""));
  $("cm-share").hidden = ST.configured === false;
  if (!ST.configured) { a.innerHTML = ""; return }
  if (member()) {
    var p = ST.profile;
    a.innerHTML = '<button class="cmx-me" id="cm-me" aria-haspopup="menu" aria-expanded="false">' + avatar(p, "") + '<span>@' + esc(p.handle) + '</span>' + ic("chevron") + '</button>' +
      '<div class="cmx-menu" id="cm-menu" role="menu" hidden><div class="who"><b>' + esc(p.name) + '</b><span>@' + esc(p.handle) + '</span></div>' +
      '<button role="menuitem" data-m="profile">' + ic("person") + 'Your profile</button>' +
      '<button role="menuitem" data-m="mine">' + ic("layers") + 'Your missions</button>' +
      '<button role="menuitem" data-m="edit">' + ic("edit") + 'Edit your profile</button>' +
      '<button role="menuitem" data-m="out">' + ic("logout") + 'Sign out</button></div>';
    $("cm-me").addEventListener("click", function () {
      var m = $("cm-menu"); m.hidden = !m.hidden; this.setAttribute("aria-expanded", String(!m.hidden));
    });
    a.querySelectorAll("[data-m]").forEach(function (b) {
      b.addEventListener("click", function () {
        $("cm-menu").hidden = true;
        var w = b.getAttribute("data-m");
        if (w === "profile" || w === "mine") go({ kind: "profile", handle: p.handle });
        else if (w === "edit") go({ kind: "profile-edit" });
        else signOut();
      });
    });
  } else {
    a.innerHTML = '<button class="cmx-btn ghost" id="cm-signin">' + ic("person") + (ST.signed_in ? "Choose your name" : "Sign in") + '</button>';
    $("cm-signin").addEventListener("click", function () {
      if (VIEW && VIEW.kind === "auth") return;
      go({ kind: "auth", step: ST.signed_in ? "name" : "signin" });
    });
  }
}
function signOut() {
  return api("POST", "auth/signout", {}).then(refreshState).then(function () {
    toast("Signed out of the community");
    if (VIEW && (VIEW.kind === "profile-edit" || VIEW.kind === "share" || VIEW.kind === "mod")) { BACK = []; VIEW = { kind: "discover" } }
    show();
  });
}

function show() {
  if (!EL || EL.hidden) return;
  paintAccount();
  var k = VIEW ? VIEW.kind : "discover";
  EL.querySelectorAll("[data-nav]").forEach(function (b) {
    var n = b.getAttribute("data-nav");
    b.classList.toggle("on", (n === "discover" && (k === "discover" || k === "mission")) ||
      (n === "mine" && k === "profile" && ST.profile && VIEW.handle && VIEW.handle.toLowerCase() === ST.profile.handle.toLowerCase()) ||
      (n === "mod" && k === "mod"));
  });
  if ($("cm-q").value !== LIST.q && document.activeElement !== $("cm-q")) $("cm-q").value = LIST.q;
  var body = $("cm-body");
  if (ST.configured === false) {
    body.innerHTML = '<div class="cmx-hero compact" style="margin-top:22px"><div>' +
      '<div class="cmx-empty">' + radar() + '<b>The community is not open yet</b><p>Sharing missions with other players comes with an update of the studio.</p></div></div></div>';
    return;
  }
  if (k === "discover") return showDiscover(body);
  if (k === "mission") return showMission(body, VIEW.id);
  if (k === "profile") return showProfile(body, VIEW.handle);
  if (k === "profile-edit") return showProfileEdit(body);
  if (k === "auth") return showAuth(body);
  if (k === "share") return showShare(body);
  if (k === "pick") return showPick(body);
  if (k === "mod") return showReports(body);
}

// ------------------------------------------------------------------ discover
function showDiscover(body) {
  var searching = !!LIST.q;
  body.innerHTML =
    (searching
      ? '<section class="cmx-hero compact"><div><div class="cmx-over">' + ic("search") + 'Searching the community</div>' +
        '<h1>Results for “' + esc(LIST.q) + '”</h1></div></section>'
      : '<section class="cmx-hero"><div class="cmx-topo"></div>' +
        '<div><div class="cmx-over">' + ic("radar") + 'Missions from the field</div>' +
          '<h1>Play what others built.<br><em>Share what you make.</em></h1>' +
          '<p>Every mission here was made with IGI Studio. Look at its map and its 3D view, pull it into your studio, change it - and share it back.</p>' +
          '<div class="cmx-stats" id="cm-stats"></div></div>' +
        '<div class="cmx-spot" id="cm-spot">' + radar("cmx-hero-radar") + '</div></section>') +
    '<div class="cmx-browse"><aside class="cmx-filters" aria-label="Filters">' + filtersHtml() + '</aside>' +
      '<section class="cmx-results"><div class="cmx-rhead" id="cm-rhead"></div><div class="cmx-grid" id="cm-grid"></div><div class="cmx-more" id="cm-more"></div></section></div>';
  bindFilters();
  paintRhead();
  if (!searching) {
    stats().then(function (s) { var e = $("cm-stats"); if (e) e.innerHTML = statTiles(s) });
    spotlight();
  }
  if (LIST.loaded) paintCards(); else more();
}
function filtersHtml() {
  var sorts = (LIST.q ? [["relevance", "Best match", "target"]] : []).concat(SORTS);
  return '<div><div class="cmx-fh">Order</div><div class="cmx-sorts">' + sorts.map(function (s) {
      return '<button type="button" data-sort="' + s[0] + '" class="' + (LIST.sort === s[0] ? "on" : "") + '">' + ic(s[2]) + esc(s[1]) + '</button>' }).join("") + '</div></div>' +
    '<div><div class="cmx-fh">Difficulty</div><div class="cmx-pills">' +
      '<button type="button" class="cmx-pill' + (!LIST.difficulty ? " on" : "") + '" data-diff="">Any</button>' + DIFFS.map(function (d) {
      return '<button type="button" class="cmx-pill ' + d + (LIST.difficulty === d ? " on" : "") + '" data-diff="' + d + '"><span class="dot"></span>' + d + '</button>' }).join("") + '</div></div>' +
    '<div><div class="cmx-fh">Style</div><div class="cmx-pills">' + TAGS.map(function (t) {
      return '<button type="button" class="cmx-pill' + (LIST.tag === t ? " on" : "") + '" data-tag="' + t + '">' + ic(TAG_IC[t]) + t + '</button>' }).join("") + '</div></div>' +
    '<div><div class="cmx-fh">Missions</div><div class="cmx-sorts">' + [["", "All of them", "layers"], ["none", "Originals", "star"], ["only", "Remixes", "branch"]].map(function (r) {
      return '<button type="button" data-rmx="' + r[0] + '" class="' + (LIST.remixes === r[0] ? "on" : "") + '">' + ic(r[2]) + r[1] + '</button>' }).join("") + '</div></div>';
}
function bindFilters() {
  var f = $("cm-body").querySelector(".cmx-filters");
  f.querySelectorAll("[data-sort]").forEach(function (b) { b.addEventListener("click", function () { LIST.sort = b.getAttribute("data-sort"); reload(true) }) });
  f.querySelectorAll("[data-diff]").forEach(function (b) { b.addEventListener("click", function () { LIST.difficulty = b.getAttribute("data-diff"); reload(true) }) });
  f.querySelectorAll("[data-tag]").forEach(function (b) { b.addEventListener("click", function () { var t = b.getAttribute("data-tag"); LIST.tag = LIST.tag === t ? "" : t; reload(true) }) });
  f.querySelectorAll("[data-rmx]").forEach(function (b) { b.addEventListener("click", function () { LIST.remixes = b.getAttribute("data-rmx"); reload(true) }) });
}
function paintRhead() {
  var h = $("cm-rhead");
  if (!h) return;
  var s = LIST.sort === "relevance" ? ["relevance", "", "target", "Best matches"] : SORTS.filter(function (x) { return x[0] === LIST.sort })[0] || SORTS[0];
  var chips = [];
  if (LIST.difficulty) chips.push(['diff', LIST.difficulty]);
  if (LIST.tag) chips.push(['tag', LIST.tag]);
  if (LIST.remixes) chips.push(['rmx', LIST.remixes === "only" ? "remixes" : "originals"]);
  h.innerHTML = '<h2>' + ic(s[2]) + esc(s[3]) + '</h2><span class="count">' + (LIST.loaded ? LIST.items.length + (LIST.next ? "+" : "") + " missions" : "") + '</span>' +
    (chips.length ? '<div class="cmx-chips">' + chips.map(function (c) {
      return '<button type="button" class="cmx-chip" data-clear="' + c[0] + '">' + esc(c[1]) + ic("x") + '</button>' }).join("") + '</div>' : '');
  h.querySelectorAll("[data-clear]").forEach(function (b) {
    b.addEventListener("click", function () {
      var c = b.getAttribute("data-clear");
      if (c === "diff") LIST.difficulty = ""; else if (c === "tag") LIST.tag = ""; else LIST.remixes = "";
      reload(true);
    });
  });
}
function spotlight() {
  var host = $("cm-spot");
  if (!host) return;
  call("list_missions", { sort: "week", limit: 1 }).then(function (r) {
    var m = (r.items || [])[0];
    if (m && m.score > 0) return m;
    return call("list_missions", { sort: "top", limit: 1 }).then(function (r2) { return (r2.items || [])[0] || null });
  }).then(function (m) {
    if (!m || !$("cm-spot")) return;
    $("cm-spot").innerHTML = '<button type="button" class="cmx-spot-card" data-mission="' + esc(m.id) + '" aria-label="' + esc(m.name) + '">' +
      '<div class="img hud" style="background-image:url(' + esc(media(m.cover)) + ')">' +
        '<span class="cmx-spot-tag"><span class="cmx-badge gold">' + ic("fire") + 'Featured</span></span>' +
        '<div class="cmx-spot-t"><b>' + esc(m.name) + '</b><span>' + avatar(m.author, "sm") + '@' + esc(m.author ? m.author.handle : "?") +
          ' <span class="cmx-score up">' + ic("up") + m.score + '</span> ' + ic("pull") + fmt(m.pulls) + '</span></div></div></button>';
  }).catch(function () {});
}
// from the first page again; the filters redrawn, the toolbar's search kept
function reload(redraw) {
  LIST.items = []; LIST.next = null; LIST.err = null; LIST.loaded = false;
  if (redraw || !$("cm-grid")) showDiscover($("cm-body"));
  else { paintRhead(); paintCards(); more() }
}
function more() {
  if (LIST.busy) return;
  LIST.busy = true;
  var p = { q: LIST.q, sort: LIST.sort, difficulty: LIST.difficulty, tag: LIST.tag, remixes: LIST.remixes,
            cursor: LIST.items.length ? LIST.next : null };
  var ask = JSON.stringify(p);
  LIST.asking = ask;
  paintMore();
  call("list_missions", p).then(function (r) {
    if (LIST.asking !== ask) return;           // the filters changed meanwhile
    LIST.busy = false; LIST.loaded = true;
    LIST.items = LIST.items.concat(r.items || []);
    LIST.next = r.next;
    paintRhead(); paintCards();
  }).catch(function (e) {
    if (LIST.asking !== ask) return;
    LIST.busy = false; LIST.err = e;
    paintCards();
  });
}
function skeletons(n) {
  var s = "";
  for (var i = 0; i < n; i++) s += '<div class="cmx-card skel" aria-hidden="true"><div class="cmx-card-img"></div><div class="cmx-card-b">' +
    '<div class="line" style="width:70%"></div><div class="line" style="width:95%"></div><div class="line" style="width:45%"></div></div></div>';
  return s;
}
function paintCards() {
  var g = $("cm-grid");
  if (!g) return;
  g.innerHTML = LIST.items.map(cardHtml).join("") + (LIST.busy && !LIST.items.length ? skeletons(6) : "");
  if (LIST.loaded && !LIST.items.length && !LIST.err && !LIST.busy) {
    var filtered = LIST.q || LIST.tag || LIST.difficulty || LIST.remixes;
    $("cm-more").innerHTML = '<div class="cmx-empty" style="width:100%">' + radar() + '<b>' + (filtered ? "Nothing on the radar" : "No missions here yet") + '</b>' +
      '<p>' + (filtered ? "Nothing matches that. Try other words, or fewer filters." : "Be the first: open a mission of yours and share it with everyone.") + '</p>' +
      (filtered ? '' : '<button class="cmx-btn primary" id="cm-first">' + ic("upload") + 'Share a mission</button>') + '</div>';
    if ($("cm-first")) $("cm-first").addEventListener("click", function () { share() });
    return;
  }
  paintMore();
}
function paintMore() {
  var m = $("cm-more");
  if (!m) return;
  if (LIST.err) {
    m.innerHTML = '<div class="cmx-empty" style="width:100%">' + ic("warn") + '<b>' + esc(LIST.err.message) + '</b><button class="cmx-btn" id="cm-retry">Try again</button></div>';
    $("cm-retry").addEventListener("click", function () { LIST.err = null; more() });
    return;
  }
  if (LIST.busy) { m.innerHTML = LIST.items.length ? '<div class="cmx-spin"></div>' : ''; return }
  if (LIST.next) {
    m.innerHTML = '<button class="cmx-btn" id="cm-next">' + ic("chevron") + 'More missions</button>';
    $("cm-next").addEventListener("click", more);
    if (window.IntersectionObserver) {
      var io = new IntersectionObserver(function (es) { if (es[0].isIntersecting) { io.disconnect(); more() } }, { root: $("cm-main"), rootMargin: "300px" });
      io.observe($("cm-next"));
    }
    return;
  }
  m.innerHTML = "";
}
function cardHtml(c, preview) {
  var f = c.facts || {}, sc = c.score || 0;
  return '<article class="cmx-card"' + (preview ? '' : ' data-mission="' + esc(c.id) + '" tabindex="0"') + ' aria-label="' + esc(c.name) + '">' +
    '<div class="cmx-card-img" style="background-image:url(' + esc(c.thumbUrl || media(c.thumb)) + ')">' +
      '<div class="tl">' + diffPill(c.difficulty) + (c.remix_of ? '<span class="cmx-badge">' + ic("branch") + 'remix</span>' : '') +
        (c.status === "unlisted" ? '<span class="cmx-badge gold">unlisted</span>' : c.status === "hidden" ? '<span class="cmx-badge bad">hidden</span>' : '') + '</div>' +
      '<div class="tr"><span class="cmx-score ' + (sc > 0 ? "up" : sc < 0 ? "down" : "") + '">' + ic(sc < 0 ? "down" : "up") + sc + '</span></div>' +
      '<div class="bl">' + ic("map") + esc(H.levelName(c.level)) + (c.kind === "empty" ? " · empty map" : "") + '</div>' +
      (preview ? '' : '<div class="view"><span>' + ic("eye") + 'Open</span></div>') +
    '</div>' +
    '<div class="cmx-card-b"><h3>' + esc(c.name) + '</h3><p>' + esc(c.summary) + '</p>' +
      '<div class="cmx-card-by">' + avatar(c.author, "sm") + '<b>@' + esc(c.author ? c.author.handle : "someone who left") + '</b>' +
        (c.created_at ? '<span>· ' + esc(when(c.created_at)) + '</span>' : '') + '</div>' +
      '<div class="cmx-card-stats"><span title="Objectives">' + ic("flag") + c.objectives + '</span>' +
        (f.guards ? '<span title="Guards">' + ic("person") + f.guards + '</span>' : '') +
        '<span title="Comments">' + ic("comment") + c.comments + '</span><span title="Pulls">' + ic("pull") + fmt(c.pulls) + '</span></div>' +
    '</div></article>';
}

// ------------------------------------------------------------------ a mission
function showMission(body, id) {
  body.innerHTML = '<div class="cmx-loading"><div class="cmx-spin"></div></div>';
  call("get_mission", { id: id }).then(function (m) {
    if (!VIEW || VIEW.id !== id) return;
    VIEW.m = m;
    paintMission(body, m);
  }).catch(function (e) {
    body.innerHTML = '<div class="cmx-empty" style="margin-top:22px">' + radar() + '<b>' + esc(e.message) + '</b></div>';
  });
}
function intel(m) {
  var f = m.facts || {}, t = [];
  t.push(["map", H.levelName(m.level), m.kind === "empty" ? "its empty map" : "base level"]);
  t.push(["gauge", m.difficulty, "difficulty"]);
  if (m.play_minutes) t.push(["timer", "~" + m.play_minutes + " min", "to play"]);
  if (f.time_limit) t.push(["clock", clock(f.time_limit), "time limit"]);
  if (f.weather) t.push([f.weather === "snow" ? "snow" : "cloud", f.weather, "weather"]);
  if (f.music) t.push(["music", f.music, "music"]);
  [["guards", "person", "guard"], ["cameras", "cctv", "camera"], ["alarms", "bell", "alarm"], ["pickups", "box", "pickup"],
   ["cutscenes", "film", "cutscene"], ["vehicles", "run", "moving vehicle"], ["events", "bolt", "event"], ["placements", "layers", "placed"]].forEach(function (k) {
    if (f[k[0]]) t.push([k[1], fmt(f[k[0]]), k[0] === "placements" ? "things placed" : (f[k[0]] === 1 ? k[2] : k[2] + "s")]);
  });
  if (f.fail_on_alarm) t.push(["warn", "Alarm", "fails it"]);
  return '<div class="cmx-intel">' + t.map(function (x) {
    return '<div><span class="ii">' + ic(x[0]) + '</span><div><b>' + esc(x[1]) + '</b><span>' + esc(x[2]) + '</span></div></div>' }).join("") + '</div>';
}
function paintMission(body, m) {
  var shots = [m.cover].concat(m.shots || []), up = updatesFor(m.id);
  var pullLabel = m.my_pull ? (m.my_pull < m.version ? "Pull version " + m.version : "Pull it again") : "Pull to my studio";
  var line = m.lineage || [];
  body.innerHTML =
    '<section class="cmx-mhero"><div class="cmx-mhero-bg" style="background-image:url(' + esc(media(m.cover)) + ')"></div>' +
      '<div class="cmx-mhero-in">' +
        '<div class="cmx-gallery"><div class="main hud" id="cm-cover" style="background-image:url(' + esc(media(m.cover)) + ')"></div>' +
          (shots.length > 1 ? '<div class="cmx-thumbs">' + shots.map(function (s, i) {
            return '<button type="button" class="' + (i ? "" : "on") + '" data-shot="' + esc(s) + '" style="background-image:url(' + esc(media(s)) + ')" aria-label="Picture ' + (i + 1) + '"></button>' }).join("") + '</div>' : '') +
        '</div>' +
        '<div class="cmx-mhead">' +
          '<div class="cmx-over">' + ic("map") + esc(H.levelName(m.level)) + '<span class="sep">/</span>' + diffPill(m.difficulty) +
            '<span class="sep">/</span>v' + m.version + (m.remix_of ? '<span class="cmx-badge">' + ic("branch") + 'remix</span>' : '') +
            (m.status !== "published" ? '<span class="cmx-badge ' + (m.status === "hidden" ? "bad" : "gold") + '">' + esc(m.status) + '</span>' : '') + '</div>' +
          '<h1>' + esc(m.name) + '</h1><p class="sum">' + esc(m.summary) + '</p>' +
          '<div class="cmx-byline">' + who(m.author, "md") + '<span>shared ' + esc(when(m.created_at)) + (m.version > 1 ? ' · updated ' + esc(when(m.updated_at)) : '') + '</span>' +
            ((m.coauthors || []).length ? '<span>with ' + m.coauthors.map(function (p) { return '<button type="button" class="cmx-link" data-profile="' + esc(p.handle) + '">@' + esc(p.handle) + '</button>' }).join(", ") + '</span>' : '') + '</div>' +
          '<div class="cmx-tiles">' + [["up", m.up - m.down, "score"], ["pull", fmt(m.pulls), "pulls"], ["comment", m.comments, "comments"], ["branch", m.remixes, "remixes"]].map(function (t) {
            return '<div class="cmx-tile"><b>' + ic(t[0]) + t[1] + '</b><span>' + t[2] + '</span></div>' }).join("") + '</div>' +
          '<div class="cmx-acts"><button class="cmx-btn primary big" id="cm-pull">' + ic("pull") + esc(pullLabel) + '</button>' +
            '<button class="cmx-btn" id="cm-map">' + ic("map") + 'The map</button><button class="cmx-btn" id="cm-3d">' + ic("cube") + 'In 3D</button>' +
            '<div class="cmx-vote" id="cm-vote"></div></div>' +
          '<p class="cmx-note">' + ic("info") + '<span>' + (m.my_pull ? 'You pulled version ' + m.my_pull + (up ? '; version ' + m.version + ' is out' : '') + '. ' : '') +
            'Looking changes nothing; to change it, pull it into your studio.' + (m.allow_remix ? '' : ' Its author does not allow changed copies to be shared.') + '</span></p>' +
        '</div></div></section>' +
    '<div class="cmx-mbody"><div>' +
      (m.description ? '<section class="cmx-panel"><h2>' + ic("file") + 'Briefing</h2><div class="cmx-desc">' + esc(m.description) + '</div></section>' : '') +
      '<section class="cmx-panel"><h2>' + ic("flag") + 'Objectives <span class="n">' + (m.objectives || []).length + '</span></h2><ol class="cmx-objs">' +
        (m.objectives || []).map(function (o) {
          return '<li><span class="oi">' + ic(objIcon(o.kind)) + '</span><span class="ot"><small>' + esc(o.kind === "level" ? "from the level" : o.kind) + '</small>' + esc(o.text) + '</span></li>' }).join("") + '</ol></section>' +
      '<section class="cmx-panel"><h2>' + ic("radar") + 'Intel</h2>' + intel(m) +
        (m.video_url ? '<p class="cmx-note" style="margin-top:14px">' + ic("film") + '<span>Video: <span style="user-select:text">' + esc(m.video_url) + '</span></span></p>' : '') + '</section>' +
      '<section class="cmx-panel"><h2>' + ic("comment") + 'Comments <span class="n" id="cm-ccount">' + m.comments + '</span></h2><div id="cm-comments"></div></section>' +
    '</div><aside class="cmx-side">' +
      (m.mine ? '<section class="cmx-panel"><h2>' + ic("person") + 'Yours</h2><div class="cmx-own">' +
        '<button class="cmx-btn" id="cm-edit">' + ic("edit") + 'Edit the details</button>' +
        (m.status === "hidden" ? '<p class="cmx-note">' + ic("warn") + '<span>A moderator hid it.</span></p>' :
          '<button class="cmx-btn" id="cm-list">' + ic(m.status === "unlisted" ? "eye" : "eyeOff") + (m.status === "unlisted" ? "List it again" : "Unlist it") + '</button>') +
        '<button class="cmx-btn danger" id="cm-del">' + ic("trash") + 'Delete it</button>' +
        '<p class="cmx-note">' + ic("info") + '<span>A new version comes from the studio: open the mission, then Share, Publish an update.</span></p></div></section>' : '') +
      (m.can_moderate ? '<section class="cmx-panel"><h2>' + ic("shieldCheck") + 'Moderator</h2><div class="cmx-own">' +
        '<button class="cmx-btn" id="cm-hide">' + ic(m.status === "hidden" ? "eye" : "eyeOff") + (m.status === "hidden" ? "Show it again" : "Hide it") + '</button>' +
        (m.mine ? '' : '<button class="cmx-btn danger" id="cm-mdel">' + ic("trash") + 'Delete it</button>') + '</div></section>' : '') +
      (line.length ? '<section class="cmx-panel"><h2>' + ic("branch") + 'Where it came from</h2><ol class="cmx-timeline">' + line.map(function (x) {
          var a = x.author || {};
          return '<li>' + (x.id ? '<button type="button" class="cmx-link" data-mission="' + esc(x.id) + '">' + esc(x.name) + '</button>' : '<b>' + esc(x.name) + '</b>') +
            '<small>v' + esc(x.version || 1) + ' by @' + esc(a.handle || "?") + '</small></li>' }).join("") +
        '<li class="here"><b>' + esc(m.name) + '</b><small>by @' + esc(m.author ? m.author.handle : "?") + '</small></li></ol></section>' : '') +
      (m.remixes ? '<section class="cmx-panel"><h2>' + ic("branch") + 'Remixes <span class="n">' + m.remixes + '</span></h2><div id="cm-tree">' +
        '<button class="cmx-btn block" id="cm-tree-go">' + ic("branch") + 'Show the tree</button></div></section>' : '') +
      '<section class="cmx-panel"><h2>' + ic("history") + 'Versions</h2><ol class="cmx-timeline">' + (m.versions || []).map(function (v, i) {
        return '<li class="' + (i ? "" : "here") + '"><b>Version ' + v.version + '</b><small>' + esc(when(v.created_at)) + '</small>' +
          (v.notes ? '<div class="notes">' + esc(v.notes) + '</div>' : '') + '</li>' }).join("") + '</ol></section>' +
      (!m.mine ? '<button class="cmx-btn ghost" id="cm-report">' + ic("report") + 'Report this mission</button>' : '') +
    '</aside></div>';
  body.querySelectorAll("[data-shot]").forEach(function (b) {
    b.addEventListener("click", function () {
      $("cm-cover").style.backgroundImage = "url(" + media(b.getAttribute("data-shot")) + ")";
      body.querySelectorAll("[data-shot]").forEach(function (x) { x.classList.toggle("on", x === b) });
    });
  });
  paintVote(m);
  $("cm-pull").addEventListener("click", function () { pull(m) });
  $("cm-map").addEventListener("click", function () { preview(m, false) });
  $("cm-3d").addEventListener("click", function () { preview(m, true) });
  if ($("cm-tree-go")) $("cm-tree-go").addEventListener("click", function () { tree(m) });
  if ($("cm-edit")) $("cm-edit").addEventListener("click", function () { editDetails(m) });
  if ($("cm-list")) $("cm-list").addEventListener("click", function () {
    call("set_status", { id: m.id, status: m.status === "unlisted" ? "published" : "unlisted" }).then(function () {
      toast(m.status === "unlisted" ? "Listed again" : "Unlisted: only its link finds it now"); showMission(body, m.id);
    }).catch(function (e) { toast(e.message) });
  });
  if ($("cm-del")) $("cm-del").addEventListener("click", function () { deleteMission(m) });
  if ($("cm-mdel")) $("cm-mdel").addEventListener("click", function () { deleteMission(m) });
  if ($("cm-hide")) $("cm-hide").addEventListener("click", function () {
    call("set_status", { id: m.id, status: m.status === "hidden" ? "published" : "hidden" }).then(function () { showMission(body, m.id) })
      .catch(function (e) { toast(e.message) });
  });
  if ($("cm-report")) $("cm-report").addEventListener("click", function () { report("mission", m.id, "“" + m.name + "”") });
  comments(m);
}
function updatesFor(cid) {
  for (var k in UPDATES) if (UPDATES[k].id === cid) return UPDATES[k];
  return null;
}
function paintVote(m) {
  var v = $("cm-vote");
  if (!v) return;
  v.innerHTML = '<button type="button" class="up' + (m.my_vote === 1 ? ' on' : '') + '" id="cm-up" aria-label="Vote up" title="' + (m.mine ? "Your own mission" : "A good one") + '">' + ic("up") + '</button>' +
    '<b title="' + m.up + ' up, ' + m.down + ' down">' + (m.up - m.down) + '</b>' +
    '<button type="button" class="down' + (m.my_vote === -1 ? ' on' : '') + '" id="cm-down" aria-label="Vote down" title="' + (m.mine ? "Your own mission" : "Not for me") + '">' + ic("down") + '</button>';
  function vote(val) {
    if (m.mine) { toast("You cannot vote for your own mission"); return }
    needAccount("vote", function () {
      var to = m.my_vote === val ? 0 : val;
      call("set_vote", { id: m.id, value: to }).then(function (r) {
        m.up = r.up; m.down = r.down; m.my_vote = r.my_vote;
        if (VIEW && VIEW.kind === "mission" && VIEW.id === m.id && $("cm-vote")) paintVote(m); else show();
        LIST.items.forEach(function (c) { if (c.id === m.id) { c.up = r.up; c.down = r.down; c.score = r.score } });
      }).catch(function (e) { toast(e.message) });
    });
  }
  $("cm-up").addEventListener("click", function () { vote(1) });
  $("cm-down").addEventListener("click", function () { vote(-1) });
}
function tree(m) {
  var box = $("cm-tree");
  box.innerHTML = '<div class="cmx-spin"></div>';
  call("remixes", { id: m.id }).then(function (r) {
    var kids = {};
    (r.items || []).forEach(function (x) { (kids[x.parent] = kids[x.parent] || []).push(x) });
    function list(pid) {
      var k = kids[pid] || [];
      return k.length ? '<ul class="cmx-tree">' + k.map(function (x) {
        return '<li><button type="button" class="cmx-link" data-mission="' + esc(x.id) + '">' + esc(x.name) + '</button> ' +
          '<small>@' + esc(x.author ? x.author.handle : "?") + ' · ▲ ' + x.score + '</small>' + list(x.id) + '</li>' }).join("") + '</ul>' : '';
    }
    box.innerHTML = list(m.id) || '<p class="cmx-note">' + ic("info") + '<span>None of them can be seen now.</span></p>';
  }).catch(function (e) { box.innerHTML = '<p class="cmx-note">' + ic("warn") + '<span>' + esc(e.message) + '</span></p>' });
}
function pull(m) {
  needAccount("pull a mission into your studio", function () {
    var b = $("cm-pull");
    if (b) { b.disabled = true; b.innerHTML = '<span class="cmx-spin" style="width:16px;height:16px;border-width:2px"></span>Pulling…' }
    api("POST", "pull", { id: m.id, version: m.version }).then(function (r) {
      toast("“" + (m.name || r.mission.name) + "” is a mission of yours now");
      hide();
      H.openMission(r.mission.id);
      refreshUpdates();
    }).catch(function (e) {
      toast(e.message);
      if (b) { b.disabled = false; b.innerHTML = ic("pull") + "Pull to my studio" }
    });
  });
}
function preview(m, in3d) {
  var b = in3d ? $("cm-3d") : $("cm-map");
  if (b) b.disabled = true;
  api("GET", "plan/" + m.id + "?v=" + m.version).then(function (r) {
    hide();
    H.preview(r.mission, { id: m.id, version: m.version, name: m.name, author: m.author, allow_remix: m.allow_remix }, in3d);
  }).catch(function (e) {
    toast(e.message);
    if (b) b.disabled = false;
  });
}
function dialog(title, html, wide) { H.sheet(title, '<div class="cmx-dlg">' + html + '</div>', wide) }
function deleteMission(m) {
  dialog("Delete “" + m.name + "”?",
    '<div class="cmx-alert">' + ic("warn") + '<span>It goes from the community for good: its versions, votes and comments with it. Missions others made from it keep their line, without a link back.</span></div>' +
    '<p class="cmx-note" style="margin-top:12px">' + ic("info") + '<span>The mission in your studio stays as it is. Its name is free again at once.</span></p>' +
    '<div class="foot"><button class="cmx-btn" id="cmd-no">Keep it</button><button class="cmx-btn danger" id="cmd-yes">' + ic("trash") + 'Delete it</button></div>');
  $("cmd-no").addEventListener("click", H.closeSheet);
  $("cmd-yes").addEventListener("click", function () {
    this.disabled = true;
    call("delete_mission", { id: m.id }).then(function () {
      H.closeSheet(); toast("“" + m.name + "” is gone from the community");
      LIST.items = LIST.items.filter(function (c) { return c.id !== m.id });
      STATS = null;
      back();
    }).catch(function (e) { toast(e.message); $("cmd-yes").disabled = false });
  });
}
function field(id, label, value, o) {
  o = o || {};
  return '<div class="cmx-field"><label for="' + id + '">' + esc(label) + (o.side || '') + '</label>' +
    (o.area ? '<textarea id="' + id + '" rows="' + (o.rows || 4) + '" maxlength="' + (o.max || 2000) + '"' + (o.ph ? ' placeholder="' + esc(o.ph) + '"' : '') + '>' + esc(value) + '</textarea>'
      : '<div class="cmx-in" id="' + id + '-box">' + (o.icon ? ic(o.icon) : '') + (o.pre ? '<span class="pre">' + o.pre + '</span>' : '') +
        '<input id="' + id + '" type="' + (o.type || "text") + '" value="' + esc(value) + '"' + (o.max ? ' maxlength="' + o.max + '"' : '') +
        (o.ph ? ' placeholder="' + esc(o.ph) + '"' : '') + (o.auto ? ' autocomplete="' + o.auto + '"' : '') + (o.spell === false ? ' spellcheck="false"' : '') + '>' +
        (o.eye ? '<button type="button" class="eye" data-eye="' + id + '" aria-label="Show the password">' + ic("eye") + '</button>' : '') +
        (o.st ? '<span class="st" id="' + id + '-st"></span>' : '') + '</div>') +
    (o.msg !== false ? '<div class="cmx-msg" id="' + id + '-msg">' + (o.hint ? esc(o.hint) : '') + '</div>' : '') + '</div>';
}
function bindEyes(root) {
  (root || document).querySelectorAll("[data-eye]").forEach(function (b) {
    b.addEventListener("click", function () {
      var i = $(b.getAttribute("data-eye")), show = i.type === "password";
      i.type = show ? "text" : "password";
      b.innerHTML = ic(show ? "eyeOff" : "eye");
      b.setAttribute("aria-label", show ? "Hide the password" : "Show the password");
    });
  });
}
function editDetails(m) {
  dialog("Edit “" + m.name + "”",
    field("ced-name", "Name", m.name, { max: 60, st: true }) +
    field("ced-sum", "Summary (one line, for its card)", m.summary, { max: 140 }) +
    field("ced-desc", "Briefing", m.description, { area: true, rows: 5, max: 6000 }) +
    '<div class="cmx-field"><div class="lab">Difficulty</div>' + seg("ced-diff", m.difficulty) + '</div>' +
    '<div class="cmx-field"><div class="lab">Style</div>' + tagsHtml("ced-tags", m.tags || []) + '</div>' +
    '<label class="cmx-switch"><input type="checkbox" id="ced-rmx"' + (m.allow_remix ? " checked" : "") + '><span><b>Remixes allowed</b><small>Others may share changed copies of it, crediting you.</small></span></label>' +
    '<div class="cmx-alert" id="ced-err" hidden></div>' +
    '<div class="foot"><button class="cmx-btn" id="ced-no">Cancel</button><button class="cmx-btn primary" id="ced-ok">' + ic("check") + 'Save</button></div>', true);
  bindSeg("ced-diff"); bindTags("ced-tags");
  nameCheck($("ced-name"), m.id);
  $("ced-no").addEventListener("click", H.closeSheet);
  $("ced-ok").addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    call("update_details", { id: m.id, name: $("ced-name").value, summary: $("ced-sum").value, description: $("ced-desc").value,
      difficulty: segValue("ced-diff"), tags: tagsValue("ced-tags"), allow_remix: $("ced-rmx").checked }).then(function () {
      H.closeSheet(); toast("Saved"); showMission($("cm-body"), m.id);
    }).catch(function (e) { $("ced-err").hidden = false; $("ced-err").innerHTML = ic("warn") + '<span>' + esc(e.message) + '</span>'; btn.disabled = false });
  });
}

// ------------------------------------------------------------------ comments
function comments(m, cursor) {
  var host = $("cm-comments");
  if (!host) return;
  if (!cursor) host.innerHTML = '<div id="cm-c-new"></div><div id="cm-c-list"><div class="cmx-spin"></div></div><div id="cm-c-more" class="cmx-more"></div>';
  paintCompose(m, null, $("cm-c-new"));
  call("list_comments", { id: m.id, cursor: cursor || null }).then(function (r) {
    var list = $("cm-c-list");
    if (!list) return;
    var h = (r.items || []).map(function (c) { return commentHtml(c, m) }).join("");
    if (!cursor) list.innerHTML = h || '<p class="cmx-note">' + ic("comment") + '<span>No comments yet. Played it? Say how it went.</span></p>';
    else list.insertAdjacentHTML("beforeend", h);
    bindComments(m, list);
    var more = $("cm-c-more");
    more.innerHTML = r.next ? '<button class="cmx-btn" id="cm-c-next">' + ic("chevron") + 'More comments</button>' : '';
    if (r.next) $("cm-c-next").addEventListener("click", function () { comments(m, r.next) });
  }).catch(function (e) { var l = $("cm-c-list"); if (l) l.innerHTML = '<p class="cmx-note">' + ic("warn") + '<span>' + esc(e.message) + '</span></p>' });
}
function commentHtml(c, m, reply) {
  var mine = c.author && m.author && c.author.id === m.author.id;
  return '<div class="cmx-c' + (c.removed ? ' removed' : '') + '" data-c="' + esc(c.id) + '">' + (c.removed ? '<span class="cmx-av md">–</span>' : avatar(c.author, "md")) +
    '<div class="cb"><div class="cmx-c-h">' + (c.removed ? '<i>removed</i>' : who(c.author, "none")) +
      (mine && !c.removed ? '<span class="cmx-badge gold">author</span>' : '') +
      '<small>' + esc(when(c.created_at)) + (c.edited_at ? ' · edited' : '') + '</small></div>' +
    '<div class="cmx-c-body">' + (c.removed ? 'This comment was removed.' : esc(c.body)) + '</div>' +
    (c.removed ? '' : '<div class="cmx-c-acts">' +
      (!reply ? '<button type="button" data-ca="reply">' + ic("reply") + 'Reply</button>' : '') +
      (c.mine ? '<button type="button" data-ca="edit">' + ic("edit") + 'Edit</button>' : '') +
      (c.can_remove ? '<button type="button" class="danger" data-ca="del">' + ic("trash") + 'Remove</button>' : '') +
      (!c.mine ? '<button type="button" data-ca="report">' + ic("report") + 'Report</button>' : '') + '</div>') +
    (c.replies && c.replies.length ? '<div class="cmx-replies">' + c.replies.map(function (x) { return commentHtml(x, m, true) }).join("") + '</div>' : '') +
    (reply ? '' : '<div class="cmx-c-reply"></div>') +
    '</div></div>';
}
function bindComments(m, root) {
  root.querySelectorAll("[data-ca]").forEach(function (b) {
    if (b.dataset.bound) return;
    b.dataset.bound = "1";
    b.addEventListener("click", function () {
      var el = b.closest(".cmx-c"), id = el.getAttribute("data-c"), a = b.getAttribute("data-ca");
      if (a === "reply") return needAccount("reply", function () { if (VIEW.kind !== "mission") return; paintCompose(m, id, el.querySelector(".cmx-c-reply"), true) });
      if (a === "report") return report("comment", id, "this comment");
      if (a === "del") return call("delete_comment", { id: id }).then(function () { comments(m) }).catch(function (e) { toast(e.message) });
      if (a === "edit") {
        var bodyEl = el.querySelector(".cmx-c-body"), old = bodyEl.textContent;
        bodyEl.innerHTML = '<div class="cmx-c-edit"><textarea maxlength="2000">' + esc(old) + '</textarea><div class="cmx-compose"><div class="box"><div class="row">' +
          '<button class="cmx-btn" data-x="no">Cancel</button><button class="cmx-btn primary" data-x="ok">Save</button></div></div></div></div>';
        bodyEl.querySelector('[data-x="no"]').addEventListener("click", function () { bodyEl.textContent = old });
        bodyEl.querySelector('[data-x="ok"]').addEventListener("click", function () {
          call("edit_comment", { id: id, body: bodyEl.querySelector("textarea").value }).then(function () { comments(m) }).catch(function (e) { toast(e.message) });
        });
      }
    });
  });
}
function paintCompose(m, parent, host, focus) {
  if (!host) return;
  if (!member()) {
    if (parent) return;
    host.innerHTML = '<div class="cmx-signhint">' + ic("comment") + '<span><button type="button" class="cmx-link" id="cm-c-sign">Sign in</button> to comment, reply and vote.</span></div>';
    $("cm-c-sign").addEventListener("click", function () { needAccount("comment", function () { go({ kind: "mission", id: m.id }) }) });
    return;
  }
  host.innerHTML = '<div class="cmx-compose">' + avatar(ST.profile, "md") + '<div class="box"><textarea maxlength="2000" placeholder="' +
    (parent ? "Your reply" : "Played it? Say how it went, or what could be better") + '"></textarea>' +
    '<div class="row">' + (parent ? '<button class="cmx-btn" data-x="no">Cancel</button>' : '') +
    '<button class="cmx-btn primary" data-x="ok">' + ic("comment") + (parent ? "Reply" : "Comment") + '</button></div></div></div>';
  var ta = host.querySelector("textarea");
  if (focus) ta.focus();
  if (parent) host.querySelector('[data-x="no"]').addEventListener("click", function () { host.innerHTML = "" });
  host.querySelector('[data-x="ok"]').addEventListener("click", function () {
    var b = this;
    if (!ta.value.trim()) { ta.focus(); return }
    b.disabled = true;
    call("add_comment", { id: m.id, parent: parent, body: ta.value }).then(function () {
      m.comments++;
      var n = $("cm-ccount"); if (n) n.textContent = m.comments;
      comments(m);
    }).catch(function (e) { toast(e.message); b.disabled = false });
  });
}
function report(type, target, what) {
  needAccount("report it", function () {
    dialog("Report " + what,
      '<p class="cmx-note">' + ic("shieldCheck") + '<span>Moderators look at every report. What is wrong with it?</span></p>' +
      '<div class="cmx-pills" id="rp-why" style="margin:14px 0">' + [["spam", "Spam", "warn"], ["offensive", "Hurtful", "skull"], ["stolen", "Stolen work", "branch"],
        ["broken", "Broken", "burst"], ["other", "Something else", "info"]].map(function (r) {
        return '<button type="button" class="cmx-pill" data-v="' + r[0] + '">' + ic(r[2]) + r[1] + '</button>' }).join("") + '</div>' +
      field("rp-note", "More, if it helps", "", { area: true, rows: 3, max: 1000 }) +
      '<div class="foot"><button class="cmx-btn" id="rp-no">Cancel</button><button class="cmx-btn primary" id="rp-ok">' + ic("report") + 'Report</button></div>');
    var why = "";
    $("rp-why").querySelectorAll("[data-v]").forEach(function (b) {
      b.addEventListener("click", function () {
        why = b.getAttribute("data-v");
        $("rp-why").querySelectorAll("[data-v]").forEach(function (x) { x.classList.toggle("on", x === b) });
      });
    });
    $("rp-no").addEventListener("click", H.closeSheet);
    $("rp-ok").addEventListener("click", function () {
      if (!why) { toast("Say what is wrong with it"); return }
      call("report", { type: type, target: target, reason: why, note: $("rp-note").value }).then(function () {
        H.closeSheet(); toast("Reported: thank you");
      }).catch(function (e) { toast(e.message) });
    });
  });
}

// ------------------------------------------------------------------ people
function showProfile(body, handle) {
  body.innerHTML = '<div class="cmx-loading"><div class="cmx-spin"></div></div>';
  call("get_profile", { handle: handle }).then(function (r) {
    if (!VIEW || VIEW.handle !== handle) return;
    paintProfile(body, r);
  }).catch(function (e) { body.innerHTML = '<div class="cmx-empty" style="margin-top:22px">' + radar() + '<b>' + esc(e.message) + '</b></div>' });
}
function paintProfile(body, r) {
  var p = r.profile, s = r.stats || {}, items = (r.missions && r.missions.items) || [];
  body.innerHTML =
    '<section class="cmx-phero"><div class="cmx-topo"></div><div class="cmx-phero-in">' + avatar(p, "xl") +
      '<div class="cmx-pinfo"><h1>' + esc(p.name) + (p.role ? '<span class="cmx-badge gold">' + ic("shieldCheck") + esc(p.role) + '</span>' : '') +
        (p.banned ? '<span class="cmx-badge bad">banned</span>' : '') + '</h1>' +
        '<div class="handle">@' + esc(p.handle) + '<span>·</span>' + ic("clock") + 'joined ' + esc(when(p.created_at)) + '</div>' +
        (p.bio ? '<p class="bio">' + esc(p.bio) + '</p>' : (r.mine ? '<p class="bio" style="color:var(--faint)">A few words about you would go here.</p>' : '')) +
        ((p.links || []).length ? '<div class="cmx-links">' + p.links.map(function (l) { return '<span>' + ic("link") + esc(l.replace(/^https:\/\//, "")) + '</span>' }).join("") + '</div>' : '') +
      '</div>' +
      '<div class="cmx-pside"><div class="cmx-tiles">' + [["layers", s.missions || 0, "missions"], ["up", s.score || 0, "score"], ["pull", fmt(s.pulls || 0), "pulls"]].map(function (t) {
        return '<div class="cmx-tile"><b>' + ic(t[0]) + t[1] + '</b><span>' + t[2] + '</span></div>' }).join("") + '</div>' +
        (r.mine ? '<div class="cmx-pacts"><button class="cmx-btn" id="cm-p-edit">' + ic("edit") + 'Edit profile</button><button class="cmx-btn ghost" id="cm-p-out">' + ic("logout") + 'Sign out</button></div>'
          : (member() ? '<div class="cmx-pacts"><button class="cmx-btn ghost" id="cm-p-rep">' + ic("report") + 'Report</button></div>' : '')) +
      '</div></div></section>' +
    '<div class="cmx-rhead"><h2>' + ic("layers") + (r.mine ? "Your missions" : "Missions") + '</h2><span class="count">' + items.length + (r.missions && r.missions.next ? "+" : "") + '</span>' +
      (r.mine ? '<span class="count">Unlisted ones show only to you.</span><div class="cmx-chips"><button class="cmx-btn primary" id="cm-p-share">' + ic("upload") + 'Share a mission</button></div>' : '') + '</div>' +
    (items.length ? '<div class="cmx-grid">' + items.map(function (c) { return cardHtml(c) }).join("") + '</div>' :
      '<div class="cmx-empty">' + radar() + '<b>' + (r.mine ? "Nothing shared yet" : "Nothing shared yet") + '</b><p>' +
        (r.mine ? "Open a mission of yours and share it: the studio walks you through it." : "When @" + esc(p.handle) + " shares a mission, it shows here.") + '</p></div>') +
    (r.mine ? '<div class="cmx-danger"><div><b>Delete your account</b><p>Your profile, the missions you shared, your votes and comments - gone for good. The missions in your studio stay.</p></div>' +
      '<button class="cmx-btn danger" id="cm-p-del">' + ic("trash") + 'Delete my account…</button></div>' : '');
  if ($("cm-p-edit")) $("cm-p-edit").addEventListener("click", function () { go({ kind: "profile-edit" }) });
  if ($("cm-p-out")) $("cm-p-out").addEventListener("click", signOut);
  if ($("cm-p-del")) $("cm-p-del").addEventListener("click", deleteAccount);
  if ($("cm-p-rep")) $("cm-p-rep").addEventListener("click", function () { report("profile", p.id, "@" + p.handle) });
  if ($("cm-p-share")) $("cm-p-share").addEventListener("click", function () { share() });
}
function deleteAccount() {
  dialog("Delete your community account?",
    '<div class="cmx-alert">' + ic("warn") + '<span>Your profile, every mission you shared (with its votes and comments), your votes, your comments and your pulls go for good, and the account with them.</span></div>' +
    '<p class="cmx-note" style="margin:12px 0">' + ic("info") + '<span>The missions in your studio stay. Missions others made from yours keep their line, without a link back.</span></p>' +
    field("da-c", "Type DELETE to confirm", "", { auto: "off" }) +
    '<div class="foot"><button class="cmx-btn" id="da-no">Keep it</button><button class="cmx-btn danger" id="da-yes" disabled>' + ic("trash") + 'Delete my account</button></div>');
  $("da-c").addEventListener("input", function () { $("da-yes").disabled = this.value.trim() !== "DELETE" });
  $("da-no").addEventListener("click", H.closeSheet);
  $("da-yes").addEventListener("click", function () {
    this.disabled = true;
    api("POST", "account/delete", {}).then(function () {
      H.closeSheet(); toast("Your account is deleted"); return refreshState();
    }).then(function () { VIEW = { kind: "discover" }; BACK = []; LIST.items = []; LIST.loaded = false; STATS = null; show() })
      .catch(function (e) { toast(e.message); $("da-yes").disabled = false });
  });
}
function showProfileEdit(body) {
  if (!member()) { VIEW = { kind: "discover" }; show(); return }
  body.innerHTML = '<div style="max-width:620px;margin:28px auto 0"><div class="cmx-over">' + ic("edit") + 'Your profile</div>' +
    '<h1 style="font:600 34px Barlow Condensed,sans-serif;margin:6px 0 18px">How the community sees you</h1>' +
    '<div class="cmx-step" id="cm-pf"></div></div>';
  profileForm($("cm-pf"), ST.profile, false, function () { back() });
}
// Your name, picture and words: the first time, or changed later
function profileForm(host, p, first, done) {
  var sug = ST.suggest || {};
  var cur = p || { handle: "", name: sug.name || (VIEW && VIEW.pending && VIEW.pending.name) || "", bio: "", links: [], avatar_url: sug.image || null };
  var AV = { id: cur.avatar || null, url: cur.avatar_url || null, data: null };
  function src() { return AV.data || (AV.id ? media(AV.id) : AV.url ? "api/community/avatar?u=" + encodeURIComponent(AV.url) : "") }
  function avHtml() { var s = src(); return s ? '<img class="cmx-av" src="' + esc(s) + '" alt="">' : avatar({ handle: $("pf-handle") ? $("pf-handle").value : cur.handle, name: cur.name }) }
  host.innerHTML =
    '<div class="cmx-pickav"><span id="pf-av">' + avHtml() + '</span><div class="btns">' +
      '<button class="cmx-btn" id="pf-pic">' + ic("image") + 'Choose a picture</button>' +
      '<button class="cmx-btn ghost" id="pf-nopic"' + (AV.id || AV.url ? '' : ' hidden') + '>' + ic("x") + 'No picture</button>' +
      '<input type="file" id="pf-file" accept="image/*" hidden></div></div>' +
    field("pf-handle", "Username", cur.handle, { pre: "@", max: 24, st: true, spell: false, auto: "username", hint: "3 to 24 letters, digits, _ . or -" }) +
    field("pf-name", "Name others see", cur.name, { icon: "person", max: 40, auto: "name" }) +
    field("pf-bio", "A few words about you (optional)", cur.bio, { area: true, rows: 3, max: 500, ph: "The missions you like to make, the ones you like to play" }) +
    field("pf-links", "Links (optional, https://, one a line, up to 4)", (cur.links || []).join("\n"), { area: true, rows: 2, max: 900 }) +
    '<div class="cmx-alert" id="pf-err" hidden></div>' +
    '<footer style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px">' + (first ? '' : '<button class="cmx-btn" id="pf-no">Cancel</button>') +
      '<button class="cmx-btn primary big" id="pf-ok">' + ic("check") + (first ? "Join the community" : "Save") + '</button></footer>';
  var ok = handleCheck($("pf-handle"), function () { if (!AV.data && !AV.id && !AV.url) $("pf-av").innerHTML = avHtml() });
  $("pf-pic").addEventListener("click", function () { $("pf-file").click() });
  $("pf-nopic").addEventListener("click", function () { AV = { id: null, url: null, data: null }; $("pf-av").innerHTML = avHtml(); this.hidden = true });
  $("pf-file").addEventListener("change", function () {
    var f = this.files && this.files[0];
    if (!f) return;
    loadImage(URL.createObjectURL(f)).then(function (img) {
      AV.data = encode(img, 256, 256, 110000); AV.id = null; AV.url = null;
      $("pf-av").innerHTML = avHtml(); $("pf-nopic").hidden = false;
    }).catch(function () { toast("That picture could not be read") });
  });
  if ($("pf-no")) $("pf-no").addEventListener("click", done);
  $("pf-ok").addEventListener("click", function () {
    var b = this;
    if (!ok()) { $("pf-handle").focus(); return }
    if (!$("pf-name").value.trim()) { $("pf-name").focus(); return }
    b.disabled = true;
    (AV.data ? api("POST", "avatar", { data: AV.data }).then(function (r) { return r.id }) : Promise.resolve(AV.id)).then(function (aid) {
      return call("save_profile", { handle: $("pf-handle").value.trim().replace(/^@/, ""), name: $("pf-name").value.trim(), bio: $("pf-bio").value,
        links: $("pf-links").value.split(/\n+/).map(function (s) { return s.trim() }).filter(Boolean),
        avatar: aid || null, avatar_url: aid ? null : AV.url });
    }).then(refreshState).then(function (s) {
      toast(first ? "Welcome to the community, @" + s.profile.handle : "Saved");
      done();
    }).catch(function (e) { b.disabled = false; var el = $("pf-err"); el.hidden = false; el.innerHTML = ic("warn") + '<span>' + esc(e.message) + '</span>' });
  });
}
// a username as you type it: its shape, and whether it is free. Returns "is it fine now?"
function handleCheck(input, onChange) {
  var t = null, n = 0, good = !!input.value && false;
  var box = $(input.id + "-box"), st = $(input.id + "-st"), msg = $(input.id + "-msg");
  function set(state, text) {
    good = state === "good";
    box.classList.toggle("good", state === "good"); box.classList.toggle("bad", state === "bad");
    st.className = "st " + (state || ""); st.innerHTML = state === "good" ? ic("check") : state === "bad" ? ic("x") : state === "wait" ? '<span class="cmx-spin" style="width:14px;height:14px;border-width:2px"></span>' : "";
    msg.className = "cmx-msg " + (state === "good" ? "good" : state === "bad" ? "bad" : ""); msg.textContent = text;
  }
  function check() {
    var v = input.value.trim().replace(/^@/, ""), k = ++n;
    if (onChange) onChange(v);
    if (!v) { set("", "3 to 24 letters, digits, _ . or -"); return }
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{2,23}$/.test(v)) { set("bad", "3 to 24 letters, digits, _ . or -, starting with a letter or a digit"); return }
    set("wait", "Checking…");
    call("handle_free", { handle: v }).then(function (r) {
      if (k !== n) return;
      set(r.free ? "good" : "bad", r.free ? "@" + v + " is free" : r.message);
    }).catch(function () { if (k === n) set("", "") });
  }
  input.addEventListener("input", function () { clearTimeout(t); t = setTimeout(check, 280) });
  if (input.value) check();
  return function () { return good };
}

// ------------------------------------------------------------------ signing in: a page of two halves
function showAuth(body) {
  var V = VIEW;
  V.step = V.step || "signin";
  body.innerHTML = '<div class="cmx-auth"><section class="cmx-auth-brand"><div class="cmx-topo"></div>' + radar("cmx-auth-radar") +
      '<div class="cmx-over">' + ic("radar") + 'IGI Studio · Community</div>' +
      '<h1>Join the <em>field</em>.</h1>' +
      '<p>The community is where missions made with IGI Studio meet the people who play them - and where they get better, one remix at a time.</p>' +
      '<ul class="cmx-feats">' +
        '<li><span class="fi">' + ic("upload") + '</span><div><b>Share your missions</b><span>Publish with a cover, screenshots, objectives and credits, and keep them up to date with new versions.</span></div></li>' +
        '<li><span class="fi">' + ic("pull") + '</span><div><b>Play what others made</b><span>Look at any mission’s map and 3D view, then pull it into your studio in one click.</span></div></li>' +
        '<li><span class="fi">' + ic("branch") + '</span><div><b>Remix, with credit</b><span>Change a mission and share it back: it carries the line of everyone who made it.</span></div></li>' +
        '<li><span class="fi">' + ic("comment") + '</span><div><b>Vote and talk</b><span>Up or down, comments and replies - and moderators when something is wrong.</span></div></li>' +
      '</ul><div class="cmx-stats" id="au-stats"></div>' +
      '<p class="cmx-fine">' + ic("lock") + 'Your email is never shown. The studio works fully without an account.</p></section>' +
    '<section class="cmx-auth-side"><div class="cmx-auth-card" id="au-card"></div></section></div>';
  stats().then(function (s) { var e = $("au-stats"); if (e) e.innerHTML = statTiles(s) });
  authStep(V);
}
var POLL = null, GOOGLE_CHECK = null;
// back to the studio's window from the browser: the Google sign-in is looked at at once
window.addEventListener("focus", function () { if (GOOGLE_CHECK) GOOGLE_CHECK() });
function authStep(V) {
  var card = $("au-card");
  if (!card) return;
  clearInterval(POLL);
  var why = V.why ? '<div class="cmx-why">' + ic("lock") + '<span>To ' + esc(V.why) + ', sign in or make an account.</span></div>' : '';
  var tabs = '<div class="cmx-tabs2" role="tablist"><button type="button" role="tab" data-tab="signin" class="' + (V.step === "signin" ? "on" : "") + '">Sign in</button>' +
    '<button type="button" role="tab" data-tab="signup" class="' + (V.step === "signup" ? "on" : "") + '">Create account</button></div>';
  var googleBtn = function (t) { return '<button type="button" class="cmx-google" id="au-google">' + GOOGLE + t + '</button><div class="cmx-or">or with your email</div>' };
  var h = "";
  if (V.step === "signin") {
    h = tabs + why + '<h2>Welcome back</h2><p class="lead">Sign in to pull, share, vote and comment.</p>' + googleBtn("Sign in with Google") +
      field("au-email", "Email", V.email || "", { icon: "mail", type: "email", auto: "email", ph: "you@example.com", msg: false }) +
      field("au-pw", "Password", "", { icon: "lock", type: "password", auto: "current-password", eye: true, msg: false,
        side: '<button type="button" class="cmx-link" id="au-forgot">Forgot it?</button>' }) +
      '<div class="cmx-alert" id="au-err" hidden></div>' +
      '<button class="cmx-btn primary big block" id="au-go" style="margin-top:6px">' + ic("arrow") + 'Sign in</button>' +
      '<p class="cmx-foot">New here? <button type="button" class="cmx-link" data-tab="signup">Create an account</button></p>';
  } else if (V.step === "signup") {
    var pd = V.pending || {};
    h = tabs + why + '<h2>Create your account</h2><p class="lead">One account for the whole community. Free, and the studio never needs it.</p>' + googleBtn("Sign up with Google") +
      '<div class="cmx-row2">' + field("su-name", "Name", pd.name || "", { icon: "person", auto: "name", max: 40, msg: true }) +
        field("su-handle", "Username", pd.handle || "", { pre: "@", max: 24, st: true, spell: false, auto: "username" }) + '</div>' +
      field("su-email", "Email", pd.email || V.email || "", { icon: "mail", type: "email", auto: "email", ph: "you@example.com", st: true }) +
      field("su-pw", "Password", "", { icon: "lock", type: "password", auto: "new-password", eye: true, msg: false }) +
      '<div class="cmx-meter" id="su-meter" data-s="0"><i></i><i></i><i></i><i></i></div>' +
      '<ul class="cmx-rules" id="su-rules"><li data-r="len">' + ic("check") + '8 characters or more</li><li data-r="mix">' + ic("check") + 'A letter and a number</li>' +
        '<li data-r="case">' + ic("check") + 'Upper and lower case</li><li data-r="sym">' + ic("check") + 'A symbol, or 12+ characters</li></ul>' +
      '<div style="height:12px"></div>' +
      field("su-pw2", "Confirm the password", "", { icon: "lock", type: "password", auto: "new-password", eye: true, st: true }) +
      '<label class="cmx-check"><input type="checkbox" id="su-agree"><span>I agree to the <button type="button" class="cmx-link" id="su-rules-link">community rules</button>: my own work or credited, none of the game’s files, nothing hurtful.</span></label>' +
      '<div class="cmx-alert" id="au-err" hidden></div>' +
      '<button class="cmx-btn primary big block" id="su-go" disabled>' + ic("check") + 'Create account</button>' +
      '<p class="cmx-foot">Already have one? <button type="button" class="cmx-link" data-tab="signin">Sign in</button></p>';
  } else if (V.step === "verify") {
    h = '<div class="cmx-big-ico">' + ic("mail") + '</div><h2>Check your email</h2><p class="lead">We sent a 6-digit code to <b>' + esc(V.email) + '</b>. Type it here to finish.</p>' +
      codeBoxes("vf") + '<div class="cmx-alert" id="au-err" hidden></div>' +
      '<button class="cmx-btn primary big block" id="vf-go">' + ic("check") + 'Confirm</button>' +
      '<p class="cmx-foot"><button type="button" class="cmx-link" id="vf-again">Send a new code</button> · <button type="button" class="cmx-link" id="vf-back">Use another email</button></p>';
  } else if (V.step === "forgot") {
    h = '<div class="cmx-big-ico">' + ic("key") + '</div><h2>Forgot your password?</h2><p class="lead">We email you a code to set a new one.</p>' +
      field("fg-email", "Email", V.email || "", { icon: "mail", type: "email", auto: "email", msg: false }) +
      '<div class="cmx-alert" id="au-err" hidden></div>' +
      '<button class="cmx-btn primary big block" id="fg-go">' + ic("mail") + 'Send the code</button>' +
      '<p class="cmx-foot"><button type="button" class="cmx-link" data-tab="signin">Back to signing in</button></p>';
  } else if (V.step === "reset") {
    h = '<div class="cmx-big-ico">' + ic("key") + '</div><h2>A new password</h2><p class="lead">We sent a code to <b>' + esc(V.email) + '</b>.</p>' +
      codeBoxes("rs") + field("rs-pw", "New password", "", { icon: "lock", type: "password", auto: "new-password", eye: true, msg: false }) +
      '<div class="cmx-meter" id="rs-meter" data-s="0"><i></i><i></i><i></i><i></i></div><div style="height:12px"></div>' +
      field("rs-pw2", "Confirm it", "", { icon: "lock", type: "password", auto: "new-password", eye: true, st: true }) +
      '<div class="cmx-alert" id="au-err" hidden></div>' +
      '<button class="cmx-btn primary big block" id="rs-go">' + ic("check") + 'Set it and sign in</button>' +
      '<p class="cmx-foot"><button type="button" class="cmx-link" data-tab="forgot">Send a new code</button></p>';
  } else if (V.step === "google") {
    h = '<div class="cmx-wait">' + radar() + '<h2>Waiting for Google</h2><p class="lead">Google’s page is open in your browser - it may be behind this window. ' +
      'Sign in there; when it says you are signed in, the studio carries on by itself.</p>' +
      '<div class="cmx-alert" id="au-err" hidden></div>' +
      '<div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:6px">' +
        '<button class="cmx-btn" id="gg-again">' + ic("globe") + 'Open the page again</button>' +
        '<button class="cmx-btn ghost" id="gg-copy">' + ic("link") + 'Copy the link</button></div>' +
      '<p class="cmx-foot"><button type="button" class="cmx-link" data-tab="signin">Cancel</button></p></div>';
  } else if (V.step === "name") {
    h = '<div class="cmx-big-ico">' + ic("person") + '</div><h2>One last thing</h2><p class="lead">Choose the name others see next to your missions and comments. Your email is never shown.</p><div id="au-pf"></div>';
  }
  card.innerHTML = h;
  card.querySelectorAll("[data-tab]").forEach(function (b) { b.addEventListener("click", function () { V.step = b.getAttribute("data-tab"); authStep(V) }) });
  bindEyes(card);
  bindAuth(V);
}
function err(e) { var el = $("au-err"); if (el) { el.hidden = false; el.innerHTML = ic("warn") + '<span>' + esc(e.message || String(e)) + '</span>' } }
function clearErr() { var el = $("au-err"); if (el) el.hidden = true }
function busy(b, on, label) {
  if (!b) return;
  if (on) { b.dataset.label = b.innerHTML; b.disabled = true; b.innerHTML = '<span class="cmx-spin" style="width:16px;height:16px;border-width:2px"></span>' + (label || "One moment…") }
  else { b.disabled = false; if (b.dataset.label) b.innerHTML = b.dataset.label }
}
function onEnter(id, fn) { var el = $(id); if (el) el.addEventListener("keydown", function (e) { if (e.key === "Enter") fn() }) }
function emailOk(s) { return /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(s) }
// how strong a password is (0-4), and what it has
function strength(pw, email, name) {
  var r = { len: pw.length >= 8, mix: /[A-Za-z]/.test(pw) && /\d/.test(pw), "case": /[a-z]/.test(pw) && /[A-Z]/.test(pw), sym: /[^A-Za-z0-9]/.test(pw) || pw.length >= 12 };
  var low = pw.toLowerCase(), local = String(email || "").split("@")[0].toLowerCase(), nm = String(name || "").toLowerCase().replace(/\s+/g, "");
  var weak = COMMON.indexOf(low) >= 0 || (local.length > 2 && low.indexOf(local) >= 0) || (nm.length > 2 && low.indexOf(nm) >= 0);
  var s = !pw ? 0 : !(r.len && r.mix) || weak ? 1 : 2 + (r["case"] ? 1 : 0) + (r.sym ? 1 : 0);
  return { s: Math.min(4, s), rules: r, weak: weak, ok: r.len && r.mix && !weak };
}
function codeBoxes(p) {
  var h = '<div class="cmx-code" id="' + p + '-code">';
  for (var i = 0; i < 6; i++) h += '<input inputmode="numeric" autocomplete="' + (i ? "off" : "one-time-code") + '" maxlength="1" aria-label="Digit ' + (i + 1) + '">';
  return h + '</div>';
}
function bindCode(p, done) {
  var box = $(p + "-code"), ins = [].slice.call(box.querySelectorAll("input"));
  function val() { return ins.map(function (i) { return i.value }).join("") }
  ins.forEach(function (inp, i) {
    inp.addEventListener("input", function () {
      var d = inp.value.replace(/\D/g, "");
      if (d.length > 1) {                  // pasted, or filled in by the system
        d.split("").slice(0, 6 - i).forEach(function (c, k) { ins[i + k].value = c });
        (ins[Math.min(5, i + d.length)] || inp).focus();
      } else { inp.value = d; if (d && ins[i + 1]) ins[i + 1].focus() }
      box.classList.remove("bad");
      if (val().length === 6 && done) done(val());
    });
    inp.addEventListener("keydown", function (e) {
      if (e.key === "Backspace" && !inp.value && ins[i - 1]) { ins[i - 1].focus(); ins[i - 1].value = "" }
      else if (e.key === "ArrowLeft" && ins[i - 1]) ins[i - 1].focus();
      else if (e.key === "ArrowRight" && ins[i + 1]) ins[i + 1].focus();
    });
    inp.addEventListener("paste", function (e) {
      var t = (e.clipboardData || window.clipboardData).getData("text").replace(/\D/g, "").slice(0, 6);
      if (!t) return;
      e.preventDefault();
      t.split("").forEach(function (c, k) { if (ins[k]) ins[k].value = c });
      (ins[Math.min(5, t.length)] || ins[5]).focus();
      if (t.length === 6 && done) done(t);
    });
  });
  setTimeout(function () { ins[0].focus() }, 30);
  return { value: val, bad: function () { box.classList.add("bad"); ins.forEach(function (i) { i.value = "" }); ins[0].focus() } };
}
function bindAuth(V) {
  var s = V.step;
  if ($("au-google")) $("au-google").addEventListener("click", function () {
    var b = this;
    busy(b, true, "Opening Google…");
    api("POST", "auth/google", {}).then(function (r) {
      V.step = "google"; V.url = r.url; authStep(V);
    }).catch(function (e) { busy(b, false); err(e) });
  });
  if (s === "google") {
    // asked every second and a bit, and at once when the studio's window is back in front:
    // signed in, by this sign-in or an earlier one, is all that matters
    GOOGLE_CHECK = function () {
      if (!isOpen() || VIEW !== V || V.step !== "google") { clearInterval(POLL); GOOGLE_CHECK = null; return }
      api("GET", "auth/google").then(function (g) {
        if (VIEW !== V || V.step !== "google") return;
        if (g.signed_in || g.state === "done") { clearInterval(POLL); GOOGLE_CHECK = null; authDone(V) }
        else if (g.state === "failed") err(new Error(g.error || "Google sign-in did not finish. Open the page again, or cancel."));
      }).catch(function () {});
    };
    POLL = setInterval(GOOGLE_CHECK, 1200);
    GOOGLE_CHECK();
    $("gg-again").addEventListener("click", function () {
      clearErr();
      api("POST", "auth/google-again", {}).then(function (r) { V.url = r.url; toast("Google’s page is open in your browser") })
        .catch(function () { api("POST", "auth/google", {}).then(function (r) { V.url = r.url }).catch(err) });
    });
    $("gg-copy").addEventListener("click", function () {
      if (!V.url) return;
      (navigator.clipboard ? navigator.clipboard.writeText(V.url) : Promise.reject()).then(function () { toast("The link is copied: paste it into your browser") })
        .catch(function () { toast("Copy it from here: " + V.url) });
    });
  }
  if (s === "signin") {
    var go = function () {
      clearErr();
      var b = $("au-go"), email = $("au-email").value.trim();
      V.email = email;
      if (!emailOk(email)) { err(new Error("That doesn’t look like an email address.")); $("au-email").focus(); return }
      if (!$("au-pw").value) { $("au-pw").focus(); return }
      busy(b, true, "Signing in…");
      api("POST", "auth/signin", { email: email, password: $("au-pw").value }).then(function () { authDone(V) }).catch(function (e) {
        busy(b, false);
        if (e.code === "verify") { V.step = "verify"; authStep(V) } else err(e);
      });
    };
    $("au-go").addEventListener("click", go);
    onEnter("au-pw", go); onEnter("au-email", function () { $("au-pw").focus() });
    $("au-forgot").addEventListener("click", function () { V.email = $("au-email").value.trim(); V.step = "forgot"; authStep(V) });
    ($("au-email").value ? $("au-pw") : $("au-email")).focus();
  } else if (s === "signup") {
    var handleOk = handleCheck($("su-handle"));
    var nameEl = $("su-name");
    // the username follows the name until it is typed itself
    var typed = !!$("su-handle").value;
    $("su-handle").addEventListener("input", function () { typed = true });
    nameEl.addEventListener("input", function () {
      if (typed) return;
      var h = nameEl.value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 24);
      $("su-handle").value = h;
      $("su-handle").dispatchEvent(new Event("input"));
      typed = false;
    });
    function paint() {
      var pw = $("su-pw").value, st = strength(pw, $("su-email").value, nameEl.value);
      $("su-meter").setAttribute("data-s", st.s);
      $("su-rules").querySelectorAll("[data-r]").forEach(function (li) {
        var ok = st.rules[li.getAttribute("data-r")]; li.classList.toggle("ok", !!ok); li.innerHTML = ic(ok ? "check" : "x") + li.textContent;
      });
      var pw2 = $("su-pw2").value, m = $("su-pw2-msg"), b2 = $("su-pw2-box"), st2 = $("su-pw2-st");
      var match = pw2 && pw2 === pw;
      b2.classList.toggle("good", !!match); b2.classList.toggle("bad", !!pw2 && !match);
      st2.className = "st " + (match ? "good" : pw2 ? "bad" : ""); st2.innerHTML = match ? ic("check") : pw2 ? ic("x") : "";
      m.className = "cmx-msg " + (match ? "good" : pw2 ? "bad" : ""); m.textContent = match ? "The passwords match" : pw2 ? "They don’t match yet" : "";
      if (st.weak && pw) { m.className = "cmx-msg bad"; m.textContent = "That password is too easy to guess" }
      var em = $("su-email").value.trim(), eb = $("su-email-box"), es = $("su-email-st");
      eb.classList.toggle("good", emailOk(em)); eb.classList.toggle("bad", !!em && !emailOk(em) && document.activeElement !== $("su-email"));
      es.className = "st " + (emailOk(em) ? "good" : ""); es.innerHTML = emailOk(em) ? ic("check") : "";
      var ready = nameEl.value.trim() && handleOk() && emailOk(em) && st.ok && match && $("su-agree").checked;
      $("su-go").disabled = !ready;
      return ready;
    }
    ["su-name", "su-handle", "su-email", "su-pw", "su-pw2"].forEach(function (id) { $(id).addEventListener("input", function () { setTimeout(paint, 0) }) });
    $("su-email").addEventListener("blur", paint);
    $("su-agree").addEventListener("change", paint);
    // the username's check answers a moment later
    var tick = setInterval(function () { if (!$("su-go")) { clearInterval(tick); return } paint() }, 400);
    $("su-rules-link").addEventListener("click", rulesDialog);
    function go2() {
      clearErr();
      if (!paint()) return;
      var b = $("su-go");
      V.pending = { name: nameEl.value.trim(), handle: $("su-handle").value.trim().replace(/^@/, ""), email: $("su-email").value.trim() };
      V.email = V.pending.email;
      busy(b, true, "Creating your account…");
      api("POST", "auth/signup", { email: V.email, password: $("su-pw").value, name: V.pending.name }).then(function (r) {
        if (r.verify) { V.step = "verify"; authStep(V) } else authDone(V);
      }).catch(function (e) { busy(b, false); err(e) });
    }
    $("su-go").addEventListener("click", go2);
    onEnter("su-pw2", go2);
    nameEl.focus();
    paint();
  } else if (s === "verify") {
    var code = bindCode("vf", function (v) { confirm(v) });
    var confirm = function (v) {
      clearErr();
      var b = $("vf-go");
      v = v || code.value();
      if (v.length !== 6) { err(new Error("Type the 6 digits from the email.")); return }
      busy(b, true, "Checking…");
      api("POST", "auth/verify", { email: V.email, code: v }).then(function () { authDone(V) }).catch(function (e) {
        busy(b, false);
        if (e.code === "signin") { V.step = "signin"; authStep(V); err(e) } else { code.bad(); err(e) }
      });
    };
    $("vf-go").addEventListener("click", function () { confirm() });
    resendTimer($("vf-again"), function () { return api("POST", "auth/resend", { email: V.email }) });
    $("vf-back").addEventListener("click", function () { V.step = "signup"; authStep(V) });
  } else if (s === "forgot") {
    var go3 = function () {
      clearErr();
      var b = $("fg-go");
      V.email = $("fg-email").value.trim();
      if (!emailOk(V.email)) { err(new Error("That doesn’t look like an email address.")); return }
      busy(b, true, "Sending…");
      api("POST", "auth/resend", { email: V.email, kind: "forget-password" }).then(function () { V.step = "reset"; authStep(V) })
        .catch(function (e) { busy(b, false); err(e) });
    };
    $("fg-go").addEventListener("click", go3);
    onEnter("fg-email", go3);
    $("fg-email").focus();
  } else if (s === "reset") {
    var rc = bindCode("rs");
    function paintR() {
      var pw = $("rs-pw").value, st = strength(pw, V.email, ""), pw2 = $("rs-pw2").value, match = pw2 && pw === pw2;
      $("rs-meter").setAttribute("data-s", st.s);
      $("rs-pw2-box").classList.toggle("good", !!match); $("rs-pw2-box").classList.toggle("bad", !!pw2 && !match);
      $("rs-pw2-st").className = "st " + (match ? "good" : pw2 ? "bad" : ""); $("rs-pw2-st").innerHTML = match ? ic("check") : pw2 ? ic("x") : "";
      $("rs-pw2-msg").className = "cmx-msg " + (st.ok ? (match ? "good" : pw2 ? "bad" : "") : pw ? "bad" : "");
      $("rs-pw2-msg").textContent = pw && !st.ok ? "8 or more characters, with a letter and a number" : match ? "The passwords match" : pw2 ? "They don’t match yet" : "";
      return st.ok && match;
    }
    $("rs-pw").addEventListener("input", paintR); $("rs-pw2").addEventListener("input", paintR);
    $("rs-go").addEventListener("click", function () {
      clearErr();
      if (rc.value().length !== 6) { err(new Error("Type the 6 digits from the email.")); return }
      if (!paintR()) { $("rs-pw").focus(); return }
      var b = this;
      busy(b, true, "Setting it…");
      api("POST", "auth/reset", { email: V.email, code: rc.value(), password: $("rs-pw").value }).then(function () { authDone(V) })
        .catch(function (e) { busy(b, false); rc.bad(); err(e) });
    });
  } else if (s === "name") {
    profileForm($("au-pf"), null, true, function () { authFinish(V) });
  }
}
function resendTimer(b, fn) {
  var left = 30, t = null;
  function tickT() {
    if (!document.body.contains(b)) { clearInterval(t); return }
    b.disabled = left > 0;
    b.textContent = left > 0 ? "Send a new code (" + left + "s)" : "Send a new code";
    left--;
    if (left < -1) clearInterval(t);
  }
  t = setInterval(tickT, 1000); tickT();
  b.addEventListener("click", function () {
    if (b.disabled) return;
    fn().then(function () { toast("A new code is on its way"); left = 30; clearInterval(t); t = setInterval(tickT, 1000); tickT() }).catch(err);
  });
}
// signed in: the name chosen at sign-up taken now, else asked for; then on with what was wanted
function authDone(V) {
  refreshState().then(function (s) {
    if (s.signed_in && !s.profile) {
      var pd = V.pending;
      if (pd && pd.handle) {
        return call("save_profile", { handle: pd.handle, name: pd.name || pd.handle }).then(refreshState).then(function () { authFinish(V) })
          .catch(function (e) { V.step = "name"; authStep(V); setTimeout(function () { err(e) }, 0) });
      }
      V.step = "name"; authStep(V);
      return;
    }
    authFinish(V);
  });
}
function authFinish(V) {
  STATS = null;
  if (ST.profile) toast("Signed in as @" + ST.profile.handle);
  var then = V.then;
  VIEW = BACK.pop() || { kind: "discover" };
  show();
  if (then) then();
}
function rulesDialog() {
  dialog("The community rules",
    '<ul class="cmx-goes">' +
      '<li>' + ic("check") + '<span><b>Your own work, or credited.</b> A remix carries its line by itself; anything else you build on, say so.</span></li>' +
      '<li>' + ic("check") + '<span><b>None of the game’s files.</b> A mission is a plan of changes; the studio never uploads the game’s own files, and neither should pictures or links.</span></li>' +
      '<li>' + ic("check") + '<span><b>Nothing hurtful.</b> No hate, harassment or adult content in missions, pictures, names or comments.</span></li>' +
      '<li>' + ic("check") + '<span><b>Report, don’t fight.</b> Moderators look at every report; they can hide missions, remove comments and close accounts.</span></li>' +
    '</ul><div class="foot"><button class="cmx-btn primary" id="rl-ok">Got it</button></div>');
  $("rl-ok").addEventListener("click", H.closeSheet);
}

// ------------------------------------------------------------------ small form parts
function seg(id, cur) {
  return '<div class="cmx-seg" id="' + id + '">' + DIFFS.map(function (d) {
    return '<button type="button" class="' + d + (d === cur ? " on" : "") + '" data-v="' + d + '"><span class="dot"></span>' + d + '</button>' }).join("") + '</div>';
}
function bindSeg(id, onChange) {
  $(id).querySelectorAll("[data-v]").forEach(function (b) {
    b.addEventListener("click", function () {
      $(id).querySelectorAll("[data-v]").forEach(function (x) { x.classList.toggle("on", x === b) });
      if (onChange) onChange(b.getAttribute("data-v"));
    });
  });
}
function segValue(id) { var b = $(id).querySelector(".on"); return b ? b.getAttribute("data-v") : "" }
function tagsHtml(id, cur) {
  return '<div class="cmx-tags" id="' + id + '">' + TAGS.map(function (t) {
    var on = cur.indexOf(t) >= 0;
    return '<button type="button" class="cmx-pill' + (on ? " on" : "") + '" data-t="' + t + '" aria-pressed="' + on + '">' + ic(TAG_IC[t]) + t + '</button>' }).join("") + '</div>';
}
function bindTags(id, onChange) {
  $(id).querySelectorAll("[data-t]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (!b.classList.contains("on") && tagsValue(id).length >= 6) { toast("At most 6"); return }
      b.classList.toggle("on"); b.setAttribute("aria-pressed", String(b.classList.contains("on")));
      if (onChange) onChange(tagsValue(id));
    });
  });
}
function tagsValue(id) { return [].map.call($(id).querySelectorAll(".on"), function (b) { return b.getAttribute("data-t") }) }
// a mission's name as you type it: free in the community? Returns "is it fine now?"
function nameCheck(input, except, onChange) {
  var t = null, n = 0, good = false;
  var box = $(input.id + "-box"), st = $(input.id + "-st"), msg = $(input.id + "-msg");
  function set(state, text) {
    good = state === "good";
    box.classList.toggle("good", state === "good"); box.classList.toggle("bad", state === "bad");
    st.className = "st " + (state || ""); st.innerHTML = state === "good" ? ic("check") : state === "bad" ? ic("x") : state === "wait" ? '<span class="cmx-spin" style="width:14px;height:14px;border-width:2px"></span>' : "";
    msg.className = "cmx-msg " + (state === "good" ? "good" : state === "bad" ? "bad" : ""); msg.textContent = text;
  }
  function check() {
    var v = input.value.trim(), k = ++n;
    if (onChange) onChange(v);
    if (v.length < 3) { set("bad", "3 to 60 characters"); return }
    set("wait", "Checking…");
    call("name_free", { name: v, except: except || null }).then(function (r) {
      if (k !== n) return;
      set(r.free ? "good" : "bad", r.free ? "No other mission has this name" : "Taken: another mission in the community has this name");
    }).catch(function () { if (k === n) set("", "") });
  }
  input.addEventListener("input", function () { clearTimeout(t); t = setTimeout(check, 300) });
  check();
  return function () { return good };
}

// ------------------------------------------------------------------ pictures
function loadImage(src) {
  return new Promise(function (ok, no) {
    var i = new Image();
    i.onload = function () { ok(i) };
    i.onerror = no;
    i.src = src;
  });
}
// a picture cut to w x h (the middle of it), as WebP under cap bytes
function encode(img, w, h, cap) {
  var c = document.createElement("canvas");
  c.width = w; c.height = h;
  var g = c.getContext("2d"), iw = img.naturalWidth || img.width, ih = img.naturalHeight || img.height;
  var s = Math.max(w / iw, h / ih), dw = iw * s, dh = ih * s;
  g.fillStyle = "#08180a"; g.fillRect(0, 0, w, h);
  g.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
  var q = 0.86, out = c.toDataURL("image/webp", q);
  while (out.length * 0.75 > cap && q > 0.3) { q -= 0.08; out = c.toDataURL("image/webp", q) }
  return out;
}
// Framing a shot: the page steps aside, the map or the 3D view is there to set
// up, a bar takes the picture (or gives up)
var CAP = null;
function capture(then) {
  build();
  var bar = $("cm-capbar");
  if (!bar) {
    bar = document.createElement("div");
    bar.className = "cmx-capbar"; bar.id = "cm-capbar"; bar.hidden = true;
    document.body.appendChild(bar);
  }
  CAP = { then: then };
  EL.hidden = true;
  bar.innerHTML = ic("camera") + '<div><b>Frame the shot</b><small>Move the map, or open the 3D view and fly to it. Then take the picture.</small></div>' +
    '<button class="cmx-btn primary" id="cm-cap-go">' + ic("camera") + 'Take the picture</button><button class="cmx-btn ghost" id="cm-cap-no">Cancel</button>';
  bar.hidden = false;
  $("cm-cap-go").addEventListener("click", function () {
    var url = H.can3d() ? H.capture3d() : H.captureMap();
    if (!url) { toast("Nothing to take a picture of yet"); return }
    loadImage(url).then(function (img) { capEnd(img) }).catch(function () { toast("That picture could not be taken"); capEnd(null) });
  });
  $("cm-cap-no").addEventListener("click", function () { capEnd(null) });
}
function capEnd(img) {
  var c = CAP;
  CAP = null;
  var bar = $("cm-capbar"); if (bar) bar.hidden = true;
  EL.hidden = false;
  if (c && img) c.then(img);
  else show();
}
function pickFile(then) {
  var inp = document.createElement("input");
  inp.type = "file"; inp.accept = "image/*";
  inp.onchange = function () {
    var f = inp.files && inp.files[0];
    if (f) loadImage(URL.createObjectURL(f)).then(then).catch(function () { toast("That picture could not be read") });
  };
  inp.click();
}

// ------------------------------------------------------------------ sharing
var STEPS = [["check", "Check", "Saved, and ready to go", "shieldCheck"], ["about", "About", "Its name and briefing", "file"],
  ["pictures", "Pictures", "A cover and screenshots", "image"], ["credits", "Credits", "Who made it, who may change it", "users"],
  ["review", "Review", "As others will see it", "eye"]];
function draftKey(id) { return "community:draft:" + id }
function share(mode) {
  if (!ST.configured) { toast("The community is not open yet"); return }
  var cur = H.current();
  if (cur && cur.preview) { toast("Pull it into your studio first, and change it"); return }
  needAccount("share a mission", function () {
    var c = H.current();
    if (!isOpen()) open({ kind: "discover" });
    if (c && !c.readonly) go({ kind: "share", mode: mode || null });
    else go({ kind: "pick", mode: mode || null });
  });
}
// no mission of yours open: choose one
function showPick(body) {
  body.innerHTML = '<div class="cmx-share" style="grid-template-columns:1fr"><div><div class="cmx-over">' + ic("upload") + 'Share a mission</div>' +
    '<h1 style="font:600 34px Barlow Condensed,sans-serif;margin:6px 0 4px">Which mission?</h1><p class="cmx-note">' + ic("info") +
    '<span>It opens in the studio behind this page, so the cover can be framed in its 3D view or on its map.</span></p>' +
    '<div class="cmx-grid" id="cm-pick" style="margin-top:18px"><div class="cmx-loading"><div class="cmx-spin"></div></div></div></div></div>';
  H.myMissions().then(function (list) {
    var g = $("cm-pick");
    if (!g) return;
    if (!list.length) { g.outerHTML = '<div class="cmx-empty" style="margin-top:18px">' + radar() + '<b>No missions of yours yet</b><p>Make one in the studio first, then share it.</p></div>'; return }
    g.innerHTML = list.map(function (m) {
      return '<article class="cmx-card" tabindex="0" data-pick="' + esc(m.id) + '"><div class="cmx-card-img" style="background-image:url(' + esc(m.cover || "") + ')">' +
        '<div class="bl">' + ic("map") + esc(H.levelName(m.base.level)) + '</div>' +
        (m.community && m.community.published ? '<div class="tl"><span class="cmx-badge gold">' + ic("globe") + 'shared · v' + m.community.published.version + '</span></div>' : '') +
        '<div class="view"><span>' + ic("upload") + 'Share this one</span></div></div>' +
        '<div class="cmx-card-b"><h3>' + esc(m.name) + '</h3><p>' + esc(m.description || "") + '</p><div class="cmx-card-stats"><span>' + ic("person") + m.guards + '</span><span>' + ic("layers") + m.changes + ' changes</span></div></div></article>';
    }).join("");
    g.querySelectorAll("[data-pick]").forEach(function (c) {
      function pick() {
        g.innerHTML = '<div class="cmx-loading"><div class="cmx-spin"></div></div>';
        H.openMission(c.getAttribute("data-pick"), function () {
          build(); EL.hidden = false;
          VIEW = { kind: "share", mode: VIEW && VIEW.mode };
          show();
        });
        EL.hidden = false;
      }
      c.addEventListener("click", pick);
      c.addEventListener("keydown", function (e) { if (e.key === "Enter") pick() });
    });
  });
}
function showShare(body) {
  var V = VIEW;
  var cur = H.current();
  if (!cur || cur.readonly) { VIEW = { kind: "pick" }; show(); return }
  if (!V.W || V.W.mid !== cur.id) {
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(draftKey(cur.id)) || "null") } catch (e) {}
    V.W = { step: 0, mid: cur.id, cur: cur, pre: null, checks: null, info: H.shareInfo(), saved: saved,
      F: Object.assign({ name: cur.name, summary: "", description: cur.description || "", difficulty: "normal", tags: [],
        play_minutes: "", video_url: "", allow_remix: true, coauthors: "", notes: "", cover: null, thumb: null, shots: [],
        with_picture: true }, saved || {}) };
    V.W.F.agree = false;
    V.W.F.mode = V.mode || V.W.F.mode || "new";
  }
  wizard(body, V.W);
}
function wizard(body, W) {
  var F = W.F, cur = W.cur;
  function keep() { try { var k = Object.assign({}, F); delete k.agree; localStorage.setItem(draftKey(cur.id), JSON.stringify(k)) } catch (e) {} }
  function previewCard() {
    var me = ST.profile || {};
    return cardHtml({ name: F.name || cur.name, summary: F.summary || "One line for its card", author: me, level: cur.base.level, kind: cur.base.kind,
      score: 0, comments: 0, pulls: 0, objectives: W.info.objectives.length, facts: W.info.facts, difficulty: F.difficulty,
      remix_of: W.pre && W.pre.origin, thumbUrl: F.thumb || F.cover || "" }, true);
  }
  var s = STEPS[W.step][0];
  body.innerHTML = '<div class="cmx-share"><aside class="cmx-rail"><div><div class="cmx-over">' + ic("upload") + (F.mode === "update" ? "Publish an update" : "Share a mission") + '</div>' +
      '<h2>' + esc(F.name || cur.name) + '</h2></div>' +
      '<ol class="cmx-steps">' + STEPS.map(function (x, i) {
        return '<li class="' + (i === W.step ? "on" : i < W.step ? "done" : "") + '"><span class="sn">' + ic(i < W.step ? "check" : x[3]) + '</span><div><b>' + x[1] + '</b><small>' + x[2] + '</small></div></li>' }).join("") + '</ol>' +
      '<div><div class="lbl">How its card will look</div><div id="wz-prev">' + previewCard() + '</div></div></aside>' +
    '<section class="cmx-step" id="wz-step"></section></div>';
  var host = $("wz-step");
  function head(title, sub) {
    return '<header><div class="cmx-over">Step ' + (W.step + 1) + ' of ' + STEPS.length + '</div><h1>' + title + '</h1><p>' + sub + '</p></header>';
  }
  function foot(label, ok, icon) {
    return '<footer>' + (W.step ? '<button class="cmx-btn" id="wz-back">' + ic("back") + 'Back</button>' : '<button class="cmx-btn ghost" id="wz-cancel">Cancel</button>') +
      '<span class="grow"></span><button class="cmx-btn primary big" id="wz-next"' + (ok === false ? ' disabled' : '') + '>' + (label || "Next") + ic(icon || "arrow") + '</button></footer>';
  }
  function refreshPreview() { var p = $("wz-prev"); if (p) p.innerHTML = previewCard() }
  function step(n) { collect(); keep(); W.step = n; wizard(body, W); var m = $("cm-main"); if (m) m.scrollTop = 0 }
  function collect() {
    if (s === "about" && $("wz-name")) {
      F.name = $("wz-name").value.trim(); F.summary = $("wz-sum").value.trim(); F.description = $("wz-desc").value;
      F.difficulty = segValue("wz-diff") || "normal"; F.tags = tagsValue("wz-tags"); F.play_minutes = $("wz-min").value;
    } else if (s === "pictures" && $("wz-video")) {
      F.video_url = $("wz-video").value.trim();
      if ($("wz-pic")) F.with_picture = $("wz-pic").checked;
    } else if (s === "credits" && $("wz-co")) {
      F.coauthors = $("wz-co").value; F.allow_remix = $("wz-rmx").checked; F.notes = $("wz-notes").value;
    }
  }
  function bindNav() {
    if ($("wz-cancel")) $("wz-cancel").addEventListener("click", back);
    if ($("wz-back")) $("wz-back").addEventListener("click", function () { step(W.step - 1) });
  }

  if (s === "check") {
    if (!W.checks) {
      host.innerHTML = head("Is it ready?", "The studio saves the mission and checks it, as before applying it.") + '<div class="cmx-loading"><div class="cmx-spin"></div></div>' + foot("Next", false);
      bindNav();
      Promise.all([api("GET", "precheck?mission=" + encodeURIComponent(cur.id)), H.check()]).then(function (r) {
        W.pre = r[0]; W.checks = r[1] || [];
        if (!W.pre.published) F.mode = "new";
        else if (!W.saved && !VIEW.mode) F.mode = "update";
        var o = W.pre.origin;
        return Promise.all([
          o && o.id ? call("get_mission", { id: o.id }).then(function (m) { W.remixClosed = !m.allow_remix && !(ST.profile && m.author && m.author.id === ST.profile.id) }).catch(function () {}) : null,
          W.pre.published ? call("get_mission", { id: W.pre.published.id }).then(function (m) {
            W.published = m;
            if (F.mode === "update" && !W.saved) Object.assign(F, { name: m.name, summary: m.summary, description: m.description, difficulty: m.difficulty,
              tags: m.tags || [], play_minutes: m.play_minutes || "", video_url: m.video_url || "", allow_remix: m.allow_remix,
              coauthors: (m.coauthors || []).map(function (p) { return p.handle }).join(", ") });
          }).catch(function () {}) : null]);
      }).then(function () { if (VIEW && VIEW.W === W && W.step === 0) wizard(body, W) })
        .catch(function (e) { host.innerHTML = head("Is it ready?", "") + '<div class="cmx-alert">' + ic("warn") + '<span>' + esc(e.message) + '</span></div>' + foot("Next", false); bindNav() });
      return;
    }
    var pre = W.pre, errs = W.checks.filter(function (r) { return r.level === "error" }), warns = W.checks.filter(function (r) { return r.level === "warn" });
    var objs = W.info.objectives, rows = [];
    rows.push(["ok", "Saved", "What goes up is the mission as it is now."]);
    rows.push([objs.length ? "ok" : "bad", objs.length ? plural(objs.length, "objective") : "No objectives", objs.length ? objs.map(function (o) { return o.text }).slice(0, 3).join(" · ") + (objs.length > 3 ? " …" : "") : "A mission needs at least one: add one in the Objectives tab."]);
    rows.push([errs.length ? "bad" : "ok", errs.length ? plural(errs.length, "problem") + " to fix first" : "Nothing blocks the build", errs.length ? errs.slice(0, 4).map(function (r) { return r.text }).join(" · ") : "The same checks Apply makes."]);
    if (warns.length) rows.push(["warn", plural(warns.length, "thing") + " to look at", warns.slice(0, 3).map(function (r) { return r.text }).join(" · ")]);
    if (pre.origin && pre.origin.id) {
      var unchanged = pre.unchanged && F.mode !== "update";
      rows.push([unchanged || (W.remixClosed && F.mode !== "update") ? "bad" : "ok", unchanged ? "Nothing changed since you pulled it" : W.remixClosed && F.mode !== "update" ? "Its author does not allow remixes" : "A remix",
        "Pulled from “" + pre.origin.name + "” by @" + ((pre.origin.author && pre.origin.author.handle) || pre.origin.author || "?") + (unchanged ? ". Change something before sharing it." : ". It carries its line and credits the original.")]);
    }
    var blocked = rows.some(function (r) { return r[0] === "bad" });
    host.innerHTML = head("Is it ready?", "The studio saved the mission and checked it, as before applying it.") +
      (pre.published ? '<div class="cmx-field"><div class="lab">“' + esc(cur.name) + '” is already in the community (version ' + pre.published.version + ')</div><div class="cmx-choice">' +
        '<button type="button" data-mode="update" class="' + (F.mode === "update" ? "on" : "") + '">' + ic("history") + '<span><b>Publish an update</b><small>Version ' + (pre.published.version + 1) + ' of the same mission: its votes, comments and pulls stay.</small></span></button>' +
        '<button type="button" data-mode="new" class="' + (F.mode === "new" ? "on" : "") + '">' + ic("plus") + '<span><b>Share as a new mission</b><small>Another mission, with a name of its own.</small></span></button></div></div>' : '') +
      '<ul class="cmx-checks">' + rows.map(function (r) {
        return '<li class="' + r[0] + '"><span class="ck">' + ic(r[0] === "ok" ? "check" : r[0] === "bad" ? "x" : "warn") + '</span><div><b>' + esc(r[1]) + '</b><small>' + esc(r[2]) + '</small></div></li>' }).join("") + '</ul>' +
      foot("Next", !blocked);
    bindNav();
    host.querySelectorAll("[data-mode]").forEach(function (b) {
      b.addEventListener("click", function () {
        F.mode = b.getAttribute("data-mode");
        if (F.mode === "update" && W.published && !W.saved) Object.assign(F, { name: W.published.name, summary: W.published.summary, description: W.published.description,
          difficulty: W.published.difficulty, tags: W.published.tags || [], allow_remix: W.published.allow_remix });
        wizard(body, W);
      });
    });
    $("wz-next").addEventListener("click", function () { step(1) });
  } else if (s === "about") {
    var f = W.info.facts, facts = [["map", H.levelName(cur.base.level), cur.base.kind === "empty" ? "its empty map" : "base level"], ["flag", W.info.objectives.length, "objectives"]];
    if (f.guards != null) facts.push(["person", f.guards, "guards"]);
    if (f.cameras) facts.push(["cctv", f.cameras, "cameras"]);
    if (f.time_limit) facts.push(["clock", clock(f.time_limit), "time limit"]);
    if (f.weather) facts.push([f.weather === "snow" ? "snow" : "cloud", f.weather, "weather"]);
    if (f.cutscenes) facts.push(["film", f.cutscenes, "cutscenes"]);
    host.innerHTML = head("About the mission", "What players see first. The facts come from the mission itself.") +
      field("wz-name", "Name", F.name, { max: 60, st: true }) +
      field("wz-sum", "Summary: one line for its card", F.summary, { max: 140, ph: "e.g. Get into the radar base at night without raising the alarm", hint: "Up to 140 characters" }) +
      field("wz-desc", "Briefing", F.description, { area: true, rows: 6, max: 6000, ph: "The story, how it plays, what to look out for" }) +
      '<div class="cmx-row2"><div class="cmx-field"><div class="lab">Difficulty</div>' + seg("wz-diff", F.difficulty) + '</div>' +
        field("wz-min", "Play time (minutes, optional)", F.play_minutes, { icon: "timer", type: "number", ph: "20" }) + '</div>' +
      '<div class="cmx-field"><div class="lab">Style (up to 6)</div>' + tagsHtml("wz-tags", F.tags) + '</div>' +
      '<div class="cmx-field" style="margin-top:20px"><div class="lab">Filled in from the mission</div><div class="cmx-intel">' + facts.map(function (x) {
        return '<div><span class="ii">' + ic(x[0]) + '</span><div><b>' + esc(x[1]) + '</b><span>' + esc(x[2]) + '</span></div></div>' }).join("") + '</div></div>' +
      foot("Next");
    bindNav();
    bindSeg("wz-diff", function () { collect(); refreshPreview() }); bindTags("wz-tags");
    var nameOk = nameCheck($("wz-name"), F.mode === "update" && W.pre.published ? W.pre.published.id : null, function () { collect(); refreshPreview() });
    $("wz-sum").addEventListener("input", function () { collect(); refreshPreview() });
    $("wz-next").addEventListener("click", function () {
      collect();
      if (F.name.length < 3) { $("wz-name").focus(); return }
      if (!F.summary) { $("wz-sum").focus(); $("wz-sum-msg").className = "cmx-msg bad"; $("wz-sum-msg").textContent = "A line for its card"; return }
      if (!nameOk() && $("wz-name-box").classList.contains("bad")) { $("wz-name").focus(); return }
      step(2);
    });
  } else if (s === "pictures") {
    var pic = W.pre && W.pre.picture, slots = "";
    for (var i = 0; i < 4; i++) {
      var sh = F.shots[i];
      slots += '<div class="cmx-slot' + (sh ? " has" : "") + '" data-slot="' + i + '"' + (sh ? ' style="background-image:url(' + sh + ')"' : '') + '>' +
        (sh ? '<button type="button" class="rm" data-rm="' + i + '" aria-label="Remove">' + ic("x") + '</button>'
          : (i === F.shots.length ? '<button type="button" class="add" data-add="1">' + ic("plus") + 'Add a screenshot</button>' : '')) + '</div>';
    }
    host.innerHTML = head("Pictures", "A cover for its card and its page, and up to four screenshots.") +
      '<div class="cmx-pics"><div><div class="lab" style="font-size:13px;color:var(--muted);margin-bottom:8px">Cover (needed)</div>' +
        '<div class="cmx-coverbox' + (F.cover ? " has hud" : "") + '" id="wz-cover"' + (F.cover ? ' style="background-image:url(' + F.cover + ')"' : '') + '>' +
          (F.cover ? '' : '<div>' + ic("image") + '<div>No cover yet</div></div>') + '</div>' +
        '<div class="cmx-srcs"><button class="cmx-btn primary" data-src="frame">' + ic("camera") + 'Frame a shot</button>' +
          (pic ? '<button class="cmx-btn" data-src="picture">' + ic("image") + 'The mission’s picture</button>' : '') +
          '<button class="cmx-btn" data-src="file">' + ic("upload") + 'A file…</button></div>' +
        '<p class="cmx-note">' + ic("info") + '<span>Frame a shot hides this page: set up the map or the 3D view, then take the picture. It is cut to 16:9 from the middle.</span></p></div>' +
      '<div><div class="lab" style="font-size:13px;color:var(--muted);margin-bottom:8px">Screenshots (optional)</div><div class="cmx-slots">' + slots + '</div>' +
        '<div style="height:16px"></div>' + field("wz-video", "A video of it (optional)", F.video_url, { icon: "film", ph: "https://youtu.be/…" }) +
        (pic ? '<label class="cmx-switch"><input type="checkbox" id="wz-pic"' + (F.with_picture ? ' checked' : '') + '><span><b>Its own picture too</b><small>The picture the game’s mission list shows.</small></span></label>' : '') +
      '</div></div>' + foot("Next", !!F.cover);
    bindNav();
    function setCover(img) { F.cover = encode(img, 1280, 720, 440000); F.thumb = encode(img, 480, 270, 85000); keep(); wizard(body, W) }
    function addShot(img) { F.shots.push(encode(img, 1280, 720, 440000)); keep(); wizard(body, W) }
    host.querySelectorAll("[data-src]").forEach(function (b) {
      b.addEventListener("click", function () {
        collect();
        var src = b.getAttribute("data-src");
        if (src === "frame") capture(function (img) { setCover(img) });
        else if (src === "file") pickFile(setCover);
        else loadImage(H.pictureUrl()).then(setCover).catch(function () { toast("The mission’s picture could not be read") });
      });
    });
    host.querySelectorAll("[data-add]").forEach(function (b) {
      b.addEventListener("click", function () {
        collect();
        var slot = b.parentNode;
        slot.insertAdjacentHTML("beforeend", '<div class="cmx-slotmenu"><button type="button" data-s="frame">' + ic("camera") + 'Frame a shot</button>' +
          '<button type="button" data-s="file">' + ic("upload") + 'A file…</button><button type="button" data-s="no">' + ic("x") + 'Cancel</button></div>');
        slot.querySelectorAll("[data-s]").forEach(function (x) {
          x.addEventListener("click", function (e) {
            e.stopPropagation();
            var w = x.getAttribute("data-s");
            slot.querySelector(".cmx-slotmenu").remove();
            if (w === "frame") capture(addShot); else if (w === "file") pickFile(addShot);
          });
        });
      });
    });
    host.querySelectorAll("[data-rm]").forEach(function (b) {
      b.addEventListener("click", function () { collect(); F.shots.splice(+b.getAttribute("data-rm"), 1); keep(); wizard(body, W) });
    });
    $("wz-next").addEventListener("click", function () { if (F.cover) step(3) });
  } else if (s === "credits") {
    var line = W.pre.lineage || [], me = ST.profile ? ST.profile.handle : "you";
    host.innerHTML = head("Credits", "Who made it, and what others may do with it.") +
      (line.length ? '<div class="cmx-field"><div class="lab">The line it carries</div><ol class="cmx-timeline" style="margin-top:6px">' + line.map(function (x) {
          return '<li><b>' + esc(x.name) + '</b><small>by @' + esc((x.author && x.author.handle) || "?") + '</small></li>' }).join("") +
          '<li class="here"><b>' + esc(F.name) + '</b><small>by @' + esc(me) + ' (you)</small></li></ol></div>' : '') +
      field("wz-co", "Made with (their usernames, comma between)", F.coauthors, { icon: "users", ph: "@friend, @teammate", hint: "They show on its page next to you." }) +
      '<label class="cmx-switch"><input type="checkbox" id="wz-rmx"' + (F.allow_remix ? ' checked' : '') + '><span><b>Remixes allowed</b><small>Others may share changed copies of it. Each one credits you.</small></span></label>' +
      field("wz-notes", F.mode === "update" ? "What is new in this version (needed)" : "Notes on this version (optional)", F.notes, { area: true, rows: 4, max: 1000,
        ph: F.mode === "update" ? "Fewer guards at the gate, a new objective, the alarm fixed…" : "Anything players should know" }) +
      foot("Next");
    bindNav();
    $("wz-next").addEventListener("click", function () {
      collect();
      if (F.mode === "update" && !F.notes.trim()) { $("wz-notes").focus(); toast("Say what is new in this version"); return }
      step(4);
    });
  } else if (s === "review") {
    host.innerHTML = head(F.mode === "update" ? "Ready to update" : "Ready to share", "This is what others will see. Nothing goes up until you say so.") +
      '<div class="cmx-review"><div>' + previewCard() + '</div><div>' +
        '<div class="cmx-over" style="margin-bottom:8px">' + ic("map") + esc(H.levelName(cur.base.level)) + '<span class="sep">/</span>' + diffPill(F.difficulty) +
          (F.mode === "update" ? '<span class="sep">/</span>version ' + (((W.published && W.published.version) || 1) + 1) : '') + '</div>' +
        '<h2 style="font:600 30px Barlow Condensed,sans-serif;margin:0 0 4px">' + esc(F.name) + '</h2><p style="margin:0 0 16px;color:var(--muted)">' + esc(F.summary) + '</p>' +
        '<ul class="cmx-goes">' +
          '<li>' + ic("check") + '<span>The mission’s plan: everything you placed and set, for anyone to look at and pull</span></li>' +
          '<li>' + ic("check") + '<span>The cover' + (F.shots.length ? ' and ' + plural(F.shots.length, "screenshot") : '') + (F.with_picture && W.pre.picture ? ', and its picture' : '') + '</span></li>' +
          '<li>' + ic("check") + '<span>' + plural(W.info.objectives.length, "objective") + ' and its facts, as the studio counted them</span></li>' +
          '<li class="no">' + ic("x") + '<span>Not your AI designer chats, its history, or any of the game’s files</span></li></ul>' +
        '<label class="cmx-check"><input type="checkbox" id="wz-agree"><span>I made this mission, or it credits who did; it has none of the game’s files in it, and nothing hurtful (the <button type="button" class="cmx-link" id="wz-rules">rules</button>).</span></label>' +
        '<div class="cmx-alert" id="wz-err" hidden></div>' +
      '</div></div>' + foot(F.mode === "update" ? "Publish the update" : "Share it", false, "upload");
    bindNav();
    $("wz-rules").addEventListener("click", rulesDialog);
    $("wz-agree").addEventListener("change", function () { $("wz-next").disabled = !this.checked });
    $("wz-next").addEventListener("click", function () { publish(this) });
  }

  function publish(btn) {
    busy(btn, true, "Sending…");
    var form = {
      mode: F.mode, name: F.name, summary: F.summary, description: F.description, difficulty: F.difficulty, tags: F.tags,
      play_minutes: F.play_minutes ? +F.play_minutes : null, video_url: F.video_url || null, allow_remix: F.allow_remix,
      coauthors: String(F.coauthors || "").split(/[,\s]+/).map(function (h) { return h.replace(/^@/, "").trim() }).filter(Boolean),
      notes: F.notes, objectives: W.info.objectives, facts: W.info.facts, cover: F.cover, thumb: F.thumb, shots: F.shots,
      with_picture: F.with_picture
    };
    H.check().then(function () {
      return api("POST", "publish", { mission: cur.id, form: form });
    }).then(function (r) {
      try { localStorage.removeItem(draftKey(cur.id)) } catch (e) {}
      H.communityPublished(r);
      LIST.items = []; LIST.loaded = false; STATS = null;
      body.querySelectorAll(".cmx-steps li").forEach(function (li) { li.className = "done"; li.querySelector(".sn").innerHTML = ic("check") });
      host.innerHTML = '<div class="cmx-done"><div class="cmx-stamp">' + (F.mode === "update" ? "Updated" : "Shared") + '</div>' +
        '<h2>“' + esc(r.name) + '” is in the community' + (F.mode === "update" ? ', version ' + r.version : '') + '</h2>' +
        '<p>Others can find it, look at it, vote, comment and pull it now.</p>' +
        '<div class="row"><button class="cmx-btn" id="wz-close">' + ic("back") + 'Back to the studio</button><button class="cmx-btn primary big" id="wz-see">' + ic("eye") + 'See its page</button></div></div>';
      $("wz-close").addEventListener("click", function () { BACK = []; VIEW = { kind: "discover" }; hide() });
      $("wz-see").addEventListener("click", function () { BACK = [{ kind: "discover" }]; VIEW = { kind: "mission", id: r.id }; show() });
    }).catch(function (e) {
      busy(btn, false);
      var el = $("wz-err"); if (el) { el.hidden = false; el.innerHTML = ic("warn") + '<span>' + esc(e.message) + '</span>' }
    });
  }
}

// ------------------------------------------------------------------ reports (moderators)
function showReports(body) {
  body.innerHTML = '<section class="cmx-hero compact"><div><div class="cmx-over">' + ic("shieldCheck") + 'Moderators</div><h1>Reports</h1></div></section><div id="cm-reps"><div class="cmx-spin"></div></div>';
  call("mod_reports", {}).then(function (r) {
    var items = r.items || [], host = $("cm-reps");
    host.innerHTML = items.length ? '<ul class="cmx-reports">' + items.map(function (x) {
      var w = x.what || {};
      var what = x.type === "mission" ? '<button type="button" class="cmx-link" data-mission="' + esc(x.target) + '">' + esc(w.name || "a mission") + '</button>' :
        x.type === "comment" ? '“' + esc((w.body || "").slice(0, 160)) + '”' : (w.handle ? '<button type="button" class="cmx-link" data-profile="' + esc(w.handle) + '">@' + esc(w.handle) + '</button>' : "someone");
      return '<li data-r="' + esc(x.id) + '"><div class="cmx-over" style="margin-bottom:6px">' + ic("report") + esc(x.reason) + '<span class="sep">/</span>' + esc(x.type) + '</div>' +
        '<div>' + what + ' <small style="color:var(--faint)">reported by @' + esc(x.reporter ? x.reporter.handle : "?") + ', ' + esc(when(x.created_at)) + '</small></div>' +
        (x.note ? '<p class="cmx-note" style="margin-top:6px">' + ic("comment") + '<span>' + esc(x.note) + '</span></p>' : '') +
        '<div class="row">' + (x.type === "mission" ? '<button class="cmx-btn" data-act="hide">' + ic("eyeOff") + 'Hide the mission</button>' : '') +
        (x.type === "comment" ? '<button class="cmx-btn" data-act="remove_comment">' + ic("trash") + 'Remove the comment</button>' : '') +
        '<button class="cmx-btn danger" data-act="ban">' + ic("x") + 'Ban its author</button><button class="cmx-btn ghost" data-act="dismiss">Dismiss</button></div></li>';
    }).join("") + '</ul>' : '<div class="cmx-empty">' + radar() + '<b>All quiet</b><p>No open reports.</p></div>';
    host.querySelectorAll("[data-act]").forEach(function (b) {
      b.addEventListener("click", function () {
        call("mod_act", { report: b.closest("[data-r]").getAttribute("data-r"), action: b.getAttribute("data-act") })
          .then(function () { toast("Done"); showReports(body) }).catch(function (e) { toast(e.message) });
      });
    });
  }).catch(function (e) { $("cm-reps").innerHTML = '<div class="cmx-empty"><b>' + esc(e.message) + '</b></div>' });
}

// ------------------------------------------------------------------ the library's "update available"
function refreshUpdates() {
  if (!ST.configured) return Promise.resolve(UPDATES);
  return api("GET", "updates").then(function (r) { UPDATES = r.updates || {}; return UPDATES }).catch(function () { return UPDATES });
}

window.Community = {
  init: function (host) {
    H = host;
    refreshState().then(function (s) { if (s.configured) refreshUpdates() });
  },
  open: function (view) { open(view && view.kind === "list" ? { kind: "discover" } : view) },
  openMission: function (id) { open({ kind: "mission", id: id }) },
  hide: hide,
  isOpen: isOpen,
  state: function () { return ST },
  updates: function () { return UPDATES },
  refresh: refreshState,
  signIn: function () { open({ kind: "discover" }); go({ kind: "auth", step: "signin" }) },
  signOut: signOut,
  share: share,
  pull: function (meta) { pull({ id: meta.id, version: meta.version, name: meta.name }) },
  profile: function () { if (member()) open({ kind: "profile", handle: ST.profile.handle }); else window.Community.signIn() }
};
// the editor's side is there already: its script comes first
if (window.StudioCommunity) window.Community.init(window.StudioCommunity);
})();
