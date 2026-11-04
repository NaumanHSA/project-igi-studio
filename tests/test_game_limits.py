"""What crashed the game under an agent's mission, 2026-11-04, and looked like the level's
fault for a dozen tests: a description the game took as a key and could not hold; the
player taken out with a selection round everything; and a graph emptied under the
soldiers of a level's own cutscene. The game was seen failing on each."""
import pathlib, re, shutil, subprocess, tempfile, unittest

from studio import protect
from studio.build import flatten as FL  # noqa: F401  (the build's own imports stay importable here)
from studio.build import lang as L, slots as SL
from studio.qvm import read as QR
from studio.server import gametest as GT
from studio.setup import verify as V

ROOT = pathlib.Path(__file__).resolve().parent.parent
LONG = "Ekk is dead, but her bomb's core is headed for her secret airfield. Stop Colonel Volkov before he flies it out."


def fake_game(root):
    """A game folder with what a slot's name touches: language files as the game ships them."""
    game = pathlib.Path(root) / "game"
    for level in (14,):
        d = game / "missions" / "location0" / ("level%d" % level)
        d.mkdir(parents=True)
        (d / "mission.qvm").write_bytes(b"")
    for lang in ("USA", "english"):
        d = game / "language" / lang
        d.mkdir(parents=True)
        pairs = []
        for k, v in (("Mission 1 Name", "Trainyard"), ("Mission 1 Desc", "Small coastline trainyard")):
            pairs += [(b"NAME", ("LOCAL:%s/%s" % (lang, k)).encode() + b"\0"), (b"CSTR", v.encode() + b"\0")]
        (d / "missions.res").write_bytes(L.build(pairs))
    return game


