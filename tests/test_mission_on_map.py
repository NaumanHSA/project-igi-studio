"""A mission made on an empty map, as the build writes it. Found 2026-11-03 playing
one an agent had made: no numbers on the map computer, weapons hanging in the air, a
fence buried in places and above the ground in others, and the two leaves of a gate a
metre apart."""
import json, pathlib, re, shutil, subprocess, sys, tempfile, unittest

from studio.build import surface as SF

GAME = pathlib.Path("D:/IGI1")
LEVEL2 = GAME / "missions" / "location0" / "level2"
ROOT = pathlib.Path(__file__).resolve().parent.parent
PIECE = 4096.0


def task(src, tid):
    m = re.search(r'Task_New\(%d, "(\w+)", "[^"]*", ([-\d.]+), ([-\d.]+), ([-\d.]+),[^\n]*' % tid, src)
    return (m.group(1), float(m.group(2)) / PIECE, float(m.group(3)) / PIECE, float(m.group(4)) / PIECE, m.group(0)) if m else None


@unittest.skipUnless((LEVEL2 / "terrain").exists(), "no game here")
class EmptyMapMission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = SF.Terrain(str(LEVEL2), None)
        g = cls.t.z
        cls.g = g
        door = lambda: {"kind": "gate", "stop": [3.4, 0], "slider": 0, "head": 2, "fixed": [0, 0], "switch": "sw"}
        common = {"kind": "object", "type": "building", "patrol": []}
        plan = {
            "name": "Probe", "base": {"level": 2, "kind": "empty"},
            "placements": [
                # (flatten False is what older missions have for these: it asks for nothing now)
                dict(common, uid="fence", model="303_02_1", name="Fence", x=30908, y=-9388, z=g(30908, -9388), gamma=0, flatten=False),
                dict(common, uid="fence2", model="303_02_1", name="Fence", x=30923.84, y=-9388, z=g(30923.84, -9388), gamma=0),
                dict(common, uid="alone", model="301_01_1", name="Crate", x=30800, y=-9440, z=g(30800, -9440), gamma=0),
                dict(common, uid="kept", model="301_01_1", name="Crate", x=30700, y=-9440, z=g(30700, -9440), gamma=0, keepGround=True),
                dict(common, uid="leaf1", model="304_01_1", name="Gate", x=30962, y=-9388, z=g(30962, -9388), gamma=0, door=door()),
                dict(common, uid="leaf2", model="304_01_1", name="Gate", x=30966, y=-9388, z=g(30966, -9388), gamma=0, door=door()),
                {"uid": "sw", "type": "switch", "kind": "alarm", "model": "202_01_1", "gate": True, "name": "Gate switch",
                 "x": 30960, "y": -9388, "z": g(30960, -9388) + 1.06, "gamma": 0, "mount": "", "alarmId": None},
                dict(common, uid="box", model="219_01_1", name="Box", x=30904.5, y=-9360, z=g(30904.5, -9360), gamma=0,
                     label={"title": "Stores", "info": "What the base keeps."}),
                {"uid": "ground", "type": "pickup", "kind": "pickup", "pickupId": "WEAPON_ID_AK47", "name": "On the ground",
                 "patrol": [], "x": 30880, "y": -9360, "z": g(30880, -9360) + 0.5, "gamma": 1.5708},
                {"uid": "lid", "type": "pickup", "kind": "pickup", "pickupId": "WEAPON_ID_AK47", "name": "On the box",
                 "patrol": [], "x": 30904.5, "y": -9360, "z": g(30904.5, -9360) + 0.52, "gamma": 1.5708},
            ],
            "objectives": [{"uid": "o1", "kind": "collect", "text": "Take the rifle", "target": {"uid": "lid"}},
                           {"uid": "o2", "kind": "reach", "text": "Reach the rocks", "x": 30910, "y": -9350, "r": 5}],
            "nodes": [], "nodeEdits": [], "edits": [], "removeRefs": [], "removals": [], "ground": [], "brush": [], "sculpt": [],
            "events": [], "paint": [], "textures": [], "cutscenes": [], "failOnAlarm": False, "objBase": False, "ccwLying": True,
            "settings": {}, "levelScenes": {}, "levelVehicles": {}}
        cls.dir = pathlib.Path(tempfile.mkdtemp())
        (cls.dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        run = subprocess.run([sys.executable, "-m", "studio.build.plan", "--plan", str(cls.dir / "plan.json"),
                              "--out", str(cls.dir / "out"), "--game", str(GAME)],
                             capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        if run.returncode:
            raise RuntimeError(run.stdout[-1500:] + run.stderr[-1500:])
        cls.src = (cls.dir / "out" / "objects.qsc").read_text(encoding="latin-1")
        cls.h = json.loads((cls.dir / "out" / "heights.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def marks(self):
        return re.findall(r'"ComputerHilight", "Objective (\d)", [-\d.]+, [-\d.]+, [-\d.]+, "([^"]*)", "(\d*)", '
                          r'"COMPUTER:h_(\d)\.spr"', self.src)

    def test_each_objective_has_its_number_on_the_map(self):
        marks = self.marks()
        self.assertEqual([(m[0], m[3]) for m in marks], [("1", "1"), ("2", "2")])
        for n, show, link, _ in marks:
            self.assertNotEqual(show, "0", "marker %s is switched off" % n)

    def test_a_number_stands_on_a_thing_of_its_own_right_there(self):
        wants = {"1": (30904.5, -9360), "2": (30910, -9350)}
        for n, _, link, _ in self.marks():
            kind, x, y, z, text = task(self.src, int(link))
            self.assertEqual(kind, "Building", "the map computer cannot place a %s" % kind)
            self.assertIn(', "")', text, "it should have no model: nothing to see or bump into")
            self.assertAlmostEqual(x, wants[n][0], delta=0.01)
            self.assertAlmostEqual(y, wants[n][1], delta=0.01)

    def test_the_list_of_objectives_goes_to_those_too(self):
        d = next(x for x in self.src.splitlines() if 'Task_New(' in x and '"DefineComputerObjective"' in x)
        for n, _, link, _ in self.marks():
            self.assertIn(', %s, "StatusMessage_' % link, d)

    def test_a_label_of_a_building_stands_on_one_too(self):
        m = re.search(r'"ComputerHilight", "Stores", [-\d.]+, [-\d.]+, [-\d.]+, "1", "(\d+)"', self.src)
        self.assertEqual(task(self.src, int(m.group(1)))[0], "Building")

    def test_a_reach_area_is_at_the_ground(self):
        m = re.search(r'"AreaActivate", "Objective area", [-\d.]+, [-\d.]+, ([-\d.]+),', self.src)
        self.assertAlmostEqual(float(m.group(1)) / PIECE, self.g(30910, -9350) + 1.0, delta=0.05)

    def test_a_pickup_lies_on_what_is_under_it(self):
        self.assertAlmostEqual(self.h["placements"]["ground"], self.g(30880, -9360) + 0.03, delta=0.01)
        self.assertAlmostEqual(self.h["placements"]["lid"], self.h["placements"]["box"] + 0.5 + 0.02, delta=0.05)

    def test_a_run_of_fence_stands_at_one_height_on_ground_levelled_for_it(self):
        self.assertEqual(self.h["placements"]["fence"], self.h["placements"]["fence2"])
        self.assertTrue((self.dir / "out" / "terrain" / "terrain.hmp").exists(), "no ground was shaped")

    def test_nothing_is_tilted_to_fit(self):
        for m in re.finditer(r'"EditRigidObj", "Fence", [-.0-9]+, [-.0-9]+, [-.0-9]+, ([-.0-9]+), ([-.0-9]+),', self.src):
            self.assertEqual((float(m.group(1)), float(m.group(2))), (0.0, 0.0))
        self.assertNotIn("tilts", self.h)

    def test_the_leaves_of_a_gate_stand_at_one_height_and_its_switch_on_the_post(self):
        self.assertEqual(self.h["placements"]["leaf1"], self.h["placements"]["leaf2"])
        self.assertAlmostEqual(self.h["placements"]["sw"] - self.h["placements"]["leaf1"], 1.06 - 0.205, delta=0.01)


if __name__ == "__main__":
    unittest.main()
