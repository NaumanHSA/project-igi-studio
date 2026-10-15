// The community: missions people share with each other. A page over the
// workspace (like the library): browse and search them, open one - its
// objectives, its pictures, who made it, votes and comments - look at its map
// and 3D view without taking it, pull it into the studio to change it, and
// share missions of your own with a wizard that walks through what others
// will see.
//
// Everything goes through the studio's server (api/community/..., see
// studio/server/community.py), which holds the account and talks to the
// community's database; the rules live there (cloud/migrations). Guests
// browse and look; pulling, sharing, voting and commenting need an account.
//
// The editor's side is window.StudioCommunity (plotter.html): the open
// mission, its objectives and facts, pictures of the map and the 3D view,
// the dialog sheet, opening a mission or a preview.
(function () {
"use strict";

var H = null;                         // the editor (window.StudioCommunity)
var ST = { configured: null, signed_in: false, profile: null, suggest: null };
var EL = null;                        // the page
var VIEW = null;                      // what the page shows: {kind: "list" | "mission" | "profile" | "mod", ...}
var BACK = [];                        // the views before it
var LIST = { q: "", sort: "new", level: "", difficulty: "", tag: "", remixes: "", items: [], next: null, busy: false, err: null };
var UPDATES = {};                     // mission here -> newer version there
var TAGS = ["stealth", "assault", "sniper", "rescue", "sabotage", "escape", "defence", "story", "timed", "hardcore", "beginner", "short"];
var SORTS = [["new", "Newest"], ["top", "Top"], ["week", "Top this week"], ["month", "Top this month"], ["pulled", "Most pulled"]];

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
function avatar(p, cls) {
  var src = avatarSrc(p), n = (p && (p.name || p.handle) || "?").trim();
  return src ? '<img class="cm-av ' + (cls || "") + '" src="' + esc(src) + '" alt="" loading="lazy">'
    : '<span class="cm-av cm-av-i ' + (cls || "") + '" aria-hidden="true">' + esc(n.charAt(0).toUpperCase()) + '</span>';
}
function who(p) {
  if (!p) return '<span class="cm-who gone">someone who left</span>';
  return '<button type="button" class="cm-who" data-profile="' + esc(p.handle) + '">' + avatar(p) +
    '<span>' + esc(p.name || p.handle) + ' <i>@' + esc(p.handle) + '</i></span></button>';
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
  signIn(why, then);
}

// ------------------------------------------------------------------ the page
function build() {
  if (EL) return;
  EL = document.createElement("div");
  EL.className = "start community";
  EL.id = "community";
  EL.hidden = true;
  EL.innerHTML =
    '<div class="lib cm">' +
      '<div class="cm-head">' +
        '<button class="btn ghost cm-back" id="cm-back" hidden aria-label="Back">&larr; Back</button>' +
        '<div class="cm-title"><h1>Community</h1><p class="sub" id="cm-sub">Missions people made with the studio, to play and to change.</p></div>' +
        '<div class="cm-acts"><span id="cm-account"></span>' +
          '<button class="btn primary" id="cm-share">Share a mission</button>' +
          '<button class="btn" id="cm-close" title="Back to the studio (Esc)">Close</button></div>' +
      '</div>' +
      '<div id="cm-body"></div>' +
    '</div>';
  document.body.appendChild(EL);
  $("cm-close").addEventListener("click", hide);
  $("cm-back").addEventListener("click", back);
  $("cm-share").addEventListener("click", function () { share() });
  EL.addEventListener("click", function (e) {
    var t = e.target.closest("[data-profile]");
    if (t) { e.preventDefault(); go({ kind: "profile", handle: t.getAttribute("data-profile") }); return }
    t = e.target.closest("[data-mission]");
    if (t) { e.preventDefault(); go({ kind: "mission", id: t.getAttribute("data-mission") }); return }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || !isOpen()) return;
    var sh = document.getElementById("sheet");
    if (sh && !sh.hidden) return;
    if (BACK.length) back(); else hide();
  });
}
function isOpen() { return !!(EL && !EL.hidden) }

function open(view) {
  build();
  var lib = document.getElementById("start");
  if (lib) lib.hidden = true;
  EL.hidden = false;
  BACK = [];
  VIEW = view || VIEW || { kind: "list" };
  // each time it opens, what is new: from the first page again
  LIST.items = []; LIST.next = null; LIST.err = null; LIST.loaded = false;
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
  EL.scrollTop = 0;
}
function back() {
  VIEW = BACK.pop() || { kind: "list" };
  show();
}

function paintAccount() {
  if (!EL) return;
  var a = $("cm-account");
  if (!ST.configured) { a.innerHTML = ""; return }
  if (member()) {
    a.innerHTML = '<button class="btn cm-me" id="cm-me" title="Your profile">' + avatar(ST.profile) + '<span>@' + esc(ST.profile.handle) + '</span></button>';
    $("cm-me").addEventListener("click", function () { go({ kind: "profile", handle: ST.profile.handle }) });
  } else {
    a.innerHTML = '<button class="btn" id="cm-signin">' + (ST.signed_in ? "Choose your name" : "Sign in") + '</button>';
    $("cm-signin").addEventListener("click", function () { signIn(null, function () { show() }) });
  }
  $("cm-share").hidden = !ST.configured;
}

function show() {
  if (!EL || EL.hidden) return;
  $("cm-back").hidden = !BACK.length;
  paintAccount();
  var body = $("cm-body");
  if (ST.configured === false) {
    body.innerHTML = '<div class="shelf-empty cm-empty"><p><b>The community is not open yet.</b></p>' +
      '<p class="hint">Sharing missions with other players comes with an update of the studio.</p></div>';
    return;
  }
  if (!VIEW || VIEW.kind === "list") return showList(body);
  if (VIEW.kind === "mission") return showMission(body, VIEW.id);
  if (VIEW.kind === "profile") return showProfile(body, VIEW.handle);
  if (VIEW.kind === "mod") return showReports(body);
}

// ------------------------------------------------------------------ the list
function showList(body) {
  $("cm-sub").textContent = "Missions people made with the studio, to play and to change.";
  var lv = '<option value="">Any level</option>';
  for (var i = 1; i <= 14; i++) lv += '<option value="' + i + '"' + (String(LIST.level) === String(i) ? " selected" : "") + '>' + i + ' · ' + esc(H.levelName(i)) + '</option>';
  body.innerHTML =
    '<div class="cm-tools">' +
      '<input type="search" id="cm-q" placeholder="Search names, objectives, people…" value="' + esc(LIST.q) + '" aria-label="Search the community">' +
      '<select id="cm-sort" aria-label="Order">' + SORTS.map(function (s) {
        return '<option value="' + s[0] + '"' + (LIST.sort === s[0] ? " selected" : "") + '>' + s[1] + '</option>' }).join("") +
        (LIST.q ? '<option value="relevance"' + (LIST.sort === "relevance" ? " selected" : "") + '>Best match</option>' : '') + '</select>' +
      '<select id="cm-level" aria-label="Base level">' + lv + '</select>' +
      '<select id="cm-diff" aria-label="Difficulty"><option value="">Any difficulty</option>' + ["easy", "normal", "hard"].map(function (d) {
        return '<option' + (LIST.difficulty === d ? " selected" : "") + '>' + d + '</option>' }).join("") + '</select>' +
      '<select id="cm-tag" aria-label="Style"><option value="">Any style</option>' + TAGS.map(function (t) {
        return '<option' + (LIST.tag === t ? " selected" : "") + '>' + t + '</option>' }).join("") + '</select>' +
      '<select id="cm-rmx" aria-label="Originals or changed copies"><option value="">Originals and remixes</option>' +
        '<option value="none"' + (LIST.remixes === "none" ? " selected" : "") + '>Originals only</option>' +
        '<option value="only"' + (LIST.remixes === "only" ? " selected" : "") + '>Remixes only</option></select>' +
      (ST.profile && /mod|admin/.test(ST.profile.role || "") ? '<button class="btn" id="cm-mod">Reports</button>' : '') +
    '</div>' +
    '<div class="mgrid cm-grid" id="cm-grid"></div>' +
    '<div class="cm-more" id="cm-more"></div>';
  var t = null;
  $("cm-q").addEventListener("input", function () {
    clearTimeout(t);
    var v = this.value;
    t = setTimeout(function () {
      var had = !!LIST.q;
      LIST.q = v.trim();
      if (LIST.q && !had) LIST.sort = "relevance";
      if (!LIST.q && LIST.sort === "relevance") LIST.sort = "new";
      reload(true);
    }, 300);
  });
  [["cm-sort", "sort"], ["cm-level", "level"], ["cm-diff", "difficulty"], ["cm-tag", "tag"], ["cm-rmx", "remixes"]].forEach(function (f) {
    $(f[0]).addEventListener("change", function () { LIST[f[1]] = this.value; reload(false) });
  });
  if ($("cm-mod")) $("cm-mod").addEventListener("click", function () { go({ kind: "mod" }) });
  if (LIST.loaded) paintCards(); else more();
}
// from the first page again: typing keeps the toolbar (and its focus), a filter redraws it
function reload(typing) {
  LIST.items = []; LIST.next = null; LIST.err = null; LIST.loaded = false;
  if (typing) { paintCards(); more() } else showList($("cm-body"));
}
function more() {
  if (LIST.busy) return;
  LIST.busy = true;
  var p = { q: LIST.q, sort: LIST.sort, level: LIST.level, difficulty: LIST.difficulty, tag: LIST.tag, remixes: LIST.remixes,
            cursor: LIST.items.length ? LIST.next : null };
  var ask = JSON.stringify(p);
  LIST.asking = ask;
  paintMore();
  call("list_missions", p).then(function (r) {
    if (LIST.asking !== ask) return;           // the filters changed meanwhile
    LIST.busy = false; LIST.loaded = true;
    LIST.items = LIST.items.concat(r.items || []);
    LIST.next = r.next;
    paintCards();
  }).catch(function (e) {
    if (LIST.asking !== ask) return;
    LIST.busy = false; LIST.err = e;
    paintCards();
  });
}
function paintCards() {
  var g = $("cm-grid");
  if (!g) return;
  g.innerHTML = LIST.items.map(cardHtml).join("");
  if (LIST.loaded && !LIST.items.length && !LIST.err && !LIST.busy) {
    var filtered = LIST.q || LIST.level || LIST.tag || LIST.difficulty || LIST.remixes;
    $("cm-more").innerHTML = '<div class="shelf-empty cm-empty"><p><b>' + (filtered ? "Nothing matches." : "No missions here yet.") + '</b></p>' +
      '<p class="hint">' + (filtered ? "Try other words, or fewer filters." : "Be the first: open a mission of yours and share it.") + '</p></div>';
    return;
  }
  paintMore();
}
function paintMore() {
  var m = $("cm-more");
  if (!m) return;
  if (LIST.err) {
    m.innerHTML = '<div class="shelf-empty cm-empty"><p><b>' + esc(LIST.err.message) + '</b></p><button class="btn" id="cm-retry">Try again</button></div>';
    $("cm-retry").addEventListener("click", function () { LIST.err = null; more() });
    return;
  }
  if (LIST.busy) { m.innerHTML = '<p class="hint cm-loading">Loading…</p>'; return }
  if (LIST.next) {
    m.innerHTML = '<button class="btn" id="cm-next">More</button>';
    $("cm-next").addEventListener("click", more);
    // the next page comes as you scroll near the end
    if (window.IntersectionObserver) {
      var io = new IntersectionObserver(function (es) { if (es[0].isIntersecting) { io.disconnect(); more() } }, { root: EL, rootMargin: "300px" });
      io.observe($("cm-next"));
    }
    return;
  }
  m.innerHTML = "";
}
function badges(c) {
  var out = [];
  if (c.status === "unlisted") out.push('<span class="cm-badge">Unlisted</span>');
  if (c.status === "hidden") out.push('<span class="cm-badge bad">Hidden</span>');
  if (c.remix_of) out.push('<span class="cm-badge">Remix</span>');
  return out.join("");
}
function cardHtml(c) {
  var f = c.facts || {};
  return '<article class="mcard cm-card">' +
    '<button type="button" class="mc-open" data-mission="' + esc(c.id) + '">' +
      '<span class="mc-img cm-img" style="background-image:url(' + esc(media(c.thumb)) + ')">' +
        '<span class="mc-tag">' + esc(H.levelName(c.level)) + (c.kind === "empty" ? " · empty map" : "") + '</span>' +
        '<span class="cm-badges">' + badges(c) + '</span></span>' +
      '<span class="mc-txt"><b>' + esc(c.name) + '</b>' +
        '<span class="cm-sum">' + esc(c.summary) + '</span>' +
        '<span class="cm-by">' + avatar(c.author, "sm") + esc(c.author ? "@" + c.author.handle : "someone who left") + '</span>' +
        '<span class="mc-meta cm-stats" title="Score, comments, pulls and objectives">' +
          '<span class="' + (c.score > 0 ? "up" : c.score < 0 ? "down" : "") + '">&#9650; ' + c.score + '</span>' +
          '<span>' + plural(c.comments, "comment") + '</span><span>' + plural(c.pulls, "pull") + '</span>' +
          '<span>' + plural(c.objectives, "objective") + '</span>' +
          (f.guards ? '<span>' + plural(f.guards, "guard") + '</span>' : '') +
        '</span></span>' +
    '</button></article>';
}

// ------------------------------------------------------------------ a mission
function showMission(body, id) {
  body.innerHTML = '<p class="hint cm-loading">Loading…</p>';
  call("get_mission", { id: id }).then(function (m) {
    if (!VIEW || VIEW.id !== id) return;
    VIEW.m = m;
    paintMission(body, m);
  }).catch(function (e) {
    body.innerHTML = '<div class="shelf-empty cm-empty"><p><b>' + esc(e.message) + '</b></p></div>';
  });
}
function factsRows(m) {
  var f = m.facts || {}, rows = [];
  rows.push(["Base", esc(H.levelName(m.level)) + (m.kind === "empty" ? " (its empty map)" : " (a copy)")]);
  rows.push(["Difficulty", esc(m.difficulty)]);
  if (m.play_minutes) rows.push(["Play time", "about " + m.play_minutes + " min"]);
  if (f.time_limit) rows.push(["Time limit", Math.floor(f.time_limit / 60) + ":" + String(f.time_limit % 60).padStart(2, "0")]);
  if (f.weather) rows.push(["Weather", esc(f.weather)]);
  if (f.music) rows.push(["Music", esc(f.music)]);
  if (f.fail_on_alarm) rows.push(["Alarm", "fails the mission"]);
  var counts = [["guards", "guard"], ["cameras", "camera"], ["alarms", "alarm"], ["pickups", "pickup"], ["cutscenes", "cutscene"],
                ["vehicles", "moving vehicle"], ["events", "event"], ["placements", "thing placed", "things placed"]];
  var c = counts.filter(function (k) { return f[k[0]] }).map(function (k) { return plural(f[k[0]], k[1], k[2]) });
  if (c.length) rows.push(["In it", c.join(", ")]);
  if (m.tags && m.tags.length) rows.push(["Style", m.tags.map(esc).join(", ")]);
  return '<table class="cm-facts">' + rows.map(function (r) { return '<tr><th>' + r[0] + '</th><td>' + r[1] + '</td></tr>' }).join("") + '</table>';
}
function lineageHtml(m) {
  var line = (m.lineage || []);
  if (!line.length) return '';
  return '<div class="cm-box"><div class="lbl">Where it came from</div><ol class="cm-line">' + line.map(function (x) {
    var a = x.author || {};
    return '<li>' + (x.id ? '<button type="button" class="cm-link" data-mission="' + esc(x.id) + '">' + esc(x.name) + '</button>' : '<span>' + esc(x.name) + '</span>') +
      ' <span class="hint">v' + esc(x.version || 1) + ' by @' + esc(a.handle || "?") + '</span></li>';
  }).join("") + '<li class="cm-here"><b>' + esc(m.name) + '</b> <span class="hint">by @' + esc(m.author ? m.author.handle : "?") + '</span></li></ol></div>';
}
function paintMission(body, m) {
  $("cm-sub").textContent = "A mission from the community";
  var shots = [m.cover].concat(m.shots || []);
  var mine = m.mine, local = updatesFor(m.id);
  var pullLabel = m.my_pull ? (m.my_pull < m.version ? "Pull version " + m.version : "Pull it again") : "Pull to my studio";
  body.innerHTML =
    '<div class="cm-mission">' +
      '<div class="cm-main">' +
        '<div class="cm-cover" id="cm-cover" style="background-image:url(' + esc(media(m.cover)) + ')"></div>' +
        (shots.length > 1 ? '<div class="cm-shots">' + shots.map(function (s, i) {
          return '<button type="button" class="cm-shot' + (i ? '' : ' on') + '" data-shot="' + esc(s) + '" style="background-image:url(' + esc(media(s)) + ')" aria-label="Picture ' + (i + 1) + '"></button>' }).join("") + '</div>' : '') +
        '<h2 class="cm-name">' + esc(m.name) + ' <span class="cm-ver">v' + m.version + '</span>' + badges(m) + '</h2>' +
        '<p class="cm-summary">' + esc(m.summary) + '</p>' +
        '<div class="cm-byline">' + who(m.author) + '<span class="hint">shared ' + esc(when(m.created_at)) +
          (m.version > 1 ? ' · updated ' + esc(when(m.updated_at)) : '') + '</span>' +
          ((m.coauthors || []).length ? '<span class="hint">with ' + m.coauthors.map(function (p) { return '<button type="button" class="cm-link" data-profile="' + esc(p.handle) + '">@' + esc(p.handle) + '</button>' }).join(", ") + '</span>' : '') +
        '</div>' +
        (m.description ? '<div class="cm-desc">' + esc(m.description) + '</div>' : '') +
        '<div class="lbl cm-h">Objectives</div><ol class="cm-objs">' + (m.objectives || []).map(function (o) {
          return '<li><span class="cm-ok">' + esc(o.kind || "") + '</span>' + esc(o.text) + '</li>' }).join("") + '</ol>' +
        '<div class="lbl cm-h">About it</div>' + factsRows(m) +
        (m.video_url ? '<p class="hint">Video: <span class="mono">' + esc(m.video_url) + '</span></p>' : '') +
        '<div class="lbl cm-h">Versions</div><ul class="cm-vers">' + (m.versions || []).map(function (v) {
          return '<li><b>v' + v.version + '</b> <span class="hint">' + esc(when(v.created_at)) + '</span>' + (v.notes ? '<div>' + esc(v.notes) + '</div>' : '') + '</li>' }).join("") + '</ul>' +
        '<div class="lbl cm-h" id="cm-ch">Comments <span class="count">' + m.comments + '</span></div><div id="cm-comments"></div>' +
      '</div>' +
      '<aside class="cm-side">' +
        '<div class="cm-box cm-do">' +
          '<button class="btn primary" id="cm-pull">' + esc(pullLabel) + '</button>' +
          (m.my_pull ? '<p class="hint">You pulled version ' + m.my_pull + (local ? '; version ' + m.version + ' is out' : '') + '.</p>' : '') +
          '<div class="cm-look"><button class="btn" id="cm-map">View the map</button><button class="btn" id="cm-3d">View in 3D</button></div>' +
          '<p class="hint">Looking changes nothing: to change it, pull it into your studio' + (m.allow_remix ? '' : '. Its author does not allow changed copies to be shared') + '.</p>' +
        '</div>' +
        '<div class="cm-box cm-vote" id="cm-vote"></div>' +
        '<div class="cm-box cm-nums"><span><b>' + m.pulls + '</b> pulls</span><span><b>' + m.comments + '</b> comments</span>' +
          '<span><b>' + m.remixes + '</b> remixes</span></div>' +
        lineageHtml(m) +
        (m.remixes ? '<div class="cm-box"><div class="lbl">Remixes</div><div id="cm-tree"><button class="btn" id="cm-tree-go">Show the ' + plural(m.remixes, "remix", "remixes") + '</button></div></div>' : '') +
        (mine ? '<div class="cm-box"><div class="lbl">Yours</div><div class="cm-own">' +
          '<button class="btn" id="cm-edit">Edit the details</button>' +
          (m.status === "hidden" ? '<p class="hint">A moderator hid it.</p>' :
            '<button class="btn" id="cm-list">' + (m.status === "unlisted" ? "List it again" : "Unlist it") + '</button>') +
          '<button class="btn danger" id="cm-del">Delete it</button>' +
          '<p class="hint">A new version comes from the studio: open the mission there, then Share, Publish an update.</p></div></div>' : '') +
        (m.can_moderate ? '<div class="cm-box"><div class="lbl">Moderator</div><button class="btn" id="cm-hide">' + (m.status === "hidden" ? "Show it again" : "Hide it") + '</button>' +
          (mine ? '' : '<button class="btn danger" id="cm-mdel">Delete it</button>') + '</div>' : '') +
        (!mine ? '<button class="btn ghost cm-report" id="cm-report">Report this mission</button>' : '') +
      '</aside>' +
    '</div>';
  body.querySelectorAll("[data-shot]").forEach(function (b) {
    b.addEventListener("click", function () {
      $("cm-cover").style.backgroundImage = "url(" + media(b.getAttribute("data-shot")) + ")";
      body.querySelectorAll(".cm-shot").forEach(function (x) { x.classList.toggle("on", x === b) });
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
  if ($("cm-report")) $("cm-report").addEventListener("click", function () { report("mission", m.id, m.name) });
  comments(m);
}
function updatesFor(cid) {
  for (var k in UPDATES) if (UPDATES[k].id === cid) return UPDATES[k];
  return null;
}
function paintVote(m) {
  var v = $("cm-vote");
  if (!v) return;
  v.innerHTML = '<button type="button" class="cm-vb up' + (m.my_vote === 1 ? ' on' : '') + '" id="cm-up" aria-label="Vote up" title="' + (m.mine ? "Your own mission" : "A good one") + '">&#9650;</button>' +
    '<span class="cm-score"><b>' + (m.up - m.down) + '</b><i>' + m.up + ' up · ' + m.down + ' down</i></span>' +
    '<button type="button" class="cm-vb down' + (m.my_vote === -1 ? ' on' : '') + '" id="cm-down" aria-label="Vote down" title="' + (m.mine ? "Your own mission" : "Not for me") + '">&#9660;</button>';
  function vote(val) {
    if (m.mine) { toast("You cannot vote for your own mission"); return }
    needAccount("vote", function () {
      var to = m.my_vote === val ? 0 : val;
      call("set_vote", { id: m.id, value: to }).then(function (r) {
        m.up = r.up; m.down = r.down; m.my_vote = r.my_vote; paintVote(m);
        LIST.items.forEach(function (c) { if (c.id === m.id) { c.up = r.up; c.down = r.down; c.score = r.score } });
      }).catch(function (e) { toast(e.message) });
    });
  }
  $("cm-up").addEventListener("click", function () { vote(1) });
  $("cm-down").addEventListener("click", function () { vote(-1) });
}
function tree(m) {
  var box = $("cm-tree");
  box.innerHTML = '<p class="hint">Loading…</p>';
  call("remixes", { id: m.id }).then(function (r) {
    var kids = {};
    (r.items || []).forEach(function (x) { (kids[x.parent] = kids[x.parent] || []).push(x) });
    function list(pid) {
      var k = kids[pid] || [];
      return k.length ? '<ul class="cm-tree">' + k.map(function (x) {
        return '<li><button type="button" class="cm-link" data-mission="' + esc(x.id) + '">' + esc(x.name) + '</button> ' +
          '<span class="hint">@' + esc(x.author ? x.author.handle : "?") + ' · &#9650; ' + x.score + '</span>' + list(x.id) + '</li>' }).join("") + '</ul>' : '';
    }
    box.innerHTML = list(m.id) || '<p class="hint">None of them can be seen now.</p>';
  }).catch(function (e) { box.innerHTML = '<p class="hint">' + esc(e.message) + '</p>' });
}
function pull(m) {
  needAccount("pull a mission into your studio", function () {
    var b = $("cm-pull");
    if (b) { b.disabled = true; b.textContent = "Pulling…" }
    api("POST", "pull", { id: m.id, version: m.version }).then(function (r) {
      toast("“" + m.name + "” is a mission of yours now");
      hide();
      H.openMission(r.mission.id);
      refreshUpdates();
    }).catch(function (e) {
      toast(e.message);
      if (b) { b.disabled = false; b.textContent = "Pull to my studio" }
    });
  });
}
function preview(m, in3d) {
  var b = in3d ? $("cm-3d") : $("cm-map");
  if (b) { b.disabled = true; b.textContent = "Opening…" }
  api("GET", "plan/" + m.id + "?v=" + m.version).then(function (r) {
    hide();
    H.preview(r.mission, { id: m.id, version: m.version, name: m.name, author: m.author, allow_remix: m.allow_remix }, in3d);
  }).catch(function (e) {
    toast(e.message);
    if (b) { b.disabled = false; b.textContent = in3d ? "View in 3D" : "View the map" }
  });
}
function deleteMission(m) {
  H.sheet("Delete “" + m.name + "”?",
    '<p>It goes from the community for good: its versions, votes and comments with it. Missions others made from it keep their line, without a link back.</p>' +
    '<p class="hint">The mission in your studio stays as it is. Its name is free again at once.</p>' +
    '<div class="ck-foot"><button class="btn" id="cmd-no">Keep it</button><button class="btn danger" id="cmd-yes">Delete it</button></div>');
  $("cmd-no").addEventListener("click", H.closeSheet);
  $("cmd-yes").addEventListener("click", function () {
    this.disabled = true;
    call("delete_mission", { id: m.id }).then(function () {
      H.closeSheet(); toast("“" + m.name + "” is gone from the community");
      LIST.items = LIST.items.filter(function (c) { return c.id !== m.id });
      back();
    }).catch(function (e) { toast(e.message); $("cmd-yes").disabled = false });
  });
}
function editDetails(m) {
  H.sheet("Edit “" + m.name + "”",
    '<label class="cm-f"><span>Name</span><input id="ced-name" maxlength="60" value="' + esc(m.name) + '"><i id="ced-name-ok"></i></label>' +
    '<label class="cm-f"><span>Summary</span><input id="ced-sum" maxlength="140" value="' + esc(m.summary) + '"></label>' +
    '<label class="cm-f"><span>Description</span><textarea id="ced-desc" rows="6" maxlength="6000">' + esc(m.description) + '</textarea></label>' +
    '<div class="cm-f"><span>Difficulty</span>' + seg("ced-diff", ["easy", "normal", "hard"], m.difficulty) + '</div>' +
    '<div class="cm-f"><span>Style</span>' + tagsHtml("ced-tags", m.tags || []) + '</div>' +
    '<label class="cm-f cm-check"><input type="checkbox" id="ced-rmx"' + (m.allow_remix ? " checked" : "") + '> Others may share changed copies of it</label>' +
    '<p class="note bad" id="ced-err" hidden></p>' +
    '<div class="ck-foot"><button class="btn" id="ced-no">Cancel</button><button class="btn primary" id="ced-ok">Save</button></div>');
  bindSeg("ced-diff"); bindTags("ced-tags");
  nameCheck($("ced-name"), $("ced-name-ok"), m.id);
  $("ced-no").addEventListener("click", H.closeSheet);
  $("ced-ok").addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    call("update_details", { id: m.id, name: $("ced-name").value, summary: $("ced-sum").value, description: $("ced-desc").value,
      difficulty: segValue("ced-diff"), tags: tagsValue("ced-tags"), allow_remix: $("ced-rmx").checked }).then(function () {
      H.closeSheet(); toast("Saved"); showMission($("cm-body"), m.id);
    }).catch(function (e) { $("ced-err").hidden = false; $("ced-err").textContent = e.message; btn.disabled = false });
  });
}

// ------------------------------------------------------------------ comments
function comments(m, cursor) {
  var host = $("cm-comments");
  if (!host) return;
  if (!cursor) host.innerHTML = '<div id="cm-c-new"></div><div id="cm-c-list"><p class="hint">Loading…</p></div><div id="cm-c-more"></div>';
  paintNewComment(m, null, $("cm-c-new"));
  call("list_comments", { id: m.id, cursor: cursor || null }).then(function (r) {
    var list = $("cm-c-list");
    if (!list) return;
    var h = (r.items || []).map(function (c) { return commentHtml(c, m) }).join("");
    if (!cursor) list.innerHTML = h || '<p class="hint">No comments yet.</p>';
    else list.insertAdjacentHTML("beforeend", h);
    bindComments(m, list);
    var more = $("cm-c-more");
    more.innerHTML = r.next ? '<button class="btn" id="cm-c-next">More comments</button>' : '';
    if (r.next) $("cm-c-next").addEventListener("click", function () { comments(m, r.next) });
  }).catch(function (e) { var l = $("cm-c-list"); if (l) l.innerHTML = '<p class="hint">' + esc(e.message) + '</p>' });
}
function commentHtml(c, m, reply) {
  return '<div class="cm-c' + (reply ? ' reply' : '') + (c.removed ? ' removed' : '') + '" data-c="' + esc(c.id) + '">' +
    '<div class="cm-c-h">' + (c.removed ? '<span class="hint">removed</span>' : who(c.author)) +
      (c.author && m.author && c.author.id === m.author.id && !c.removed ? '<span class="cm-badge">author</span>' : '') +
      '<span class="hint">' + esc(when(c.created_at)) + (c.edited_at ? ' · edited' : '') + '</span>' +
      '<span class="cm-c-acts">' +
        (!reply && !c.removed ? '<button type="button" class="cm-link" data-ca="reply">Reply</button>' : '') +
        (c.mine && !c.removed ? '<button type="button" class="cm-link" data-ca="edit">Edit</button>' : '') +
        (c.can_remove ? '<button type="button" class="cm-link" data-ca="del">Remove</button>' : '') +
        (!c.mine && !c.removed ? '<button type="button" class="cm-link" data-ca="report">Report</button>' : '') +
      '</span></div>' +
    (c.removed ? '' : '<div class="cm-c-b">' + esc(c.body) + '</div>') +
    (c.replies && c.replies.length ? '<div class="cm-replies">' + c.replies.map(function (x) { return commentHtml(x, m, true) }).join("") + '</div>' : '') +
    (reply ? '' : '<div class="cm-c-new"></div>') +
    '</div>';
}
function bindComments(m, root) {
  root.querySelectorAll("[data-ca]").forEach(function (b) {
    if (b.dataset.bound) return;
    b.dataset.bound = "1";
    b.addEventListener("click", function () {
      var el = b.closest(".cm-c"), id = el.getAttribute("data-c"), a = b.getAttribute("data-ca");
      if (a === "reply") return paintNewComment(m, id, el.querySelector(":scope > .cm-c-new"), true);
      if (a === "report") return needAccount("report it", function () { report("comment", id, "this comment") });
      if (a === "del") return call("delete_comment", { id: id }).then(function () { comments(m) }).catch(function (e) { toast(e.message) });
      if (a === "edit") {
        var bodyEl = el.querySelector(":scope > .cm-c-b"), old = bodyEl.textContent;
        bodyEl.innerHTML = '<textarea rows="3" maxlength="2000">' + esc(old) + '</textarea><div class="cm-c-row"><button class="btn" data-x="no">Cancel</button><button class="btn primary" data-x="ok">Save</button></div>';
        bodyEl.querySelector('[data-x="no"]').addEventListener("click", function () { bodyEl.textContent = old });
        bodyEl.querySelector('[data-x="ok"]').addEventListener("click", function () {
          call("edit_comment", { id: id, body: bodyEl.querySelector("textarea").value }).then(function () { comments(m) }).catch(function (e) { toast(e.message) });
        });
      }
    });
  });
}
function paintNewComment(m, parent, host, focus) {
  if (!host) return;
  if (!member()) {
    host.innerHTML = parent ? '' : '<p class="hint cm-c-sign"><button type="button" class="cm-link" id="cm-c-sign">Sign in</button> to comment.</p>';
    if (!parent) $("cm-c-sign").addEventListener("click", function () { signIn("comment", function () { comments(m) }) });
    if (parent) needAccount("reply", function () { comments(m) });
    return;
  }
  host.innerHTML = '<div class="cm-c-write"><textarea rows="' + (parent ? 2 : 3) + '" maxlength="2000" placeholder="' +
    (parent ? "Your reply" : "Say what you think of it, or how it played") + '"></textarea>' +
    '<div class="cm-c-row">' + (parent ? '<button class="btn" data-x="no">Cancel</button>' : '') + '<button class="btn primary" data-x="ok">' + (parent ? "Reply" : "Comment") + '</button></div></div>';
  var ta = host.querySelector("textarea");
  if (focus) ta.focus();
  if (parent) host.querySelector('[data-x="no"]').addEventListener("click", function () { host.innerHTML = "" });
  host.querySelector('[data-x="ok"]').addEventListener("click", function () {
    var b = this;
    if (!ta.value.trim()) { ta.focus(); return }
    b.disabled = true;
    call("add_comment", { id: m.id, parent: parent, body: ta.value }).then(function () {
      m.comments++;
      var ch = $("cm-ch"); if (ch) ch.querySelector(".count").textContent = m.comments;
      comments(m);
    }).catch(function (e) { toast(e.message); b.disabled = false });
  });
}
function report(type, target, what) {
  needAccount("report it", function () {
    H.sheet("Report " + what,
      '<p class="hint">Moderators look at every report. Say what is wrong.</p>' +
      '<div class="cm-f">' + seg("rp-why", ["spam", "offensive", "stolen", "broken", "other"], "") + '</div>' +
      '<label class="cm-f"><span>More (if it helps)</span><textarea id="rp-note" rows="3" maxlength="1000"></textarea></label>' +
      '<div class="ck-foot"><button class="btn" id="rp-no">Cancel</button><button class="btn primary" id="rp-ok">Report</button></div>');
    bindSeg("rp-why");
    $("rp-no").addEventListener("click", H.closeSheet);
    $("rp-ok").addEventListener("click", function () {
      if (!segValue("rp-why")) { toast("Say what is wrong with it"); return }
      call("report", { type: type, target: target, reason: segValue("rp-why"), note: $("rp-note").value }).then(function () {
        H.closeSheet(); toast("Reported: thank you");
      }).catch(function (e) { toast(e.message) });
    });
  });
}

// ------------------------------------------------------------------ people
function showProfile(body, handle) {
  body.innerHTML = '<p class="hint cm-loading">Loading…</p>';
  call("get_profile", { handle: handle }).then(function (r) {
    if (!VIEW || VIEW.handle !== handle) return;
    paintProfile(body, r);
  }).catch(function (e) { body.innerHTML = '<div class="shelf-empty cm-empty"><p><b>' + esc(e.message) + '</b></p></div>' });
}
function paintProfile(body, r) {
  var p = r.profile, s = r.stats || {}, items = (r.missions && r.missions.items) || [];
  $("cm-sub").textContent = r.mine ? "You, as the community sees you" : "Someone in the community";
  body.innerHTML =
    '<div class="cm-person">' + avatar(p, "lg") +
      '<div class="cm-p-t"><h2>' + esc(p.name) + (p.role ? ' <span class="cm-badge">' + esc(p.role) + '</span>' : '') + '</h2>' +
        '<div class="hint">@' + esc(p.handle) + ' · joined ' + esc(when(p.created_at)) + '</div>' +
        (p.bio ? '<p class="cm-bio">' + esc(p.bio) + '</p>' : '') +
        ((p.links || []).length ? '<div class="cm-links">' + p.links.map(function (l) { return '<span class="mono">' + esc(l) + '</span>' }).join("") + '</div>' : '') +
        '<div class="cm-nums"><span><b>' + (s.missions || 0) + '</b> missions</span><span><b>' + (s.score || 0) + '</b> score</span><span><b>' + (s.pulls || 0) + '</b> pulls</span></div>' +
      '</div>' +
      (r.mine ? '<div class="cm-p-acts"><button class="btn" id="cm-p-edit">Edit your profile</button><button class="btn" id="cm-p-out">Sign out</button>' +
        '<button class="btn ghost danger" id="cm-p-del">Delete your account…</button></div>' :
        (member() ? '<div class="cm-p-acts"><button class="btn ghost" id="cm-p-rep">Report</button></div>' : '')) +
    '</div>' +
    '<div class="shelf-head"><h2>' + (r.mine ? "Your missions" : "Missions") + '</h2><span class="count">' + items.length + (r.missions && r.missions.next ? "+" : "") + '</span>' +
      (r.mine ? '<span class="hint">Unlisted ones are shown only to you.</span>' : '') + '</div>' +
    (items.length ? '<div class="mgrid cm-grid">' + items.map(cardHtml).join("") + '</div>' :
      '<div class="shelf-empty cm-empty"><p>' + (r.mine ? "Nothing shared yet. Open a mission of yours, then Share, Share with the community." : "Nothing shared yet.") + '</p></div>');
  if ($("cm-p-edit")) $("cm-p-edit").addEventListener("click", function () { profileDialog(p, function () { show() }) });
  if ($("cm-p-out")) $("cm-p-out").addEventListener("click", function () {
    api("POST", "auth/signout", {}).then(function () { return refreshState() }).then(function () { toast("Signed out"); VIEW = { kind: "list" }; BACK = []; show() });
  });
  if ($("cm-p-del")) $("cm-p-del").addEventListener("click", deleteAccount);
  if ($("cm-p-rep")) $("cm-p-rep").addEventListener("click", function () { report("profile", p.id, "@" + p.handle) });
}
function deleteAccount() {
  H.sheet("Delete your community account?",
    '<p>Your profile, every mission you shared (with its votes and comments), your votes, your comments and your pulls go for good, and the account with them.</p>' +
    '<p class="hint">The missions in your studio stay. Missions others made from yours keep their line, without a link back.</p>' +
    '<label class="cm-f"><span>Type DELETE to confirm</span><input id="da-c" autocomplete="off"></label>' +
    '<div class="ck-foot"><button class="btn" id="da-no">Keep it</button><button class="btn danger" id="da-yes" disabled>Delete my account</button></div>');
  $("da-c").addEventListener("input", function () { $("da-yes").disabled = this.value.trim() !== "DELETE" });
  $("da-no").addEventListener("click", H.closeSheet);
  $("da-yes").addEventListener("click", function () {
    this.disabled = true;
    api("POST", "account/delete", {}).then(function () {
      H.closeSheet(); toast("Your account is deleted"); return refreshState();
    }).then(function () { VIEW = { kind: "list" }; BACK = []; LIST.items = []; show() })
      .catch(function (e) { toast(e.message); $("da-yes").disabled = false });
  });
}

// ------------------------------------------------------------------ reports (moderators)
function showReports(body) {
  $("cm-sub").textContent = "Reports: what people flagged";
  body.innerHTML = '<p class="hint cm-loading">Loading…</p>';
  call("mod_reports", {}).then(function (r) {
    var items = r.items || [];
    body.innerHTML = items.length ? '<ul class="cm-reports">' + items.map(function (x) {
      var w = x.what || {};
      var what = x.type === "mission" ? '<button type="button" class="cm-link" data-mission="' + esc(x.target) + '">' + esc(w.name || "a mission") + '</button>' :
        x.type === "comment" ? '“' + esc((w.body || "").slice(0, 160)) + '”' : (w.handle ? '<button type="button" class="cm-link" data-profile="' + esc(w.handle) + '">@' + esc(w.handle) + '</button>' : "someone");
      return '<li data-r="' + esc(x.id) + '"><div><b>' + esc(x.reason) + '</b> · ' + esc(x.type) + ': ' + what +
        ' <span class="hint">by @' + esc(x.reporter ? x.reporter.handle : "?") + ', ' + esc(when(x.created_at)) + '</span></div>' +
        (x.note ? '<div class="hint">' + esc(x.note) + '</div>' : '') +
        '<div class="cm-c-row">' + (x.type === "mission" ? '<button class="btn" data-act="hide">Hide the mission</button>' : '') +
        (x.type === "comment" ? '<button class="btn" data-act="remove_comment">Remove the comment</button>' : '') +
        '<button class="btn danger" data-act="ban">Ban its author</button><button class="btn" data-act="dismiss">Dismiss</button></div></li>';
    }).join("") + '</ul>' : '<div class="shelf-empty cm-empty"><p>No open reports.</p></div>';
    body.querySelectorAll("[data-act]").forEach(function (b) {
      b.addEventListener("click", function () {
        call("mod_act", { report: b.closest("[data-r]").getAttribute("data-r"), action: b.getAttribute("data-act") })
          .then(function () { toast("Done"); showReports(body) }).catch(function (e) { toast(e.message) });
      });
    });
  }).catch(function (e) { body.innerHTML = '<div class="shelf-empty cm-empty"><p><b>' + esc(e.message) + '</b></p></div>' });
}

// ------------------------------------------------------------------ small form parts
function seg(id, values, cur) {
  return '<div class="seg cm-seg" id="' + id + '">' + values.map(function (v) {
    return '<button type="button" class="btn' + (v === cur ? " on" : "") + '" data-v="' + esc(v) + '">' + esc(v) + '</button>' }).join("") + '</div>';
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
  return '<div class="cm-tags" id="' + id + '">' + TAGS.map(function (t) {
    return '<button type="button" class="cm-tag' + (cur.indexOf(t) >= 0 ? " on" : "") + '" data-t="' + t + '" aria-pressed="' + (cur.indexOf(t) >= 0) + '">' + t + '</button>' }).join("") + '</div>';
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
// a mission name as you type it: free in the community?
function nameCheck(input, out, except, onChange) {
  var t = null, n = 0;
  function check() {
    var v = input.value.trim(), k = ++n;
    if (onChange) onChange(v);
    if (v.length < 3) { out.textContent = "3 to 60 characters"; out.className = "bad"; return }
    out.textContent = "…"; out.className = "";
    call("name_free", { name: v, except: except || null }).then(function (r) {
      if (k !== n) return;
      out.textContent = r.free ? "Free" : "Taken: another mission has this name";
      out.className = r.free ? "good" : "bad";
    }).catch(function () { if (k === n) { out.textContent = ""; out.className = "" } });
  }
  input.addEventListener("input", function () { clearTimeout(t); t = setTimeout(check, 300) });
  check();
}

// ------------------------------------------------------------------ signing in
// One dialog, a step at a time: Google or email; a new account's code; a
// forgotten password; then, the first time, the name others will see.
function signIn(why, then) {
  var S = { step: "start", email: "", name: "" };
  function paint() {
    var lead = why ? '<p class="hint cm-why">To ' + esc(why) + ', sign in or make an account. The studio works without one.</p>' : '';
    var h = "";
    if (S.step === "start") {
      h = lead +
        '<button class="btn cm-google" id="si-google"><svg viewBox="0 0 18 18" aria-hidden="true"><path fill="#4285F4" d="M17.6 9.2c0-.6-.1-1.2-.2-1.7H9v3.3h4.8a4.1 4.1 0 0 1-1.8 2.7v2.2h2.9c1.7-1.6 2.7-3.9 2.7-6.5z"/><path fill="#34A853" d="M9 18c2.4 0 4.5-.8 6-2.2l-2.9-2.2c-.8.5-1.8.9-3.1.9-2.4 0-4.4-1.6-5.1-3.8H.9v2.3A9 9 0 0 0 9 18z"/><path fill="#FBBC05" d="M3.9 10.7a5.4 5.4 0 0 1 0-3.4V5H.9a9 9 0 0 0 0 8z"/><path fill="#EA4335" d="M9 3.6c1.3 0 2.5.5 3.5 1.4l2.6-2.6A9 9 0 0 0 .9 5l3 2.3C4.6 5.1 6.6 3.6 9 3.6z"/></svg>Continue with Google</button>' +
        '<div class="cm-or"><span>or with your email</span></div>' +
        '<label class="cm-f"><span>Email</span><input id="si-email" type="email" autocomplete="email" value="' + esc(S.email) + '"></label>' +
        '<label class="cm-f"><span>Password</span><input id="si-pw" type="password" autocomplete="current-password"></label>' +
        '<p class="note bad" id="si-err" hidden></p>' +
        '<div class="ck-foot cm-si-foot"><button type="button" class="cm-link" id="si-forgot">Forgot your password?</button>' +
        '<button class="btn" id="si-new">Make an account</button><button class="btn primary" id="si-go">Sign in</button></div>';
    } else if (S.step === "signup") {
      h = lead +
        '<label class="cm-f"><span>Your name</span><input id="su-name" maxlength="40" autocomplete="name" value="' + esc(S.name) + '"></label>' +
        '<label class="cm-f"><span>Email</span><input id="su-email" type="email" autocomplete="email" value="' + esc(S.email) + '"></label>' +
        '<label class="cm-f"><span>Password (8 characters or more)</span><input id="su-pw" type="password" autocomplete="new-password"></label>' +
        '<p class="note bad" id="si-err" hidden></p>' +
        '<div class="ck-foot"><button class="btn" id="su-back">Back</button><button class="btn primary" id="su-go">Make the account</button></div>';
    } else if (S.step === "verify") {
      h = '<p>We sent a code to <b>' + esc(S.email) + '</b>. Type it here to finish.</p>' +
        '<label class="cm-f"><span>Code</span><input id="vf-code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" class="cm-code"></label>' +
        '<p class="note bad" id="si-err" hidden></p>' +
        '<div class="ck-foot"><button type="button" class="cm-link" id="vf-again">Send it again</button><button class="btn primary" id="vf-go">Confirm</button></div>';
    } else if (S.step === "forgot") {
      h = '<p class="hint">We email you a code to set a new password.</p>' +
        '<label class="cm-f"><span>Email</span><input id="fg-email" type="email" value="' + esc(S.email) + '"></label>' +
        '<p class="note bad" id="si-err" hidden></p>' +
        '<div class="ck-foot"><button class="btn" id="fg-back">Back</button><button class="btn primary" id="fg-go">Send the code</button></div>';
    } else if (S.step === "reset") {
      h = '<p>We sent a code to <b>' + esc(S.email) + '</b>.</p>' +
        '<label class="cm-f"><span>Code</span><input id="rs-code" inputmode="numeric" maxlength="8" class="cm-code"></label>' +
        '<label class="cm-f"><span>New password (8 characters or more)</span><input id="rs-pw" type="password" autocomplete="new-password"></label>' +
        '<p class="note bad" id="si-err" hidden></p>' +
        '<div class="ck-foot"><button class="btn" id="rs-back">Back</button><button class="btn primary" id="rs-go">Set it and sign in</button></div>';
    } else if (S.step === "google") {
      h = '<div class="cm-wait"><div class="cm-spin" aria-hidden="true"></div><p><b>Finish signing in in your browser.</b></p>' +
        '<p class="hint">Google opened in your browser. When it says you are signed in, come back here.</p>' +
        (S.url ? '<p class="hint">Nothing opened? Copy this into your browser:<br><input class="cm-url" readonly value="' + esc(S.url) + '"></p>' : '') +
        '<p class="note bad" id="si-err" hidden></p></div>' +
        '<div class="ck-foot"><button class="btn" id="gg-back">Cancel</button></div>';
    }
    H.sheet(S.step === "signup" ? "Make a community account" : S.step === "verify" ? "Check your email" :
      S.step === "forgot" || S.step === "reset" ? "A new password" : "Sign in to the community", h);
    bind();
  }
  function err(e) { var el = $("si-err"); if (el) { el.hidden = false; el.textContent = e.message || String(e) } }
  function busy(id, on) { var b = $(id); if (b) b.disabled = on }
  function done() {
    refreshState().then(function (s) {
      if (s.signed_in && !s.profile) { profileDialog(null, then); return }
      H.closeSheet();
      toast("Signed in as @" + s.profile.handle);
      if (then) then();
      else show();
    });
  }
  function enter(id, fn) { var el = $(id); if (el) el.addEventListener("keydown", function (e) { if (e.key === "Enter") fn() }) }
  var poll = null;
  function bind() {
    if (S.step === "start") {
      $("si-google").addEventListener("click", function () {
        busy("si-google", true);
        api("POST", "auth/google", {}).then(function (r) {
          S.step = "google"; S.url = r.url; paint();
          poll = setInterval(function () {
            var sh = document.getElementById("sheet");
            if (sh && sh.hidden) { clearInterval(poll); return }      // closed: given up
            api("GET", "auth/google").then(function (g) {
              if (S.step !== "google") { clearInterval(poll); return }
              if (g.state === "done") { clearInterval(poll); done() }
              else if (g.state === "failed" || g.state === "none") { clearInterval(poll); S.step = "start"; paint(); err(new Error(g.error || "Google sign-in did not finish.")) }
            }).catch(function () {});
          }, 1200);
        }).catch(function (e) { busy("si-google", false); err(e) });
      });
      function go() {
        S.email = $("si-email").value.trim();
        busy("si-go", true);
        api("POST", "auth/signin", { email: S.email, password: $("si-pw").value }).then(done).catch(function (e) {
          busy("si-go", false);
          if (e.code === "verify") { S.step = "verify"; paint() } else err(e);
        });
      }
      $("si-go").addEventListener("click", go);
      enter("si-pw", go);
      $("si-new").addEventListener("click", function () { S.email = $("si-email").value.trim(); S.step = "signup"; paint() });
      $("si-forgot").addEventListener("click", function () { S.email = $("si-email").value.trim(); S.step = "forgot"; paint() });
      ($("si-email").value ? $("si-pw") : $("si-email")).focus();
    } else if (S.step === "signup") {
      $("su-back").addEventListener("click", function () { S.step = "start"; paint() });
      function go2() {
        S.email = $("su-email").value.trim(); S.name = $("su-name").value.trim();
        busy("su-go", true);
        api("POST", "auth/signup", { email: S.email, password: $("su-pw").value, name: S.name }).then(function (r) {
          if (r.verify) { S.step = "verify"; paint() } else done();
        }).catch(function (e) { busy("su-go", false); err(e) });
      }
      $("su-go").addEventListener("click", go2);
      enter("su-pw", go2);
      $("su-name").focus();
    } else if (S.step === "verify") {
      function go3() {
        busy("vf-go", true);
        api("POST", "auth/verify", { email: S.email, code: $("vf-code").value }).then(done).catch(function (e) {
          busy("vf-go", false);
          if (e.code === "signin") { S.step = "start"; paint(); err(e) } else err(e);
        });
      }
      $("vf-go").addEventListener("click", go3);
      enter("vf-code", go3);
      $("vf-again").addEventListener("click", function () {
        api("POST", "auth/resend", { email: S.email }).then(function () { toast("Sent again") }).catch(err);
      });
      $("vf-code").focus();
    } else if (S.step === "forgot") {
      $("fg-back").addEventListener("click", function () { S.step = "start"; paint() });
      $("fg-go").addEventListener("click", function () {
        S.email = $("fg-email").value.trim();
        busy("fg-go", true);
        api("POST", "auth/resend", { email: S.email, kind: "forget-password" }).then(function () { S.step = "reset"; paint() })
          .catch(function (e) { busy("fg-go", false); err(e) });
      });
      $("fg-email").focus();
    } else if (S.step === "reset") {
      $("rs-back").addEventListener("click", function () { S.step = "forgot"; paint() });
      $("rs-go").addEventListener("click", function () {
        busy("rs-go", true);
        api("POST", "auth/reset", { email: S.email, code: $("rs-code").value, password: $("rs-pw").value }).then(done)
          .catch(function (e) { busy("rs-go", false); err(e) });
      });
      $("rs-code").focus();
    } else if (S.step === "google") {
      $("gg-back").addEventListener("click", function () { clearInterval(poll); S.step = "start"; paint() });
    }
  }
  paint();
}
// Your profile: the first time (choose the name others see), or changed later.
function profileDialog(p, then) {
  var first = !p, sug = ST.suggest || {};
  var cur = p || { handle: "", name: sug.name || "", bio: "", links: [], avatar_url: sug.image || null };
  var AV = { id: cur.avatar || null, url: cur.avatar_url || null, data: null };
  function avSrc() { return AV.data || (AV.id ? media(AV.id) : AV.url ? "api/community/avatar?u=" + encodeURIComponent(AV.url) : "") }
  H.sheet(first ? "Your name in the community" : "Your profile",
    (first ? '<p class="hint">Others see this next to your missions and comments. Your email is never shown.</p>' : '') +
    '<div class="cm-pf"><div class="cm-pf-av" id="pf-av">' + (avSrc() ? '<img src="' + esc(avSrc()) + '" alt="">' : '<span>?</span>') + '</div>' +
      '<div><button class="btn" id="pf-pic">Choose a picture…</button>' + (AV.id || AV.url ? ' <button class="btn ghost" id="pf-nopic">None</button>' : '') +
      '<input type="file" id="pf-file" accept="image/*" hidden></div></div>' +
    '<label class="cm-f"><span>Handle (@name)</span><input id="pf-handle" maxlength="24" value="' + esc(cur.handle) + '" autocomplete="off" spellcheck="false"><i id="pf-hok"></i></label>' +
    '<label class="cm-f"><span>Name</span><input id="pf-name" maxlength="40" value="' + esc(cur.name) + '"></label>' +
    '<label class="cm-f"><span>A few words about you</span><textarea id="pf-bio" rows="3" maxlength="500">' + esc(cur.bio) + '</textarea></label>' +
    '<label class="cm-f"><span>Links (https://, one a line, up to 4)</span><textarea id="pf-links" rows="2">' + esc((cur.links || []).join("\n")) + '</textarea></label>' +
    '<p class="note bad" id="pf-err" hidden></p>' +
    '<div class="ck-foot"><button class="btn" id="pf-no">' + (first ? "Not now" : "Cancel") + '</button><button class="btn primary" id="pf-ok">' + (first ? "Join the community" : "Save") + '</button></div>');
  var t = null;
  function check() {
    var h = $("pf-handle").value.trim();
    call("handle_free", { handle: h }).then(function (r) {
      $("pf-hok").textContent = r.free ? "Free" : r.message; $("pf-hok").className = r.free ? "good" : "bad";
    }).catch(function () {});
  }
  $("pf-handle").addEventListener("input", function () { clearTimeout(t); t = setTimeout(check, 300) });
  if (!first) check();
  $("pf-pic").addEventListener("click", function () { $("pf-file").click() });
  if ($("pf-nopic")) $("pf-nopic").addEventListener("click", function () { AV = { id: null, url: null, data: null }; $("pf-av").innerHTML = "<span>?</span>" });
  $("pf-file").addEventListener("change", function () {
    var f = this.files && this.files[0];
    if (!f) return;
    loadImage(URL.createObjectURL(f)).then(function (img) {
      AV.data = encode(img, 256, 256, 120000, true); AV.id = null; AV.url = null;
      $("pf-av").innerHTML = '<img src="' + AV.data + '" alt="">';
    }).catch(function () { toast("That picture could not be read") });
  });
  $("pf-no").addEventListener("click", H.closeSheet);
  $("pf-ok").addEventListener("click", function () {
    var b = this;
    b.disabled = true;
    (AV.data ? api("POST", "avatar", { data: AV.data }).then(function (r) { return r.id }) : Promise.resolve(AV.id)).then(function (aid) {
      return call("save_profile", { handle: $("pf-handle").value.trim(), name: $("pf-name").value.trim(), bio: $("pf-bio").value,
        links: $("pf-links").value.split(/\n+/).map(function (s) { return s.trim() }).filter(Boolean),
        avatar: aid || null, avatar_url: aid ? null : AV.url });
    }).then(function () { return refreshState() }).then(function (s) {
      H.closeSheet();
      toast(first ? "Welcome, @" + s.profile.handle : "Saved");
      if (then) then(); else show();
    }).catch(function (e) { b.disabled = false; $("pf-err").hidden = false; $("pf-err").textContent = e.message });
  });
  (first ? $("pf-handle") : $("pf-name")).focus();
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
function encode(img, w, h, cap, square) {
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

// ------------------------------------------------------------------ sharing
// The wizard: check, about, pictures, credits, review. What it is told is kept
// (in this browser, by mission) until it is published.
var STEPS = [["check", "Check"], ["about", "About"], ["pictures", "Pictures"], ["credits", "Credits"], ["review", "Review"]];
function draftKey(id) { return "community:draft:" + id }
function share(mode) {
  if (!ST.configured) { toast("The community is not open yet"); return }
  var cur = H.current();
  if (!cur || cur.readonly) {
    toast(cur && cur.preview ? "Pull it into your studio first, and change it" : "Open a mission of yours first, then share it");
    if (isOpen() && !(cur && cur.preview)) { hide(); H.library() }
    return;
  }
  needAccount("share a mission", function () { wizard(cur, mode) });
}
function wizard(cur, mode) {
  var W = { step: 0, mid: cur.id, pre: null, checks: null, info: H.shareInfo(), busy: false };
  var saved = null;
  try { saved = JSON.parse(localStorage.getItem(draftKey(cur.id)) || "null") } catch (e) {}
  var F = Object.assign({ name: cur.name, summary: "", description: cur.description || "", difficulty: "normal", tags: [],
    play_minutes: "", video_url: "", allow_remix: true, coauthors: "", notes: "", cover: null, thumb: null, shots: [],
    with_picture: true, agree: false }, saved || {});
  F.agree = false;
  F.mode = mode || F.mode || "new";
  function keep() {
    try { var k = Object.assign({}, F); delete k.agree; localStorage.setItem(draftKey(cur.id), JSON.stringify(k)) } catch (e) {}
  }
  function stepper() {
    return '<ol class="cm-steps">' + STEPS.map(function (s, i) {
      return '<li class="' + (i === W.step ? "on" : i < W.step ? "done" : "") + '"><b>' + (i + 1) + '</b>' + s[1] + '</li>' }).join("") + '</ol>';
  }
  function foot(nextLabel, nextOk) {
    return '<div class="ck-foot cm-wz-foot">' + (W.step ? '<button class="btn" id="wz-back">Back</button>' : '<button class="btn" id="wz-cancel">Cancel</button>') +
      '<button class="btn primary" id="wz-next"' + (nextOk === false ? ' disabled' : '') + '>' + nextLabel + '</button></div>';
  }
  function paint() {
    var s = STEPS[W.step][0], h = stepper();
    if (s === "check") h += checkStep();
    else if (s === "about") h += aboutStep();
    else if (s === "pictures") h += picturesStep();
    else if (s === "credits") h += creditsStep();
    else h += reviewStep();
    H.sheet((F.mode === "update" ? "Publish an update: " : "Share “") + (F.mode === "update" ? "“" + F.name + "”" : cur.name + "”"), h, true);
    bindStep(s);
    if ($("wz-cancel")) $("wz-cancel").addEventListener("click", H.closeSheet);
    if ($("wz-back")) $("wz-back").addEventListener("click", function () { collect(s); W.step--; paint() });
  }
  function next(s) { collect(s); keep(); W.step++; paint() }

  // 1. what the studio checks before anything goes up
  function checkStep() {
    if (!W.checks) return '<p class="hint cm-loading">Saving and checking the mission…</p>' + foot("Next", false);
    var pre = W.pre, errs = W.checks.filter(function (r) { return r.level === "error" }), warns = W.checks.filter(function (r) { return r.level === "warn" });
    var objs = W.info.objectives, block = [];
    if (!objs.length) block.push("A mission needs at least one objective: add one in the Objectives tab.");
    if (pre.unchanged && F.mode !== "update") block.push("Nothing has changed since you pulled “" + (pre.origin && pre.origin.name) + "”. Change something before sharing it.");
    if (pre.origin && pre.origin.id && F.mode !== "update" && W.remixClosed) block.push("Its author does not allow changed copies of “" + pre.origin.name + "” to be shared.");
    errs.forEach(function (r) { block.push(r.text) });
    var h = '';
    if (pre.published) {
      h += '<div class="cm-f"><span>This mission is already in the community (version ' + pre.published.version + ')</span>' +
        seg("wz-mode", ["update", "new"], F.mode) + '<i class="hint">Update: a new version of the same one, keeping its votes and comments. New: another mission, with a name of its own.</i></div>';
    }
    if (pre.origin && pre.origin.id)
      h += '<p class="note">Pulled from “' + esc(pre.origin.name) + '” by @' + esc(pre.origin.author && pre.origin.author.handle || pre.origin.author || "?") +
        '. Shared, it is a remix: it carries its line, and the original is credited.</p>';
    h += block.length ? '<div class="note bad"><b>Before it can be shared</b><ul>' + block.map(function (t) { return '<li>' + esc(t) + '</li>' }).join("") + '</ul></div>'
      : '<p class="ck-sum"><b class="good">Ready to share</b>' + (warns.length ? ' · ' + plural(warns.length, "thing") + ' to look at' : '') + '</p>';
    if (warns.length) h += '<ul class="cm-warns">' + warns.slice(0, 8).map(function (r) { return '<li>' + esc(r.text) + '</li>' }).join("") + '</ul>';
    h += '<div class="lbl cm-h">Objectives others will see</div><ol class="cm-objs">' + objs.map(function (o) { return '<li><span class="cm-ok">' + esc(o.kind) + '</span>' + esc(o.text) + '</li>' }).join("") + '</ol>';
    return h + foot("Next", !block.length);
  }
  function runChecks() {
    Promise.all([api("GET", "precheck?mission=" + encodeURIComponent(cur.id)), H.check()]).then(function (r) {
      W.pre = r[0]; W.checks = r[1] || [];
      if (W.pre.published && !mode && !saved) F.mode = "update";
      if (!W.pre.published) F.mode = "new";
      var o = W.pre.origin;
      if (o && o.id && F.mode !== "update") {
        return call("get_mission", { id: o.id }).then(function (m) {
          W.remixClosed = !m.allow_remix && !(ST.profile && m.author && m.author.id === ST.profile.id);
        }).catch(function () {});
      }
    }).then(function () {
      if (F.mode === "update" && W.pre.published) {
        return call("get_mission", { id: W.pre.published.id }).then(function (m) {
          if (!saved) Object.assign(F, { name: m.name, summary: m.summary, description: m.description, difficulty: m.difficulty,
            tags: m.tags || [], play_minutes: m.play_minutes || "", video_url: m.video_url || "", allow_remix: m.allow_remix,
            coauthors: (m.coauthors || []).map(function (p) { return p.handle }).join(", ") });
          W.published = m;
        }).catch(function () {});
      }
    }).then(function () { if (W.step === 0) paint() })
      .catch(function (e) { H.sheet("Share", '<p class="note bad">' + esc(e.message) + '</p><div class="ck-foot"><button class="btn" id="wz-cancel">Close</button></div>'); $("wz-cancel").addEventListener("click", H.closeSheet) });
  }

  // 2. what it is
  function aboutStep() {
    return '<label class="cm-f"><span>Name</span><input id="wz-name" maxlength="60" value="' + esc(F.name) + '"><i id="wz-name-ok"></i></label>' +
      '<label class="cm-f"><span>Summary: one line for its card</span><input id="wz-sum" maxlength="140" value="' + esc(F.summary) + '" placeholder="e.g. Get into the radar base at night without raising the alarm"></label>' +
      '<label class="cm-f"><span>Description</span><textarea id="wz-desc" rows="5" maxlength="6000" placeholder="The story, how it plays, what to look out for">' + esc(F.description) + '</textarea></label>' +
      '<div class="cm-row2"><div class="cm-f"><span>Difficulty</span>' + seg("wz-diff", ["easy", "normal", "hard"], F.difficulty) + '</div>' +
      '<label class="cm-f"><span>Play time (minutes)</span><input id="wz-min" type="number" min="1" max="600" value="' + esc(F.play_minutes) + '"></label></div>' +
      '<div class="cm-f"><span>Style (up to 6)</span>' + tagsHtml("wz-tags", F.tags) + '</div>' +
      '<div class="lbl cm-h">Filled in from the mission</div>' + factsTable() +
      foot("Next");
  }
  function factsTable() {
    var f = W.info.facts, rows = [["Base", esc(H.levelName(cur.base.level)) + (cur.base.kind === "empty" ? " (its empty map)" : " (a copy)")],
      ["Objectives", W.info.objectives.length]];
    if (f.guards != null) rows.push(["Guards", f.guards]);
    if (f.cameras) rows.push(["Cameras", f.cameras]);
    if (f.time_limit) rows.push(["Time limit", Math.floor(f.time_limit / 60) + " min"]);
    if (f.weather) rows.push(["Weather", esc(f.weather)]);
    if (f.music) rows.push(["Music", esc(f.music)]);
    if (f.cutscenes) rows.push(["Cutscenes", f.cutscenes]);
    return '<table class="cm-facts">' + rows.map(function (r) { return '<tr><th>' + r[0] + '</th><td>' + r[1] + '</td></tr>' }).join("") + '</table>';
  }

  // 3. pictures: the cover (required), screenshots
  function picturesStep() {
    var v3 = H.can3d(), pic = W.pre && W.pre.picture;
    return '<div class="cm-pics"><div><div class="lbl">Cover</div>' +
        '<div class="cm-coverbox" id="wz-cover">' + (F.cover ? '<img src="' + F.cover + '" alt="The cover">' : '<span class="hint">No cover yet</span>') + '</div>' +
        '<div class="cm-src"><button class="btn" data-src="3d"' + (v3 ? '' : ' disabled title="Open the 3D view and frame the shot first"') + '>The 3D view now</button>' +
        '<button class="btn" data-src="map">The map now</button>' +
        (pic ? '<button class="btn" data-src="picture">The mission’s picture</button>' : '') +
        '<button class="btn" data-src="file">A file…</button></div>' +
        '<p class="hint">Cut to 16:9 from the middle. Frame the 3D view or the map first, then take it.</p></div>' +
      '<div><div class="lbl">Screenshots (up to 4)</div><div class="cm-shotlist" id="wz-shots">' + F.shots.map(function (s, i) {
        return '<span class="cm-shotx"><img src="' + s + '" alt=""><button type="button" data-rm="' + i + '" aria-label="Remove">&times;</button></span>' }).join("") + '</div>' +
        (F.shots.length < 4 ? '<div class="cm-src"><button class="btn" data-shot="3d"' + (v3 ? '' : ' disabled') + '>3D view</button><button class="btn" data-shot="map">Map</button><button class="btn" data-shot="file">File…</button></div>' : '') +
        '<label class="cm-f"><span>A video of it (optional, https://)</span><input id="wz-video" value="' + esc(F.video_url) + '" placeholder="https://youtu.be/…"></label>' +
        (pic ? '<label class="cm-check"><input type="checkbox" id="wz-pic"' + (F.with_picture ? ' checked' : '') + '> Include the mission’s own picture (the game’s mission list)</label>' : '') +
      '</div></div><input type="file" id="wz-file" accept="image/*" hidden>' +
      foot("Next", !!F.cover);
  }
  function takePicture(src) {
    if (src === "file") {
      return new Promise(function (ok, no) {
        var inp = $("wz-file");
        inp.value = "";
        inp.onchange = function () { var f = inp.files && inp.files[0]; if (!f) return no(); loadImage(URL.createObjectURL(f)).then(ok, no) };
        inp.click();
      });
    }
    var url = src === "3d" ? H.capture3d() : src === "map" ? H.captureMap() : H.pictureUrl();
    if (!url) return Promise.reject(new Error("That picture is not there"));
    return loadImage(url);
  }

  // 4. who made it, and what others may do with it
  function creditsStep() {
    var line = (W.pre.lineage || []), me = ST.profile ? ST.profile.handle : "you";
    return (line.length ? '<div class="lbl">The line it carries</div><ol class="cm-line">' + line.map(function (x) {
        return '<li>' + esc(x.name) + ' <span class="hint">by @' + esc((x.author && x.author.handle) || "?") + '</span></li>' }).join("") +
        '<li class="cm-here"><b>' + esc(F.name) + '</b> <span class="hint">by @' + esc(me) + '</span></li></ol>' : '') +
      '<label class="cm-f"><span>Made with (their @handles, comma between)</span><input id="wz-co" value="' + esc(F.coauthors) + '" placeholder="@friend, @teammate"></label>' +
      '<label class="cm-check"><input type="checkbox" id="wz-rmx"' + (F.allow_remix ? ' checked' : '') + '> Others may share changed copies of it (remixes), crediting you</label>' +
      '<label class="cm-f"><span>' + (F.mode === "update" ? "What is new in this version (needed)" : "Notes on this version (optional)") + '</span>' +
        '<textarea id="wz-notes" rows="3" maxlength="1000">' + esc(F.notes) + '</textarea></label>' +
      foot("Next");
  }

  // 5. as others will see it
  function reviewStep() {
    var me = ST.profile || {};
    var card = { id: "", name: F.name, summary: F.summary || "(no summary)", author: me, level: cur.base.level, kind: cur.base.kind,
      score: 0, comments: 0, pulls: 0, objectives: W.info.objectives.length, facts: W.info.facts, remix_of: W.pre.origin };
    var c = cardHtml(card).replace(/background-image:url\([^)]*\)/, "background-image:url(" + (F.thumb || F.cover || "") + ")");
    return '<div class="cm-review"><div class="mgrid cm-grid one">' + c + '</div><div>' +
      '<p><b>' + esc(F.name) + '</b>' + (F.mode === "update" ? ' · version ' + ((W.published && W.published.version || 1) + 1) : '') + '</p>' +
      '<ul class="cm-up">' +
        '<li>The mission’s plan: everything you placed and set, for anyone to look at and pull</li>' +
        '<li>The cover' + (F.shots.length ? ' and ' + plural(F.shots.length, "screenshot") : '') + (F.with_picture && W.pre.picture ? ', and its picture' : '') + '</li>' +
        '<li>Not your AI designer chats, its history, or any of the game’s files</li></ul>' +
      '<label class="cm-check"><input type="checkbox" id="wz-agree"' + (F.agree ? ' checked' : '') + '> I made this mission, or it credits who did; it has none of the game’s files in it, and nothing hurtful.</label>' +
      '<p class="note bad" id="wz-err" hidden></p>' +
      '</div></div>' + foot(F.mode === "update" ? "Publish the update" : "Share it", F.agree);
  }

  function collect(s) {
    if (s === "about") {
      F.name = $("wz-name").value.trim(); F.summary = $("wz-sum").value.trim(); F.description = $("wz-desc").value;
      F.difficulty = segValue("wz-diff") || "normal"; F.tags = tagsValue("wz-tags"); F.play_minutes = $("wz-min").value;
    } else if (s === "pictures") {
      F.video_url = $("wz-video").value.trim();
      if ($("wz-pic")) F.with_picture = $("wz-pic").checked;
    } else if (s === "credits") {
      F.coauthors = $("wz-co").value; F.allow_remix = $("wz-rmx").checked; F.notes = $("wz-notes").value;
    } else if (s === "check" && $("wz-mode")) {
      F.mode = segValue("wz-mode") || F.mode;
    }
  }
  function bindStep(s) {
    var nx = $("wz-next");
    if (s === "check") {
      if (!W.checks) { runChecks(); return }
      if ($("wz-mode")) bindSeg("wz-mode", function (v) {
        F.mode = v;
        if (v !== "update" || W.published) { paint(); return }
        // an update starts from what is there now
        call("get_mission", { id: W.pre.published.id }).then(function (m) {
          W.published = m;
          Object.assign(F, { name: m.name, summary: m.summary, description: m.description, difficulty: m.difficulty,
            tags: m.tags || [], play_minutes: m.play_minutes || "", video_url: m.video_url || "", allow_remix: m.allow_remix,
            coauthors: (m.coauthors || []).map(function (p) { return p.handle }).join(", ") });
        }).catch(function () {}).then(paint);
      });
      nx.addEventListener("click", function () { next(s) });
    } else if (s === "about") {
      bindSeg("wz-diff"); bindTags("wz-tags");
      nameCheck($("wz-name"), $("wz-name-ok"), F.mode === "update" && W.pre.published ? W.pre.published.id : null);
      nx.addEventListener("click", function () {
        collect(s);
        if (F.name.length < 3) { $("wz-name").focus(); return }
        if (!F.summary) { $("wz-sum").focus(); toast("A line for its card"); return }
        if ($("wz-name-ok").className === "bad") { $("wz-name").focus(); toast("Choose another name"); return }
        next(s);
      });
    } else if (s === "pictures") {
      document.querySelectorAll("#sheet-body [data-src]").forEach(function (b) {
        b.addEventListener("click", function () {
          collect(s);
          takePicture(b.getAttribute("data-src")).then(function (img) {
            F.cover = encode(img, 1280, 720, 440000); F.thumb = encode(img, 480, 270, 85000); keep(); paint();
          }).catch(function (e) { if (e) toast(e.message || "That picture could not be read") });
        });
      });
      document.querySelectorAll("#sheet-body [data-shot]").forEach(function (b) {
        b.addEventListener("click", function () {
          collect(s);
          takePicture(b.getAttribute("data-shot")).then(function (img) {
            F.shots.push(encode(img, 1280, 720, 440000)); keep(); paint();
          }).catch(function (e) { if (e) toast(e.message || "That picture could not be read") });
        });
      });
      document.querySelectorAll("#sheet-body [data-rm]").forEach(function (b) {
        b.addEventListener("click", function () { collect(s); F.shots.splice(+b.getAttribute("data-rm"), 1); keep(); paint() });
      });
      nx.addEventListener("click", function () { if (F.cover) next(s) });
    } else if (s === "credits") {
      nx.addEventListener("click", function () {
        collect(s);
        if (F.mode === "update" && !F.notes.trim()) { $("wz-notes").focus(); toast("Say what is new in this version"); return }
        next(s);
      });
    } else if (s === "review") {
      $("wz-agree").addEventListener("change", function () { F.agree = this.checked; nx.disabled = !this.checked });
      nx.addEventListener("click", function () { publish(nx) });
    }
  }
  function publish(btn) {
    btn.disabled = true; btn.textContent = "Sending…";
    var form = {
      mode: F.mode, name: F.name, summary: F.summary, description: F.description, difficulty: F.difficulty, tags: F.tags,
      play_minutes: F.play_minutes ? +F.play_minutes : null, video_url: F.video_url || null, allow_remix: F.allow_remix,
      coauthors: F.coauthors.split(/[,\s]+/).map(function (h) { return h.replace(/^@/, "").trim() }).filter(Boolean),
      notes: F.notes, objectives: W.info.objectives, facts: W.info.facts, cover: F.cover, thumb: F.thumb, shots: F.shots,
      with_picture: F.with_picture
    };
    H.check().then(function () {
      return api("POST", "publish", { mission: cur.id, form: form });
    }).then(function (r) {
      try { localStorage.removeItem(draftKey(cur.id)) } catch (e) {}
      H.communityPublished(r);
      LIST.items = [];
      H.sheet(F.mode === "update" ? "Updated" : "Shared",
        '<div class="cm-wait"><p><b>“' + esc(r.name) + '” is in the community' + (F.mode === "update" ? ', version ' + r.version : '') + '.</b></p>' +
        '<p class="hint">Others can find it, look at it, vote, comment and pull it now.</p></div>' +
        '<div class="ck-foot"><button class="btn" id="wz-close">Close</button><button class="btn primary" id="wz-see">See its page</button></div>');
      $("wz-close").addEventListener("click", H.closeSheet);
      $("wz-see").addEventListener("click", function () { H.closeSheet(); open({ kind: "mission", id: r.id }) });
    }).catch(function (e) {
      btn.disabled = false; btn.textContent = F.mode === "update" ? "Publish the update" : "Share it";
      var el = $("wz-err"); if (el) { el.hidden = false; el.textContent = e.message }
    });
  }
  paint();
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
  open: function (view) { open(view) },
  openMission: function (id) { open({ kind: "mission", id: id }) },
  hide: hide,
  isOpen: isOpen,
  state: function () { return ST },
  updates: function () { return UPDATES },
  refresh: refreshState,
  signIn: function () { signIn(null, null) },
  signOut: function () { return api("POST", "auth/signout", {}).then(refreshState).then(function () { toast("Signed out of the community") }) },
  share: share,
  pull: function (meta) { pull({ id: meta.id, version: meta.version, name: meta.name }) },
  profile: function () { if (member()) open({ kind: "profile", handle: ST.profile.handle }); else signIn(null, null) }
};
// the editor's side is there already: its script comes first
if (window.StudioCommunity) window.Community.init(window.StudioCommunity);
})();
