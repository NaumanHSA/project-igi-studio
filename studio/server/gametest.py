# Trying a mission in the real game, from a tool (test_load, test_tour in the editor).
#
# Never in the person's game: in a test copy, made once beside it. The mission is
# built there by a process of its own (studio/build/testbuild.py), the copy is
# started in a window, Enter is pressed twice (the main menu's first item, then
# the mission list, which opens on the mission), and from then on it only watches:
# a fatal error is a dialog box whose text can be read, a crash is the process
# going away, and the window can be pictured. Then the copy is closed.
#
# The keys go to the game's window as messages, not through the keyboard: so the
# person's mouse and keyboard are never used, and it works with the PC locked
# (where clicks made with the mouse reach nothing, 2026-11-03).
import base64, json, os, pathlib, shutil, subprocess, sys, tempfile, threading, time

from studio import paths
from studio.server import gamewin as G

MENU = (640, 480)            # what the menu's coordinates are in: it sits centred in a bigger window
# The two screens look much alike overall, so they are told apart by the bright green
# text that is on one and not the other, in the menu's own coordinates.
PLAY_TEXT = (250, 188, 390, 210)
OK_TEXT = (575, 402, 615, 426)
TEXT = 25                    # bright green pixels that make it text
CHANGED = 6.0                # how different two screens are, 0..255, for the level to have replaced the loading screen
JUMP = 5.0                   # how different two moments 0.1 s apart are, for the tour's camera to have cut
WIDTH, HEIGHT = 1024, 768
ACCESS_VIOLATION = 0xC0000005
# where it was when it failed: said with the failure, as it says where to look
WHERE = {"menu": "on the game's menus, before it started to load the mission: so look at what the mission list "
                 "reads (the mission's name, description and picture), not at what is on the map",
         "loading": "while the mission was loading",
         "running": "while the mission was running"}
_one_at_a_time = threading.Lock()


def how_it_ended(code):
    """In words, what the game's exit code says."""
    if code == ACCESS_VIOLATION:
        return "The game crashed (access violation, 0xC0000005)."
    return "The game closed by itself (exit code %s)." % code


def _said(text, where):
    return "%s It happened %s." % (str(text).strip().rstrip("."), WHERE[where]) if where in WHERE else text


def copy_path(cfg):
    """Where the test copy lives: what the settings say, or beside the game."""
    p = str(cfg.get("testGamePath") or "").strip()
    if p:
        return pathlib.Path(p)
    game = pathlib.Path(str(cfg.get("gamePath") or ""))
    return game.parent / "IGI-Test"


def ensure_copy(cfg, say):
    """The test copy, made the first time from the person's own game."""
    game = pathlib.Path(str(cfg.get("gamePath") or ""))
    copy = copy_path(cfg)
    if copy.resolve() == game.resolve():
        raise ValueError("The test copy can't be the game itself: %s" % copy)
    if (copy / "IGI.exe").exists() and (copy / "missions" / "location0").is_dir():
        return copy
    if not (game / "IGI.exe").exists():
        raise ValueError("The game is not at %s, so there is nothing to make a test copy from." % game)
    say("STAGE making a test copy of the game, once only, at %s" % copy)
    shutil.copytree(game, copy, dirs_exist_ok=True)
    return copy


def _env(copy):
    return dict(os.environ, IGISTUDIO_GAME=str(copy), IGISTUDIO_TESTRUN=str(copy / "_studio"),
                PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")


def build(mid, store, copy, options, say):
    """The build, in its own process. {ok, slot, error}."""
    say("STAGE building the mission into the test copy")
    with tempfile.TemporaryDirectory(prefix="igi-test-") as d:
        opt = pathlib.Path(d) / "options.json"
        opt.write_text(json.dumps(dict(options, width=WIDTH, height=HEIGHT)), encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-m", "studio.build.testbuild", "--source", str(pathlib.Path(store) / mid),
                              "--game", str(copy), "--options", str(opt)], cwd=str(paths.ROOT), env=_env(copy),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                             creationflags=0x08000000 if os.name == "nt" else 0)
        res, tail, reasons = None, [], []
        for line in p.stdout:
            line = line.rstrip()
            if line.startswith("RESULT "):
                res = json.loads(line[7:])
            elif line:
                say(line)
                tail = (tail + [line])[-12:]
                if line.lstrip().startswith("x "):            # the builder's reason for refusing it
                    reasons.append(line.strip()[2:])
        p.wait()
    res = res or {"ok": False, "error": "the build stopped: " + " / ".join(tail[-3:])}
    if reasons:
        res["error"] = "; ".join(reasons[:8])
    return res


