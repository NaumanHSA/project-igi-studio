"""Objectives and events as the game runs them. Each case here was seen in the game on
2026-11-10 with a test bench: missions that make every kind of event and objective happen
by themselves, read back from the game's memory (gametest.Probes). What the bench found:
a guard sent in on an event and told where to go crashed the game as he arrived; every
area was half the size it was drawn; "eliminate every guard" on level 8 crashed it as it
loaded, twice over; and taking out one of a level's reinforcements did the same."""
import json, pathlib, re, shutil, subprocess, sys, tempfile, unittest

from studio import paths
from studio.build import surface as SF
from studio.server import gametest as GT

ROOT = pathlib.Path(__file__).resolve().parent.parent
GAME = pathlib.Path("D:/IGI1")
LEVEL2 = GAME / "missions" / "location0" / "level2"
LEVEL8 = GAME / "missions" / "location0" / "level8"
PIECE = 4096.0
HAS_NODE = shutil.which("node")


def empty_plan(**kw):
    p = {"placements": [], "nodes": [], "nodeEdits": [], "edits": [], "removeRefs": [], "removals": [], "objectives": [],
         "ground": [], "brush": [], "sculpt": [], "events": [], "paint": [], "textures": [], "cutscenes": [], "failOnAlarm": False,
         "objBase": False, "ccwLying": True, "settings": {}, "levelScenes": {}, "levelVehicles": {}}
    p.update(kw)
    return p


def build(plan, where):
    pf = where / "plan.json"
    pf.write_text(json.dumps(plan), encoding="utf-8")
    run = subprocess.run([sys.executable, "-W", "ignore", "-m", "studio.build.plan", "--plan", str(pf), "--out", str(where / "out"),
                          "--game", str(GAME)], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT), timeout=300)
    src = (where / "out" / "objects.qsc").read_text(encoding="latin-1") if (where / "out" / "objects.qsc").exists() else ""
    return run, src


def task_text(src, start):
    depth, i, quoted = 0, start, False
    while i < len(src):
        c = src[i]
        if c == '"' and src[i - 1] != "\\":
            quoted = not quoted
        elif not quoted and c == "(":
            depth += 1
        elif not quoted and c == ")":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    return src[start:]


