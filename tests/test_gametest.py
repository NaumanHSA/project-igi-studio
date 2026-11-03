"""Trying a mission in the game (studio/server/gametest.py, studio/build/testbuild.py,
studio/server/gamewin.py). What the game itself does is tried by hand, on the test
copy; these keep the rest honest, above all that a test build can only ever write
to the test copy, and has no way to the person's game or their mission's record."""
import json, os, pathlib, shutil, subprocess, sys, tempfile, threading, unittest, zlib, struct
from unittest import mock

from studio.server import gametest as GT
from studio.server import gamewin as G

ROOT = pathlib.Path(__file__).resolve().parents[1]


def in_a_test_build(code, game, run):
    """Runs code in a process with a test build's environment."""
    env = dict(os.environ, IGISTUDIO_GAME=str(game), IGISTUDIO_TESTRUN=str(run), PYTHONPATH=str(ROOT))
    env.pop("IGISTUDIO_HOME", None)
    return subprocess.run([sys.executable, "-W", "ignore", "-c", code], env=env, capture_output=True, text=True, cwd=str(ROOT))


class TestBuildPlaceTests(unittest.TestCase):
    """Where a test build's process believes everything is."""
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="igi-gt-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        self.copy = self.d / "IGI-Test"
        self.run_dir = self.copy / "_studio"
        (self.copy / "missions" / "location0" / "level15").mkdir(parents=True)

    def ask(self, expr):
        r = in_a_test_build("from studio import paths, protect\nprint(%s)" % expr, self.copy, self.run_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_its_game_is_the_copy_and_all_it_writes_is_inside_the_copy(self):
        self.assertEqual(pathlib.Path(self.ask("paths.game()")), self.copy)
        for what in ("paths.writable()", "paths.missions()", "paths.work()", "paths.backups()", "paths.cache()"):
            where = pathlib.Path(self.ask(what)).resolve()
            self.assertIn(self.run_dir.resolve(), [where] + list(where.parents), what)

    def test_it_reads_the_same_levels_and_data_as_the_studio(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        env.pop("IGISTUDIO_HOME", None)
        plain = subprocess.run([sys.executable, "-W", "ignore", "-c", "from studio import paths\nprint(paths.data())\nprint(paths.snapshot())"],
                               env=env, capture_output=True, text=True, cwd=str(ROOT)).stdout.split()
        self.assertEqual(self.ask("paths.data()"), plain[0])
        self.assertEqual(self.ask("paths.snapshot()"), plain[1])

    def test_the_gate_lets_it_write_only_to_the_copy(self):
        slot = self.copy / "missions" / "location0" / "level15" / "objects.qvm"
        self.assertTrue(self.ask("protect.assert_writable(%r)" % str(slot)))
        real = self.d / "RealGame" / "missions" / "location0" / "level15" / "objects.qvm"
        r = in_a_test_build("from studio import protect\nprotect.assert_writable(%r)" % str(real), self.copy, self.run_dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ProtectedPath", r.stderr)

    def test_a_process_without_the_environment_is_turned_away(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        env.pop("IGISTUDIO_TESTRUN", None)
        env.pop("IGISTUDIO_GAME", None)
        r = subprocess.run([sys.executable, "-W", "ignore", "-m", "studio.build.testbuild", "--source", str(self.d), "--game", str(self.copy)],
                           env=env, capture_output=True, text=True, cwd=str(ROOT))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("test copy", r.stderr)


class PrivateCopyTests(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="igi-gt-"))
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_the_mission_goes_private_and_a_tour_replaces_only_its_intro(self):
        src = self.d / "real" / "my-mission"
        (src / "history").mkdir(parents=True)
        (src / "history" / "1.json").write_text("{}")
        (src / "cover.png").write_bytes(b"x")
        keep = {"where": "outro", "name": "End", "shots": []}
        m = {"id": "my-mission", "slot": 15, "installed": {"a": 1}, "applied": {"b": 2},
             "plan": {"cutscenes": [{"where": "intro", "name": "Mine", "shots": []}, keep]}}
        (src / "mission.json").write_text(json.dumps(m))
        code = ("import json\nfrom studio.build import testbuild as T\nfrom studio.server import missions as MS\nimport pathlib\n"
                "print(T.private_copy(pathlib.Path(%r), {'tour': [{'kind': 'tour', 'cams': []}]}))\nprint(MS.STORE)" % str(src))
        r = in_a_test_build(code, self.d / "IGI-Test", self.d / "IGI-Test" / "_studio")
        self.assertEqual(r.returncode, 0, r.stderr)
        mid, store = r.stdout.split()
        self.assertEqual(mid, "my-mission")
        self.assertIn(str(self.d / "IGI-Test"), store)
        got = json.loads((pathlib.Path(store) / mid / "mission.json").read_text())
        self.assertIsNone(got["slot"])
        self.assertNotIn("installed", got)
        names = [(c["where"], c["name"]) for c in got["plan"]["cutscenes"]]
        self.assertEqual(names, [("intro", "Test tour"), ("outro", "End")])
        self.assertFalse((pathlib.Path(store) / mid / "history").exists())
        # the real one has not moved
        self.assertEqual(json.loads((src / "mission.json").read_text()), m)


class CopyPlaceTests(unittest.TestCase):
    def test_beside_the_game_unless_the_settings_say(self):
        self.assertEqual(GT.copy_path({"gamePath": "D:/Games/IGI"}), pathlib.Path("D:/Games/IGI-Test"))
        self.assertEqual(GT.copy_path({"gamePath": "D:/Games/IGI", "testGamePath": "E:/T"}), pathlib.Path("E:/T"))

    def test_the_game_itself_can_never_be_the_copy(self):
        with self.assertRaises(ValueError):
            GT.ensure_copy({"gamePath": "D:/Games/IGI", "testGamePath": "D:/Games/IGI"}, print)

    def test_made_once_from_the_game(self):
        d = pathlib.Path(tempfile.mkdtemp(prefix="igi-gt-"))
        self.addCleanup(shutil.rmtree, d, True)
        game = d / "IGI"
        (game / "missions" / "location0" / "level1").mkdir(parents=True)
        (game / "IGI.exe").write_bytes(b"MZ")
        said = []
        copy = GT.ensure_copy({"gamePath": str(game)}, said.append)
        self.assertEqual(copy, d / "IGI-Test")
        self.assertTrue((copy / "IGI.exe").exists())
        self.assertEqual(len(said), 1)
        said.clear()
        GT.ensure_copy({"gamePath": str(game)}, said.append)
        self.assertEqual(said, [])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="igi-gt-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "m1").mkdir()

    def test_with_the_game_running_it_says_so_and_touches_nothing(self):
        with mock.patch.object(G, "any_game_running", return_value=[42]), mock.patch.object(GT, "build") as b:
            r = GT.run("m1", str(self.d), {}, {})
        self.assertFalse(r["ok"])
        self.assertIn("running", r["error"])
        b.assert_not_called()

    def test_no_such_mission(self):
        self.assertIn("no mission", GT.run("nope", str(self.d), {}, {})["error"])

    def test_one_at_a_time(self):
        go, held = threading.Event(), threading.Event()

        def slow(*a):
            held.set()
            go.wait(5)
            return {"ok": True}
        with mock.patch.object(GT, "_run", side_effect=slow):
            t = threading.Thread(target=GT.run, args=("m1", str(self.d), {}, {}), daemon=True)
            t.start()
            held.wait(5)
            r = GT.run("m1", str(self.d), {}, {})
            self.assertFalse(r["ok"])
            self.assertIn("already", r["error"])
            go.set()
            t.join(5)

    def test_a_build_that_fails_never_starts_the_game(self):
        with mock.patch.object(G, "any_game_running", return_value=[]), mock.patch.object(GT, "ensure_copy", return_value=self.d), \
                mock.patch.object(GT, "build", return_value={"ok": False, "error": "plan rejected"}), mock.patch.object(GT, "Game") as g:
            r = GT.run("m1", str(self.d), {}, {})
        self.assertEqual(r["stage"], "build")
        self.assertIn("plan rejected", r["error"])
        g.assert_not_called()


class FakeGame:
    """The screens the game goes through, as the check sees them."""
    def __init__(self, screens, fatal_at=None):
        self.screens = list(screens)
        self.i = 0
        self.clicks = []
        self.fatal_at = fatal_at

    def _s(self):
        return self.screens[min(self.i, len(self.screens) - 1)]

    def fatal(self):
        return "Fatal error: the thing" if self.fatal_at is not None and self.i >= self.fatal_at else None

    def on_main_menu(self):
        return self._s() == "menu"

    def on_mission_list(self):
        return self._s() == "list"

    def click_menu(self, at):
        self.clicks.append(at)
        self.i += 1

    def close_menu_screen(self):
        self.i += 1

    def sig(self):
        s = self._s()
        # after the loading screen has been read, the level comes
        if s == "loading":
            self.i += 1
            return [0] * 768
        return [200] * 768 if s == "level" else [40] * 768


class EnterMissionTests(unittest.TestCase):
    def go(self, game):
        with mock.patch.object(G, "park"), mock.patch.object(GT.time, "sleep"):
            return GT.enter_mission(game, lambda x: None)

    def test_two_clicks_and_the_level(self):
        g = FakeGame(["menu", "list", "loading", "level"])
        self.assertEqual(self.go(g), (True, None, None))
        self.assertEqual(g.clicks, [GT.PLAY, GT.OK])

    def test_a_fatal_error_in_the_menu_is_given_as_it_is(self):
        ok, fatal, why = self.go(FakeGame(["menu"], fatal_at=0))
        self.assertFalse(ok)
        self.assertEqual(fatal, "Fatal error: the thing")
        self.assertEqual(why, fatal)

    def test_a_fatal_error_while_it_loads(self):
        ok, fatal, _ = self.go(FakeGame(["menu", "list", "loading"], fatal_at=2))
        self.assertFalse(ok)
        self.assertIn("Fatal", fatal)

    def test_a_click_the_game_ignored_is_made_again(self):
        # the first click takes it nowhere, the second does
        g = FakeGame(["menu", "menu", "list", "loading", "level"])
        with mock.patch.object(GT, "_until", side_effect=[(True, None), (False, None), (True, None), (True, None), (True, None)]):
            ok, _, _ = self.go(g)
        self.assertTrue(ok)
        self.assertEqual(g.clicks[:2], [GT.PLAY, GT.PLAY])


class PictureTests(unittest.TestCase):
    def test_a_png_of_the_right_size_and_colours(self):
        w, h = 3, 2
        bgra = bytes([10, 20, 30, 255] * (w * h))
        png = G._png(w, h, bgra)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (w, h))
        i = png.index(b"IDAT")
        n = struct.unpack(">I", png[i - 4:i])[0]
        raw = zlib.decompress(png[i + 4:i + 4 + n])
        self.assertEqual(raw[:4], bytes([0, 30, 20, 10]))          # filter byte, then R G B

    def test_telling_screens_apart(self):
        self.assertEqual(G.difference([5] * 10, [5] * 10), 0)
        self.assertEqual(G.difference([0] * 10, [100] * 10), 100)
        self.assertEqual(G.difference(None, [1]), 255)
        self.assertEqual(G.brightness([10, 20]), 15)

    def test_green_text_is_counted_and_other_colours_are_not(self):
        w, h = 4, 2
        green, grey = bytes([40, 230, 60, 255]), bytes([200, 200, 200, 255])
        buf = green * 3 + grey * 5
        with mock.patch.object(G, "_frame", return_value=(w, h, buf)):
            self.assertEqual(G.green_in(1, None, (0, 0, 4, 2)), 3)
            self.assertEqual(G.green_in(1, None, (3, 0, 4, 2)), 0)
            self.assertEqual(G.green_in(1, None, (-5, -5, 2, 1)), 2)        # kept inside the picture

    def test_the_layer_s_own_title_bar_is_cut_off(self):
        # 646 x 509 with a 3 px border and a 26 px title bar round the game's 640 x 480
        W, H = 646, 509
        with mock.patch.object(G, "_u32") as u, mock.patch.object(G, "_grab", return_value=bytes(W * H * 4)), mock.patch.object(G, "_is_black", return_value=False):
            def rect(h, r):
                r._obj.right, r._obj.bottom = W, H
                return 1
            u.GetClientRect.side_effect = rect
            f = G._frame(1, (640, 480))
        self.assertEqual((f[0], f[1], len(f[2])), (640, 480, 640 * 480 * 4))


if __name__ == "__main__":
    unittest.main()