# ------------------------------------------------------------------ the game, from outside
class Game:
    def __init__(self, copy):
        self.exe = pathlib.Path(copy) / "IGI.exe"
        self.proc = subprocess.Popen([str(self.exe), "Window"], cwd=str(copy), creationflags=0x00000008 | 0x00000200)
        self.pid = None
        self.where = "menu"

    def alive(self):
        pids = G.pids_of(self.exe)
        self.pid = pids[0] if pids else None
        return self.pid is not None

    def fatal(self):
        """What it is showing or has done that means it failed, or None."""
        if not self.alive():
            try:
                code = self.proc.wait(timeout=3)     # just gone: its code comes a moment later
            except subprocess.TimeoutExpired:
                code = None
            return how_it_ended(code)
        for d in G.dialogs_of(self.pid):
            if d.get("text"):
                return d["text"].strip()
        return None

    def inner(self):
        for w in G.windows_of(self.pid):
            if w["class"] == "Innerloop":
                return w
        return None

    def screen(self):
        """(window handle, the game's size) of what it draws in."""
        h = G.game_window(self.pid)
        i = self.inner() or {}
        return h, (i.get("w"), i.get("h"))

    def sig(self):
        h, size = self.screen()
        return G.signature(h, size) if h else None

    def picture(self):
        h, size = self.screen()
        c = G.capture(h, size) if h else None
        return c

    def green(self, box):
        """Bright green pixels in a box of the menu."""
        i = self.inner()
        h = G.game_window(self.pid) if i else None
        if not h:
            return 0
        dx, dy = (i["w"] - MENU[0]) // 2, (i["h"] - MENU[1]) // 2
        return G.green_in(h, (i["w"], i["h"]), (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy))

    def on_main_menu(self):
        return self.green(PLAY_TEXT) >= TEXT and self.green(OK_TEXT) < TEXT

    def on_mission_list(self):
        return self.green(OK_TEXT) >= TEXT

    def press(self, key):
        """A key, to the game's window."""
        i = self.inner()
        if not i:
            return False
        G.press(i["hwnd"], key)
        return True

    def key_in_front(self, key):
        """A real key, with the game's window in front a moment: what was in front
        before, to give it back (give_back)."""
        i = self.inner()
        if not i:
            return None
        before = G.foreground()
        G.front(i["hwnd"])
        time.sleep(0.4)
        G.key(key)
        return before

    def close(self):
        if self.alive():
            G.end(self.pid)
            # gone before anything else is asked of it: the next test finds no game running
            end = time.time() + 6
            while time.time() < end and self.alive():
                time.sleep(0.1)


def _until(game, test, seconds):
    """Waits for test() to come true: (it did, the text of a fatal error or None)."""
    end = time.time() + seconds
    while time.time() < end:
        f = game.fatal()
        if f:
            return False, f
        if test():
            return True, None
        time.sleep(0.15)
    return False, None