@unittest.skipUnless((LEVEL2 / "terrain").exists(), "no game here")
class OnAnEmptyMap(unittest.TestCase):
    """Level 2's empty map: a guard who arrives and moves on, an area, a pickup, every guard."""

    @classmethod
    def setUpClass(cls):
        g = SF.Terrain(str(LEVEL2), None).z
        P = (30793.9, -9228.7)
        guard = {"type": "soldier", "kind": "ai", "ai": "AITYPE_GUARD_AK", "weapon": "WEAPON_ID_AK47", "model": "003_01_1", "patrol": [],
                 "graph": "9", "team": 1}
        cls.plan = dict(empty_plan(), name="Probe", base={"level": 2, "kind": "empty"})
        cls.plan["placements"] = [
            dict(guard, uid="target", name="Target", x=30960.7, y=-9244.4, z=g(30960.7, -9244.4), gamma=0),
            dict(guard, uid="comes", name="Comes", x=30984.5, y=-9263.7, z=g(30984.5, -9263.7), gamma=0, arriveOn="e1", arriveTimes=1,
                 orders=[{"uid": "s1", "on": "e1", "do": "go", "stops": [3], "run": True}]),
            {"uid": "uzi", "type": "pickup", "kind": "pickup", "pickupId": "WEAPON_ID_UZI", "name": "Uzi", "patrol": [],
             "x": P[0] + 0.8, "y": P[1], "z": g(P[0] + 0.8, P[1]), "gamma": 0}]
        cls.plan["events"] = [
            {"uid": "e1", "name": "E1", "when": {"kind": "time", "seconds": 3}, "do": [{"kind": "message", "text": "E1", "secs": 3}]},
            {"uid": "e2", "name": "E2", "when": {"kind": "area", "x": P[0], "y": P[1], "r": 8}, "do": [{"kind": "message", "text": "E2"}]},
            {"uid": "e3", "name": "E3", "when": {"kind": "dead", "target": {"uid": "comes"}}, "do": [{"kind": "message", "text": "E3"}]}]
        cls.plan["objectives"] = [{"uid": "o1", "kind": "killAll", "text": "all"}, {"uid": "o2", "kind": "collect", "target": {"uid": "uzi"}},
                                  {"uid": "o3", "kind": "reach", "x": P[0], "y": P[1], "r": 6}]
        cls.plan["_probes"] = [{"label": "a", "expr": "{event:e1}"}, {"label": "b", "expr": "{area:%s;%s;3;CRITERIA_HUMAN1}" % P},
                               {"label": "c", "expr": "{gen:comes}.nSpawns > 0"}]
        cls.dir = pathlib.Path(tempfile.mkdtemp())
        cls.run_, cls.src = build(cls.plan, cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_it_built(self):
        self.assertEqual(self.run_.returncode, 0, self.run_.stdout[-1500:])

    def test_a_guard_who_arrives_has_his_paths_beside_his_spawner_not_in_it(self):
        g = re.search(r'Task_New\(\d+, "GuardGenerator"', self.src)
        self.assertIsNotNone(g)
        self.assertNotIn('"PatrolPath"', task_text(self.src, g.start()))
        self.assertIn('Task_New(-1, "Container", "Patrol Paths"', self.src)

    def area(self, name):
        m = re.search(r'Task_New\(\d+, "AreaActivate", "%s", [-\d.]+, [-\d.]+, [-\d.]+, 0, 0, 0, ([-\d.]+), ([-\d.]+), ([-\d.]+)' % name, self.src)
        return tuple(float(m.group(i)) / PIECE for i in (1, 2))

    def test_an_area_is_as_wide_as_twice_its_radius(self):
        # the game's AreaActivate takes whole widths: written as the radius, it was half the size drawn
        self.assertEqual(self.area("Event area"), (16.0, 16.0))
        self.assertEqual(self.area("Objective area"), (12.0, 12.0))

    def test_standing_on_a_pickup_is_about_a_metre(self):
        self.assertEqual(self.area("Objective pickup spot"), (2.0, 2.0))

    def test_a_guard_who_arrives_later_is_watched_by_nobody(self):
        self.assertIn("event 3 (E3): he only comes later", self.run_.stdout)
        every = re.search(r'"Objective 1 complete", 0, 0, 0, 0, 0, 0, "([^"]*)"', self.src).group(1)
        whole = every
        for v in re.findall(r"EditVariable_(\d+)", every):
            whole += re.search(r'Task_New\(%s, "EditVariable", "[^"]*", 0, 0, 0, 0, "([^"]*)"' % v, self.src).group(1)
        tid = re.search(r'Task_New\((\d+), "HumanSoldier", "Comes"', self.src).group(1)
        self.assertNotIn("HumanSoldier_%s." % tid, whole)

    def test_probes_start_at_their_own_values(self):
        vals = [int(x) for x in re.findall(r'"EditVariable", "Probe \d+", 0, 0, 0, (\d+),', self.src)]
        self.assertEqual(vals, [GT.PROBE_BASE, GT.PROBE_BASE + 2, GT.PROBE_BASE + 4])
        self.assertIn('"CRITERIA_HUMAN1"', self.src)


@unittest.skipUnless((LEVEL8 / "terrain").exists(), "no game here")
class OnACopyOfLevel8(unittest.TestCase):
    """Level 8 has reinforcements in GuardGenerators and three SAM guards in a ConditionalContainer."""

    @classmethod
    def setUpClass(cls):
        d = json.loads((paths.data() / "level8.json").read_text(encoding="utf-8"))
        cls.later = next(o for o in d["objects"] if o.get("id") == 400)        # inside a GuardGenerator
        cls.plan = dict(empty_plan(objectives=[{"uid": "o1", "kind": "killAll", "text": "all"}], removeRefs=[cls.later["ref"]]),
                        name="Probe", base={"level": 8, "kind": "copy"})
        cls.dir = pathlib.Path(tempfile.mkdtemp())
        cls.run_, cls.src = build(cls.plan, cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_it_built(self):
        self.assertEqual(self.run_.returncode, 0, self.run_.stdout[-1500:])

    def test_every_guard_names_none_the_level_makes_later(self):
        self.assertRegex(self.run_.stdout, r"eliminate every guard: the \d+ who arrive later are not counted")
        for tid in (401, 402, 442, 443, 444):
            self.assertNotIn("HumanSoldier_%d.isDead" % tid, self.src)

    def test_a_message_holds_only_a_short_condition(self):
        # the game's longest in a StatusMessage is 199 characters; 600 crashed level 8 as it loaded
        for m in re.finditer(r'"StatusMessage", "[^"]*", 0, 0, 0, 0, 0, 0, "([^"]*)"', self.src):
            self.assertLessEqual(len(m.group(1)), 200, m.group(1)[:80])

    def test_a_reinforcement_taken_out_takes_his_spawner(self):
        self.assertNotIn('Task_New(400, "HumanSoldier"', self.src)
        self.assertIn("came from a GuardGenerator of the level's: it goes with him", self.run_.stdout)
        for g in re.finditer(r'Task_New\(\d+, "GuardGenerator"', self.src):
            self.assertIn('"HumanSoldier"', task_text(self.src, g.start()))


@unittest.skipUnless((LEVEL8 / "terrain").exists(), "no game here")
class EveryGuardTakenOut(unittest.TestCase):
    """What a mission adds goes beside the level's first guard. With every guard taken out
    there is nothing of the level's after it, and the comma before it stood in front of a
    ")": ten of the fourteen levels did not compile (found by the bench, level 8, 2026-11-10)."""

    def test_the_level_still_compiles(self):
        from studio.qvm import write as QW
        for lv in (1, 8):
            d = json.loads((paths.data() / ("level%d.json" % lv)).read_text(encoding="utf-8"))
            refs = sorted({o["ref"] for o in d["objects"] if o.get("type") == "soldier" and o.get("ref") and not o.get("cutscene")})
            for events in ([], [{"uid": "e1", "name": "t", "when": {"kind": "time", "seconds": 3},
                                 "do": [{"kind": "message", "text": "hi", "secs": 3}]}]):
                with self.subTest(level=lv, events=len(events)):
                    where = pathlib.Path(tempfile.mkdtemp())
                    try:
                        run, src = build(dict(empty_plan(removeRefs=refs, events=events), name="All out",
                                              base={"level": lv, "kind": "copy"}), where)
                        self.assertEqual(run.returncode, 0, run.stdout[-800:])
                        QW.compile_text(src)
                    finally:
                        shutil.rmtree(where, ignore_errors=True)


def level_objectives(lv, keys=None):
    d = json.loads((paths.data() / ("level%d.json" % lv)).read_text(encoding="utf-8"))
    out, seen = [], set()
    for st in d["objectiveSets"]:
        for sl in st["slots"]:
            if sl["key"] in seen or (keys is not None and sl["key"] not in keys):
                continue
            seen.add(sl["key"])
            out.append(dict(kind="level", uid="l" + sl["key"], key=sl["key"], link=sl["link"], done=sl["done"],
                            failed=sl["failed"], text=sl["text"]))
    return out


def level_flow(src):
    lf = re.search(r'Task_New\(-?\d+, "LevelFlow"', src)
    return re.findall(r'"((?:[^"\\]|\\.)*)"', task_text(src, lf.start()))


@unittest.skipUnless((LEVEL8 / "terrain").exists(), "no game here")
class TheLevelsOwnObjectives(unittest.TestCase):
    """A copy of a level that keeps some of the level's objectives and none of its own:
    finishing them never completed the mission, since the level's end still waited for the
    ones left out (level 8 ends on its outro, after the extraction). Seen in the game after
    the fix, 2026-11-10: level 8's second objective alone, its door opened by an event, done
    at 7.6 s and the mission complete with it, then the level's outro."""

    def setUp(self):
        self.where = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.where, ignore_errors=True)

    def make(self, lv, objectives):
        shutil.rmtree(self.where / "out", ignore_errors=True)
        run, src = build(dict(empty_plan(objectives=objectives), name="Own", base={"level": lv, "kind": "copy"}), self.where)
        self.assertEqual(run.returncode, 0, run.stdout[-800:])
        return run, src

    def test_some_kept_end_the_mission_when_they_are_done(self):
        from studio.qvm import write as QW
        run, src = self.make(8, level_objectives(8, {"M8_OBJ2", "M8_OBJ3"}))
        self.assertIn('"Mission complete"', src)
        # the level's end, its outro, now plays once the mission's "Mission complete" has shown
        self.assertEqual(level_flow(src)[2], "CutScene_1111.isFinished")
        self.assertIn("the level's outro plays once the mission is won", run.stdout)
        # each held once true: a door open is true only while it is
        self.assertRegex(src, r'"Level objective 1 done", 0, 0, 0, 0, "EditVariable_(\d+)\.nValue == 0 && \(Door_240\.isOpen \|\| Door_241\.isOpen\)"')
        QW.compile_text(src)

    def test_all_kept_end_as_the_level_does(self):
        run, src = self.make(8, level_objectives(8))
        self.assertNotIn('"Mission complete"', src)
        self.assertEqual(level_flow(src)[2], "CutScene_1111.isFinished && !ConditionalContainer_1550.isRun")

    def test_one_kept_with_nothing_to_test_leaves_the_levels_end(self):
        run, src = self.make(8, level_objectives(8, {"M8_OBJ2", "M2_OBJ3"}))
        self.assertNotIn('"Mission complete"', src)
        self.assertIn("ends as the level does, which also waits", run.stdout)

    def test_an_expression_over_lines_stays_whole(self):
        """Level 2's second objective spans three lines; the line breaks came out " n":
        "&& nEditVariable_302", never true."""
        run, src = self.make(2, level_objectives(2))
        m = re.search(r'"M2_OBJ2", 444, "([^"]*)"', src)
        self.assertEqual(m.group(1), "EditVariable_301.nValue == 1 && EditVariable_302.nValue == 1 && EditVariable_303.nValue == 1")


class WhatATestSaysHappened(unittest.TestCase):
    PLAN ={"events": [{"uid": "e1", "name": "Gate", "do": [{"kind": "fail", "text": "x"}]}],
            "placements": [{"uid": "g", "type": "soldier", "name": "Late", "arriveOn": "e1"}],
            "objectives": [{"uid": "o1", "kind": "reach", "text": "Get there"}, {"uid": "o0", "kind": "level"}]}

    def test_it_watches_the_missions_own(self):
        labels = [p["label"] for p in GT.mission_probes(self.PLAN)]
        self.assertEqual(labels, ["event 1 (Gate) happened", "event 1 failed the mission", "Late arrived",
                                  "objective 1 (Get there) done", "the mission complete", "the player died"])

    def test_it_watches_the_levels_own_too(self):
        """One of the level's objectives is watched by what the level tests; one with nothing
        to test (an extraction, often) is not; and the mission complete is watched either way."""
        plan = {"objectives": [{"uid": "l1", "kind": "level", "key": "M8_OBJ2", "text": "Get in", "done": "Door_240.isOpen"},
                               {"uid": "l2", "kind": "level", "key": "M2_OBJ3", "text": "Get out", "done": ""}]}
        labels = [p["label"] for p in GT.mission_probes(plan)]
        self.assertEqual(labels, ["objective 1 (Get in) done", "the mission complete", "the player died"])

    def test_it_says_it_in_a_few_lines(self):
        rep = [{"label": "event 1 (Gate) happened", "happened": True, "after_s": 3.2, "seen_in_memory": True},
               {"label": "objective 1 (Get there) done", "happened": False, "after_s": None, "seen_in_memory": True},
               {"label": "the player died", "happened": False, "after_s": None, "seen_in_memory": True}]
        self.assertEqual(GT.what_happened(rep), ["Happened: event 1 (Gate) happened at 3 s.", "Did not happen while the test ran: objective 1 (Get there)."])


@unittest.skipUnless(HAS_NODE, "no node here")
class ThePickOnTheMap(unittest.TestCase):
    def page(self):
        return (ROOT / "editor" / "plotter.html").read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_a_guard_who_comes_later_is_not_offered(self):
        html = self.page()
        i = html.index("function comesLater(")
        js = html[i:html.index("\n", i) + 1] + '''
console.log(JSON.stringify([comesLater({type:"soldier"}),comesLater({type:"soldier",arriveOn:"e"}),comesLater({type:"soldier",reinforce:2}),comesLater({type:"pickup",arriveOn:"e"})]));'''
        out = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "[false,true,true,false]", out.stderr)
        self.assertIn('(o.own||o.id>=0)&&!comesLater(o)}],', html)

    def test_the_map_steps_back_while_it_asks(self):
        html = self.page()
        self.assertIn("drawPickFocus();             // while the map asks for something", html)
        self.assertIn('<div class="livepop pickpop" id="pickpop"', html)

    def test_areas_are_drawn_square_as_the_game_has_them(self):
        html = self.page()
        self.assertEqual(html.count("ctx.rect(p[0]-R,p[1]-R,2*R,2*R)"), 2)

    def test_guards_put_on_the_ground_go_to_walkways_on_the_ground(self):
        html = self.page()
        self.assertIn("(!ground||onTheGround(nd))", html)
        self.assertIn("(ground&&!onTheGround(n))", html)


if __name__ == "__main__":
    unittest.main()
