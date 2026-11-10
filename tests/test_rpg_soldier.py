"""A soldier with the RPG-18 is the game's own kind of soldier, a HumanSoldierRPG, as level
10's "RPG Guard" is: bone set 2, stand animation 2. Written as a plain HumanSoldier, he
stopped the game with "Warning: Animation #1 not found" the moment he saw the player (a
person's mission on level 13, 2026-11-10). Seen in the test copy after the fix: the trooper
fires his rocket; a rifle guard given the RPG fires it; an RPG trooper given an AK shoots
it; one who arrives on an event comes and fires."""
import json, pathlib, re, shutil, tempfile, unittest

from studio import paths
from tests.test_events_in_game import GAME, build, empty_plan, task_text

LEVEL13 = GAME / "missions" / "location0" / "level13"
DECLARE = 'Task_DeclareParameters("HumanSoldierRPG", '


def compiles(test, src):
    from studio.qvm import write as QW
    QW.compile_text(src)


def level(lv):
    return json.loads((paths.data() / ("level%d.json" % lv)).read_text(encoding="utf-8"))


@unittest.skipUnless((LEVEL13 / "terrain").exists(), "no game here")
class RpgSoldier(unittest.TestCase):
    def setUp(self):
        self.where = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.where, ignore_errors=True)

    def soldier(self, uid, ai, model, weapon, **kw):
        s = {"uid": uid, "type": "soldier", "kind": "soldier", "ai": ai, "model": model, "weapon": weapon,
             "name": "RPG " + uid, "graph": "9", "patrol": [], "x": -240.0, "y": 21790.0, "z": 42666.668, "gamma": 2.35619}
        s.update(kw)
        return s

    def test_placed_ones_are_the_games_rpg_soldier(self):
        """The RPG trooper, and a rifle guard handed the RPG: both HumanSoldierRPG, bone set 2,
        stand 2, declared once, and named so by what watches them. A rifle guard stays as he was."""
        plan = empty_plan(
            placements=[self.soldier("r1", "AITYPE_RPG", "013_01_1", "WEAPON_ID_RPG18"),
                        self.soldier("r2", "AITYPE_GUARD_AK", "003_01_1", "WEAPON_ID_RPG18", x=-230.0),
                        self.soldier("r3", "AITYPE_GUARD_AK", "003_01_1", "WEAPON_ID_AK47", x=-220.0),
                        self.soldier("r4", "AITYPE_RPG", "013_01_1", "WEAPON_ID_RPG18", x=-210.0, arriveOn="e0", arriveTimes=1)],
            objectives=[{"uid": "o1", "kind": "kill", "text": "Kill him", "target": {"uid": "r1"}},
                        {"uid": "o2", "kind": "killAll", "text": "Kill them all"}],
            events=[{"uid": "e0", "name": "soon", "when": {"kind": "time", "seconds": 5},
                     "do": [{"kind": "message", "text": "here they come", "secs": 3}]},
                    {"uid": "e1", "name": "down", "when": {"kind": "dead", "target": {"uid": "r2"}},
                     "do": [{"kind": "message", "text": "down", "secs": 3}]}])
        run, src = build(dict(plan, name="RPG", base={"level": 13, "kind": "empty"}), self.where)
        self.assertEqual(run.returncode, 0, run.stdout[-800:])
        heads = {m.group(2): m for m in re.finditer(r'Task_New\((\d+), "(?:HumanSoldier\w*)", "(RPG r\d)", ', src)}
        self.assertEqual(set(heads), {"RPG r1", "RPG r2", "RPG r3", "RPG r4"})
        kinds = {}
        for name, m in heads.items():
            t = task_text(src, m.start())
            kinds[name] = (re.match(r'Task_New\(\d+, "(\w+)"', t).group(1), re.search(r'"0\d\d_01_1", 1, (-?\d+), (-?\d+)', t).groups())
        self.assertEqual(kinds["RPG r1"], ("HumanSoldierRPG", ("2", "2")))
        self.assertEqual(kinds["RPG r2"], ("HumanSoldierRPG", ("2", "2")))
        self.assertEqual(kinds["RPG r3"], ("HumanSoldier", ("1", "-1")))
        self.assertEqual(kinds["RPG r4"], ("HumanSoldierRPG", ("2", "2")))     # in his GuardGenerator
        self.assertEqual(src.count(DECLARE), 1)
        r1, r2 = (heads["RPG r1"].group(1), heads["RPG r2"].group(1))
        self.assertIn("HumanSoldierRPG_%s.isDead" % r1, src)      # kill, and every guard
        self.assertIn("HumanSoldierRPG_%s.isDead" % r2, src)      # the event
        self.assertNotRegex(src, r"\bHumanSoldier_(%s|%s)\b" % (r1, r2))
        compiles(self, src)

    def test_a_level_guard_given_the_rpg_and_one_relieved_of_it(self):
        """Level 8: a guard handed the RPG becomes one, and the level's and the mission's
        expressions name him so. Level 10: its RPG guard given an AK is a HumanSoldier again."""
        d8 = level(8)
        g = next(o for o in d8["objects"] if o.get("type") == "soldier" and o.get("id") == 400)
        plan = empty_plan(edits=[{"ref": g["ref"], "type": "soldier", "weapon": "WEAPON_ID_RPG18"}],
                          objectives=[{"uid": "o1", "kind": "kill", "text": "Kill him",
                                       "target": {"ref": g["ref"], "id": 400, "qtype": "HumanSoldier"}}])
        run, src = build(dict(plan, name="RPG 8", base={"level": 8, "kind": "copy"}), self.where)
        self.assertEqual(run.returncode, 0, run.stdout[-800:])
        t = task_text(src, src.index('Task_New(400, "'))
        self.assertTrue(t.startswith('Task_New(400, "HumanSoldierRPG", '), t[:80])
        self.assertIn('"%s", 1, 2, 2' % g["model"], t)
        self.assertIn("HumanSoldierRPG_400.isDead", src)
        self.assertNotRegex(src, r"\bHumanSoldier_400\b")
        self.assertEqual(src.count(DECLARE), 1)
        compiles(self, src)

        d10 = level(10)
        r = next(o for o in d10["objects"] if o.get("qtype") == "HumanSoldierRPG")
        plan = empty_plan(edits=[{"ref": r["ref"], "type": "soldier", "weapon": "WEAPON_ID_AK47", "ai": "AITYPE_PATROL_AK"}])
        shutil.rmtree(self.where / "out", ignore_errors=True)
        run, src = build(dict(plan, name="RPG 10", base={"level": 10, "kind": "copy"}), self.where)
        self.assertEqual(run.returncode, 0, run.stdout[-800:])
        t = task_text(src, src.index('Task_New(%d, "' % r["id"]))
        self.assertTrue(t.startswith('Task_New(%d, "HumanSoldier", ' % r["id"]), t[:80])
        self.assertIn('"013_01_1", 1, 1, -1', t)
        self.assertNotRegex(src, r"\bHumanSoldierRPG_%d\b" % r["id"])
        compiles(self, src)


if __name__ == "__main__":
    unittest.main()