def enter_mission(game, say):
    """From the main menu into the mission: (ok, fatal, why not). ok once the level's own
    picture has replaced the loading screen. Enter on the main menu is its first item,
    Play; on the mission list, which opens on the mission, it starts it. Each is checked,
    because the game sometimes takes no notice of a key while a screen fades in."""
    for attempt in range(4):
        ok, fatal = _until(game, game.on_main_menu, 40)
        if fatal:
            return False, fatal, fatal
        if not ok:
            return False, None, "The game's main menu did not come up."
        time.sleep(0.5)                 # it fades in
        game.press(G.ENTER)
        ok, fatal = _until(game, game.on_mission_list, 4)
        if fatal:
            return False, fatal, fatal
        if not ok:
            say("the main menu took no notice of the key: trying again")
            continue
        time.sleep(0.5)
        game.press(G.ENTER)
        ok, fatal = _until(game, lambda: not game.on_mission_list(), 5)
        if fatal:
            return False, fatal, fatal
        if not ok:
            say("the mission list took no notice of the key: going back to the menu")
            game.press(G.ESCAPE)
            continue
        say("STAGE the mission is loading in the game")
        game.where = "loading"
        time.sleep(0.4)                 # the loading screen, once it has faded in
        loading = game.sig()
        end = time.time() + 180
        while time.time() < end:
            f = game.fatal()
            if f:
                return False, f, f
            s = game.sig()
            if s and loading and G.difference(s, loading) > CHANGED:
                if game.on_main_menu():
                    break                # back at the menu: it did not start
                return True, None, None
            time.sleep(0.15)
        else:
            return False, None, "The mission was still loading after 3 minutes."
        game.where = "menu"
        say("the game came back to its main menu: trying again")
    return False, None, "The game's menu could not be got past."


def _pic(c, **about):
    w, h, png = c
    return dict({"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii"), "width": w, "height": h}, **about)


# ------------------------------------------------------------------ probes
# What happened in the game, read from its memory (read only, as live_pos.py reads
# the player): each probe of a test build (plan.py, probes) is an EditVariable
# starting at PROBE_BASE + 2i, a value no other task has, which goes up by one the
# first time its expression comes true. The values share their three high bytes,
# so one search finds them all; a copy that never changes (the script's own
# constant) is told from the live one by changing.
PROBE_BASE = 0x51D0A000
PROBE_MAX = 120


class Probes:
    def __init__(self, pid, n, t0):
        from studio.server import live_pos as LP
        import struct
        self.LP, self.struct, self.n, self.t0 = LP, struct, n, t0
        self.h = LP.open_proc(pid)
        self.at = {}            # probe -> [addresses]
        self.fired = {}         # probe -> seconds after the start
        self.scan()

    def scan(self):
        key = self.struct.pack("<I", PROBE_BASE)[1:]
        for base, size in self.LP.regions(self.h, limit=0x7FFFFFFF):
            data = self.LP.read(self.h, base, size)
            if not data:
                continue
            i = data.find(key)
            while i >= 0:
                if i >= 1 and (base + i - 1) % 4 == 0:
                    v = self.struct.unpack_from("<I", data, i - 1)[0]
                    k, up = divmod(v - PROBE_BASE, 2)
                    if 0 <= k < self.n:
                        self.at.setdefault(k, []).append(base + i - 1)
                        if up:
                            self.fired.setdefault(k, round(time.time() - self.t0, 1))
                i = data.find(key, i + 1)

    def found(self):
        return len(self.at)

    def poll(self):
        now = round(time.time() - self.t0, 1)
        for k, addrs in self.at.items():
            if k in self.fired:
                continue
            for a in addrs:
                b = self.LP.read(self.h, a, 4)
                if b and len(b) == 4 and self.struct.unpack("<I", b)[0] == PROBE_BASE + 2 * k + 1:
                    self.fired[k] = now
                    break

    def report(self, probes):
        return [{"label": p.get("label") or p["expr"], "happened": k in self.fired, "after_s": self.fired.get(k),
                 "seen_in_memory": k in self.at} for k, p in enumerate(probes)]