class AMissionsWords(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.game = fake_game(self.dir)
        self.shipped = {p: p.read_bytes() for p in self.game.glob("language/*/missions.res")}
        real = L.paths.backups
        L.paths.backups = lambda: pathlib.Path(self.dir) / "backups"
        self.addCleanup(setattr, L.paths, "backups", real)
        real_check = protect.assert_language_file
        protect.assert_language_file = lambda p: pathlib.Path(p)    # (a folder in temp is no working game)
        self.addCleanup(setattr, protect, "assert_language_file", real_check)

    def test_they_go_under_each_languages_own_keys(self):
        L.set_mission_texts(self.game, 15, "Dead Hand", LONG)
        self.assertEqual(L.strings(self.game / "language/USA/missions.res")["LOCAL:USA/Mission 15 Desc"], LONG)
        self.assertEqual(L.strings(self.game / "language/english/missions.res")["LOCAL:english/Mission 15 Name"], "Dead Hand")

    def test_they_read_back(self):
        L.set_mission_texts(self.game, 15, "Dead Hand", LONG)
        self.assertEqual(L.mission_texts(self.game, 15), ("Dead Hand", LONG))
        self.assertIsNone(L.mission_texts(self.game, 16))

    def test_written_again_they_replace_what_was_there(self):
        L.set_mission_texts(self.game, 15, "One", "First")
        L.set_mission_texts(self.game, 15, "Two", "Second")
        self.assertEqual(L.mission_texts(self.game, 15), ("Two", "Second"))
        self.assertEqual(sum(k.endswith("Mission 15 Name") for k in L.strings(self.game / "language/USA/missions.res")), 1)

    def test_taken_out_the_file_is_as_it_shipped(self):
        L.set_mission_texts(self.game, 15, "Dead Hand", LONG)
        L.set_mission_texts(self.game, 15)
        for p, b in self.shipped.items():
            self.assertEqual(p.read_bytes(), b)

    def test_the_games_own_are_not_for_writing(self):
        with self.assertRaises(protect.ProtectedPath):
            L.set_mission_texts(self.game, 14, "Mine", "")
        L.set_mission_texts(self.game, 15, "Dead Hand", LONG)
        self.assertEqual(L.strings(self.game / "language/USA/missions.res")["LOCAL:USA/Mission 1 Name"], "Trainyard")

    def test_the_install_is_still_the_build_it_was(self):
        L.set_mission_texts(self.game, 15, "Dead Hand", LONG)
        for p, b in self.shipped.items():
            self.assertEqual(L.as_shipped(p), b)
            self.assertEqual(V._hash_of(p), __import__("hashlib").sha256(b).hexdigest())

    def test_marks_the_game_has_no_letter_for_become_ones_it_has(self):
        L.set_mission_texts(self.game, 15, "Mission 15 – Dead Hand", "Ekk’s “bomb” — now…")
        self.assertEqual(L.mission_texts(self.game, 15), ("Mission 15 - Dead Hand", 'Ekk\'s "bomb" - now...'))


class TheDefinition(unittest.TestCase):
    """As it goes into a real slot, in a copy of the definition's own code."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.game = fake_game(self.dir)
        (self.game / "missions/location0/level15").mkdir(parents=True)
        for name, fn in (("assert_language_file", lambda p: pathlib.Path(p)), ("assert_writable", lambda p: pathlib.Path(p))):
            self.addCleanup(setattr, protect, name, getattr(protect, name))
            setattr(protect, name, fn)
        self.addCleanup(setattr, L.paths, "backups", L.paths.backups)
        L.paths.backups = lambda: pathlib.Path(self.dir) / "backups"

    def test_it_names_keys_and_never_the_words(self):
        SL.write_definition(self.game, 15, 13, "Dead Hand", LONG)
        text = QR.decompile(QR.parse(self.game / "missions/location0/level15/mission.qvm"))
        self.assertIn('DefineMission(15, "Mission 15 Name", "Mission 15 Desc"', text)
        self.assertNotIn("Ekk", text)

    def test_it_reads_as_it_was_written(self):
        SL.write_definition(self.game, 15, 13, "Dead Hand", LONG)
        d = SL.read_definition(self.game, 15)
        self.assertEqual((d["name"], d["description"], d["base"], d["keyed"]), ("Dead Hand", LONG, 13, True))

    def test_one_of_an_older_studio_reads_as_it_is_and_says_so(self):
        from studio.qvm import write as QW
        (self.game / "missions/location0/level15/mission.qvm").write_bytes(QW.compile_text(
            'DefineMission(15, "Old Name", "Old words", "", MISSION_NEXT_MISSION_UNDEFINED, "missions/location0/level15", '
            '"missions/location0/common", "missions/location0/level15", "location0", "level13", "mission13.spr");\r\n'))
        d = SL.read_definition(self.game, 15)
        self.assertEqual((d["name"], d["description"], d["keyed"]), ("Old Name", "Old words", False))


class WhatTheBoxHolds(unittest.TestCase):
    def test_what_fits_is_left_alone(self):
        self.assertEqual(SL.in_game_description(LONG), LONG)
        self.assertEqual(SL.in_game_description(None), "")

    def test_more_is_cut_on_a_word(self):
        s = SL.in_game_description("word " * 80)
        self.assertLessEqual(len(s), SL.DESCRIPTION_MAX)
        self.assertTrue(s.endswith("word..."), s)

    def test_one_word_that_long_is_still_cut(self):
        s = SL.in_game_description("x" * 500)
        self.assertLessEqual(len(s), SL.DESCRIPTION_MAX)
        self.assertTrue(s.endswith("..."))

    @unittest.skipUnless(shutil.which("node"), "no node here")
    def test_the_editor_says_the_same(self):
        html = (ROOT / "editor" / "plotter.html").read_text(encoding="utf-8").replace("\r\n", "\n")
        i = html.index("var DESCRIPTION_MAX=")
        src = html[i:html.index("\n}\n", i) + 3]
        cases = ["", LONG, "word " * 80, "x" * 500, 'with "quotes" and\nlines, ' * 12, "a" * 119 + " b", "a" * 120, "a" * 121]
        js = src + "console.log(JSON.stringify(%s.map(inGameDescription)));\n" % __import__("json").dumps(cases)
        out = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(__import__("json").loads(out.stdout), [SL.in_game_description(c) for c in cases])


class ThePlayerStays(unittest.TestCase):
    def source(self):
        return (ROOT / "editor" / "plotter.html").read_text(encoding="utf-8").replace("\r\n", "\n")

    @unittest.skipUnless(shutil.which("node"), "no node here")
    def test_nothing_can_remove_him_but_he_can_move(self):
        html = self.source()
        i = html.index("function canRemove(o)")
        src = html[i:html.index("\n", i)]
        js = src + '''
console.log(JSON.stringify([canRemove({type:"player",ref:"HumanPlayer@1,2,3"}),canRemove({type:"building",ref:"Building@1,2,3"}),
canRemove({type:"building",own:true}),canRemove({type:"soldier",ref:"HumanSoldier@1,2,3",fixed:true}),canRemove({type:"building"}),canRemove(null)]));'''
        out = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "[false,true,true,false,false,false]")

    def test_a_selection_taken_out_leaves_him(self):
        html = self.source()
        body = html[html.index("function deleteGroup()"):]
        body = body[:body.index("\n}\n")]
        self.assertIn("list=list.filter(canRemove)", body)

    def test_a_mission_that_lost_him_has_him_back_on_the_map(self):
        self.assertIn('removeRefs=(p.removeRefs||[]).filter(function(r){return String(r).split("@")[0]!=="HumanPlayer"});', self.source())


class TheStartPage(unittest.TestCase):
    def test_an_agent_can_list_the_missions_from_it(self):
        # studio_status says to, and it was refused until a mission was open
        html = (ROOT / "editor" / "plotter.html").read_text(encoding="utf-8")
        self.assertIn('{name:"list_missions",look:true,anywhere:true,', html)


class WhatATestSays(unittest.TestCase):
    def test_a_crash_is_called_one(self):
        self.assertIn("crashed", GT.how_it_ended(3221225477))
        self.assertIn("exit code 3", GT.how_it_ended(3))

    def test_it_says_where(self):
        self.assertIn("name, description and picture", GT._said("The game crashed.", "menu"))
        self.assertTrue(GT._said("Warning: x", "loading").endswith("while the mission was loading."))
        self.assertEqual(GT._said("Whatever", "nowhere"), "Whatever")


class TheBuildsLastWord(unittest.TestCase):
    def source(self):
        return (ROOT / "studio" / "build" / "plan.py").read_text(encoding="utf-8")

    def test_a_soldiers_graph_keeps_a_point(self):
        src = self.source()
        self.assertIn("keeps one walkway point", src)
        self.assertLess(src.index("keeps one walkway point"), src.index("_edited_tables = {gid"))

    def test_the_regexes_find_what_the_game_has(self):
        m = re.search(r'Task_New\(-?\d+, "HumanAI", "(?:[^"\\]|\\.)*", "[^"]*", (\d+)\)',
                      'Task_New(3892, "HumanAI", "", "AITYPE_PATROL_AK", 3891))')
        self.assertEqual(m.group(1), "3891")


if __name__ == "__main__":
    unittest.main()
