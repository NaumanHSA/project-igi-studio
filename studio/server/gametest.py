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
_one_at_a_time = threading.Lock()


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

    def alive(self):
        pids = G.pids_of(self.exe)
        self.pid = pids[0] if pids else None
        return self.pid is not None

    def fatal(self):
        """What it is showing or has done that means it failed, or None."""
        if not self.alive():
            code = self.proc.poll()
            return "The game closed by itself (exit code %s)." % code
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
        say("the game came back to its main menu: trying again")
    return False, None, "The game's menu could not be got past."


def _pic(c, **about):
    w, h, png = c
    return dict({"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii"), "width": w, "height": h}, **about)


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
    built = build(mid, store, copy, {k: options.get(k) for k in ("start", "tour") if options.get(k)}, say)
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
            res = {"ok": False, "stage": "game", "loaded": False, "error": why, "fatal": fatal}
            if c:
                res["images"] = [_pic(c, what="the game when it stopped")]
            return res
        started = time.time()
        fatal = None
        if tour:
            say("STAGE the game's camera is going round the mission")
            pics, fatal = tour_pictures(game, tour, started)
        # then as the player stands, and long enough for what goes wrong as it starts
        seconds = max(3.0, min(120.0, float(options.get("seconds") or 15)))
        say("STAGE watching the mission run")
        end = time.time() + seconds
        first = None
        while time.time() < end and not fatal:
            fatal = game.fatal()
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
            return {"ok": False, "stage": "game", "loaded": True, "error": fatal, "fatal": fatal, "images": pics,
                    "seconds_run": int(time.time() - started)}
        return {"ok": True, "loaded": True, "slot": built.get("slot"), "seconds_run": int(time.time() - started),
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