# Every test watches the mission's own events and objectives (unless it brings
# probes of its own): what happened in the game, and when, and what did not.
def mission_probes(plan):
    """Probes for a mission's events, their messages, its arrivals, its objectives,
    the mission complete and the player's death, each with what it says if it
    happens: [{label, expr, says}]."""
    out = []
    for n, e in enumerate(plan.get("events") or [], 1):
        if not isinstance(e, dict) or not e.get("uid"):
            continue
        nm = e.get("name") or "event %d" % n
        out.append({"label": "event %d (%s) happened" % (n, nm), "expr": "{event:%s}" % e["uid"], "kind": "event", "n": n})
        for k, a in enumerate(e.get("do") or [], 1):
            if isinstance(a, dict) and a.get("kind") == "fail":
                out.append({"label": "event %d failed the mission" % n, "expr": "{fail:%s}" % e["uid"], "kind": "fail", "n": n})
    for p in plan.get("placements") or []:
        if p.get("type") == "soldier" and p.get("arriveOn"):
            out.append({"label": "%s arrived" % (p.get("name") or "a guard"), "expr": "{gen:%s}.nSpawns > 0" % p["uid"],
                        "kind": "arrived"})
    # the level's own objectives too, by the expression the level tests (one with none of
    # its own, as an extraction often is, has nothing to watch); and the mission complete,
    # on the mission's own end or, when it keeps the level's, the level's
    for i, o in enumerate(plan.get("objectives") or [], 1):
        if (isinstance(o, dict) and o.get("uid")
                and (o.get("kind") != "level" or (o.get("done") or "").strip())):
            out.append({"label": "objective %d (%s) done" % (i, o.get("text") or o.get("key") or o.get("kind")),
                        "expr": "{obj:%s}" % o["uid"], "kind": "objective", "n": i})
    if any(isinstance(o, dict) for o in plan.get("objectives") or []):
        out.append({"label": "the mission complete", "expr": "{done}", "kind": "done"})
    out.append({"label": "the player died", "expr": "HumanPlayer_0.isDead", "kind": "died"})
    return out[:PROBE_MAX]


def what_happened(report):
    """The probes' report in a few lines: what happened, when, and what did not."""
    if not report:
        return None
    yes = ["%s at %d s" % (r["label"], round(r["after_s"] or 0)) for r in report if r["happened"]]
    no = [r["label"].replace(" happened", "").replace(" done", "") for r in report
          if not r["happened"] and r["seen_in_memory"] and not r["label"].startswith(("the player died", "the mission complete"))]
    blind = [r["label"] for r in report if not r["seen_in_memory"]]
    lines = (["Happened: " + "; ".join(yes) + "."] if yes else ["Nothing the mission watches for happened."])
    if no:
        lines.append("Did not happen while the test ran: " + "; ".join(no) + ".")
    if blind:
        lines.append("Could not be read from the game: " + "; ".join(blind) + ".")
    return lines


def run(mid, store, cfg, options, say=print):
    """Build it into the test copy, start it, and report. options: {seconds, start, tour,
    map} where a tour is a list of shots, each {cams: [{dur, ...}], about: what it looks
    at}, and map asks for a picture of the map computer at the end."""
    if not _one_at_a_time.acquire(blocking=False):
        return {"ok": False, "error": "A test is running already: wait_for_job follows it. One at a time."}
    try:
        return _run(mid, store, cfg, options, say)
    finally:
        _one_at_a_time.release()


def _run(mid, store, cfg, options, say):
    if not (pathlib.Path(store) / mid).is_dir():
        return {"ok": False, "stage": "build", "error": "There is no mission %s." % mid}
    if G.any_game_running():
        return {"ok": False, "error": "The game is running. Only one copy can run at a time: close it, then test again."}
    t0 = time.time()
    copy = ensure_copy(cfg, say)
    probes = [p for p in (options.get("probes") or []) if isinstance(p, dict) and p.get("expr")][:PROBE_MAX]
    if not probes and options.get("probes") is not False:
        try:
            probes = mission_probes((json.loads((pathlib.Path(store) / mid / "mission.json").read_text(encoding="utf-8"))
                                     .get("plan")) or {})
        except (OSError, ValueError):
            probes = []
    built = build(mid, store, copy, dict({k: options.get(k) for k in ("start", "tour", "explode") if options.get(k)},
                                         **({"probes": probes, "probe_base": PROBE_BASE} if probes else {})), say)
    if not built.get("ok"):
        return {"ok": False, "stage": "build", "error": "It did not build: %s" % (built.get("error") or "see the log")}
    say("STAGE starting the test copy of the game")
    game = Game(copy)
    tour = options.get("tour") or []
    pics = []
    try:
        ok, fatal, why = enter_mission(game, say)
        if not ok:
            c = game.picture() if game.alive() else None
            res = {"ok": False, "stage": "game", "loaded": False, "error": _said(why, game.where) if fatal else why, "fatal": fatal,
                   "where": game.where}
            if c:
                res["images"] = [_pic(c, what="the game when it stopped")]
            return res
        started = time.time()
        game.where = "running"
        fatal = None
        if tour:
            say("STAGE the game's camera is going round the mission")
            pics, fatal = tour_pictures(game, tour, started)
        # then as the player stands, and long enough for what goes wrong as it starts
        seconds = max(3.0, min(240.0, float(options.get("seconds") or 15)))
        watch = None
        if probes:
            say("STAGE finding the probes in the game's memory")
            watch = Probes(game.pid, len(probes), started)
            say("probes found: %d of %d" % (watch.found(), len(probes)))
        say("STAGE watching the mission run")
        end = time.time() + seconds
        first = None
        while time.time() < end and not fatal:
            fatal = game.fatal()
            if watch:
                watch.poll()
            if not fatal and first is None and time.time() > end - seconds + min(3.0, seconds / 2):
                first = game.picture()
                if first:
                    pics.append(_pic(first, what="in the game, %d s after it started" % int(time.time() - started)))
            time.sleep(0.25)
        if not fatal:
            c = game.picture()
            if c:
                pics.append(_pic(c, what="in the game, %d s after it started" % int(time.time() - started)))
        if not fatal and options.get("map"):
            # the map computer, with the objectives' markers on it: in a mission the
            # game reads the keyboard itself, so M is a real key press, with the
            # game in front for a moment
            say("STAGE opening the map computer")
            before = game.key_in_front(G.KEY_M)
            time.sleep(2.5)
            fatal = game.fatal()
            c = None if fatal else game.picture()
            if c:
                pics.append(_pic(c, what="the map computer"))
            if not fatal:
                G.key(G.KEY_M)
            G.give_back_foreground(before)
        if fatal:
            c = game.picture() if game.alive() else None
            if c:
                pics.append(_pic(c, what="the game when it stopped"))
            if watch:
                watch.poll()
            return {"ok": False, "stage": "game", "loaded": True, "error": _said(fatal, "running"), "fatal": fatal,
                    "where": "running", "images": pics, "probes": watch.report(probes) if watch else None,
                    "what_happened": what_happened(watch.report(probes)) if watch else None,
                    "seconds_run": int(time.time() - started)}
        if watch:
            watch.poll()
        return {"ok": True, "loaded": True, "slot": built.get("slot"), "seconds_run": int(time.time() - started),
                "probes": watch.report(probes) if watch else None,
                "what_happened": what_happened(watch.report(probes)) if watch else None,
                "seconds_total": int(time.time() - t0), "images": pics,
                "said": "It built, loaded and ran in the game with no error. The pictures are the game's own."}
    finally:
        game.close()


def tour_pictures(game, tour, started=None):
    """A picture of each view of the tour, as the game's camera shows it: (pictures,
    fatal). Each view's camera stands still, so a view starts where the picture jumps
    from one moment to the next (a cut), and its picture is taken once it has settled a
    moment after. Going by the cut, not the clock, keeps every picture with its own
    view: the cutscene does not start the moment the level first shows (2026-11-03, a
    picture a view behind its label). A cut too slight to see (two views much alike)
    is given up on a little after the view should have ended."""
    pics, fatal = [], None
    begun = started or time.time()
    for i, sh in enumerate(tour):
        dur = sum(float(k.get("dur") or 0) for k in sh.get("cams") or [])
        if i:
            prev = game.sig()
            deadline = begun + dur_before + 2.5
            while time.time() < deadline:
                fatal = game.fatal()
                if fatal:
                    return pics, fatal
                time.sleep(0.08)
                s = game.sig()
                if s and prev and G.difference(s, prev) > JUMP:
                    break
                prev = s or prev
            begun = time.time()
        dur_before = dur
        settle = time.time() + min(1.2, dur * 0.35)
        while time.time() < settle:
            fatal = game.fatal()
            if fatal:
                return pics, fatal
            time.sleep(0.1)
        c = game.picture()
        if c:
            pics.append(_pic(c, what="in the game: " + str(sh.get("about") or "view %d" % (i + 1))))
    return pics, fatal
