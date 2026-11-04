"""What you do in the studio is what the game gets, and the studio knows what it has
given it. Found 2026-11-04 with an agent's mission and a person trying it: barrels moved
beside a crate stayed where the armoury first had them, an Apply never ended because
"-2 changes" is not none, guards could not be taken off an alarm, and a hill raised over
walkways an agent had laid could not be applied at all."""
import json, math, pathlib, re, shutil, subprocess, sys, tempfile, unittest

from studio import paths
from studio.build import own_things as OWN
from studio.build import surface as SF

ROOT = pathlib.Path(__file__).resolve().parent.parent
GAME = pathlib.Path("D:/IGI1")
LEVEL2 = GAME / "missions" / "location0" / "level2"
PIECE = 4096.0
HAS_NODE = shutil.which("node")


def page():
    return (ROOT / "editor" / "plotter.html").read_text(encoding="utf-8").replace("\r\n", "\n")


def js_function(html, name):
    i = html.index("function %s(" % name)
    return html[i:html.index("\n}\n", i) + 3]


def node(js):
    out = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class OwnThingsInTheBuild(unittest.TestCase):
    """studio/build/own_things.py: as far from the building as the plan has them."""
    HOME = {"uid": "b", "x": -697.61, "y": 21662.89, "z": 42666.668, "gamma": 4.71239}

    def thing(self, x, y, z, gamma=0.0):
        # the slot is where it first stood, and is not where it stands now
        return {"uid": "t", "of": "b", "x": x, "y": y, "z": z, "gamma": gamma, "slot": {"dx": 3.53, "dy": -4.57, "dz": -5.05, "dh": 3.6249}}

    def test_one_moved_on_its_own_stays_where_it_was_moved(self):
        t = self.thing(-698.024, 21660.041, 42661.618, 3.6249)
        off = OWN.offsets([self.HOME, t])["t"]
        x, y, z, _ = OWN.place(off, self.HOME)
        self.assertEqual((x, y, z), (-698.024, 21660.041, 42661.618))

    def test_it_goes_with_the_building_when_the_build_sets_that_down(self):
        t = self.thing(-698.024, 21660.041, 42661.618)
        off = OWN.offsets([self.HOME, t])["t"]
        x, y, z, _ = OWN.place(off, dict(self.HOME, z=42670.668))
        self.assertEqual((x, y, z), (-698.024, 21660.041, 42665.618))

    def test_it_turns_with_the_building(self):
        t = self.thing(-690.0, 21662.89, 42666.668, 0.5)
        off = OWN.offsets([self.HOME, t])["t"]
        turned = dict(self.HOME, gamma=self.HOME["gamma"] + math.pi / 2)
        x, y, _, g = OWN.place(off, turned)
        # 7.61 m east of it, turned a quarter to the left: 7.61 m north of it
        self.assertAlmostEqual(x, -697.61, places=2)
        self.assertAlmostEqual(y, 21662.89 + 7.61, places=2)
        self.assertAlmostEqual(g, (0.5 + math.pi / 2) % (2 * math.pi), places=3)

    def test_what_is_not_a_buildings_is_left_alone(self):
        self.assertEqual(OWN.offsets([self.HOME, {"uid": "x", "x": 1, "y": 2, "z": 3}]), {})
        self.assertEqual(OWN.offsets([{"uid": "x", "of": "gone", "slot": {}, "x": 1, "y": 2, "z": 3}]), {})


@unittest.skipUnless(HAS_NODE, "no node here")
class OwnThingsOnTheMap(unittest.TestCase):
    def run_it(self, body):
        html = page()
        return node(js_function(html, "reslot") + js_function(html, "groupMovers") + js_function(html, "syncDoorsOf") + body)

    def test_moved_on_its_own_its_place_follows_it(self):
        out = self.run_it('''
var b={uid:"b",own:true,x:100,y:200,z:50,gamma:0};
var t={uid:"t",own:true,of:"b",slot:{dx:1,dy:2,dz:0,dh:0,stop:[1,2]},x:104,y:202,z:50,gamma:0};
var placements=[b,t];reslot(t);
b.x=110;syncDoorsOf(b);
console.log(JSON.stringify({slot:t.slot,x:t.x,y:t.y}));''')
        self.assertEqual(out["slot"]["dx"], 4)
        self.assertEqual(out["slot"]["stop"], [1, 2])
        self.assertEqual((out["x"], out["y"]), (114, 202))

    def test_one_where_its_slot_says_is_not_touched(self):
        # (its plan stays what the game has: nothing to apply)
        out = self.run_it('''
var b={uid:"b",own:true,x:100,y:200,z:50,gamma:1.5708};
var sl={dx:1.5,dy:2.5,dz:0.2,dh:1};
var t={uid:"t",own:true,of:"b",slot:sl,gamma:2.5708,z:50.2};
var c=Math.cos(b.gamma),s=Math.sin(b.gamma);
t.x=+(b.x+sl.dx*c-sl.dy*s).toFixed(3);t.y=+(b.y+sl.dx*s+sl.dy*c).toFixed(3);
var placements=[b,t];reslot(t);
console.log(JSON.stringify(t.slot===sl));''')
        self.assertTrue(out)

    def test_in_a_group_with_its_building_it_moves_once(self):
        out = self.run_it('''
var b={uid:"b",own:true,x:100,y:200,z:50,gamma:0};
var t={uid:"t",own:true,of:"b",slot:{dx:1,dy:0,dz:0,dh:0},x:101,y:200,z:50,gamma:0};
var alone={uid:"a",own:true,of:"gone",slot:{dx:0,dy:0,dz:0,dh:0},x:5,y:5,z:5};
var placements=[b,t,alone];
console.log(JSON.stringify(groupMovers([b,t,alone]).map(function(o){return o.uid})));''')
        self.assertEqual(out, ["b", "a"])

    def test_a_loaded_mission_looks_at_them(self):
        self.assertIn("placements.forEach(reslot);", page())


@unittest.skipUnless(HAS_NODE, "no node here")
class WhatIsNotInTheGameYet(unittest.TestCase):
    """pendingChanges: none is none, and whatever changed counts."""
    PLAN = {"placements": [{"uid": "p1"}, {"uid": "p2"}], "nodes": [{"uid": "n1"}], "nodeEdits": [], "edits": [{"ref": "r1"}],
            "removeRefs": ["x@1"], "removals": [], "objectives": [{"uid": "o1"}, {"uid": "o2"}], "ground": [{"uid": "g1"}],
            "brush": [[1, 2, 3]], "sculpt": [[1, 2, 3]], "paint": [[1, 2, 3]], "settings": {"fall": "rain"}, "events": [{"uid": "e1"}],
            "textures": [], "cutscenes": [{"uid": "c1"}, {"uid": "c2"}], "failOnAlarm": False, "objBase": False,
            "levelScenes": {"7": "off"}, "levelVehicles": {"9": "off"}}

    def pending(self, change=""):
        html = page()
        js = ('var planVer=1,APPLIED_IX=null,APPLIED_ST={};function editKey(g,i){return g+":"+i}\n'
              + js_function(html, "appliedIndex") + js_function(html, "appliedState") + js_function(html, "pendingChanges")
              + "var APPLIED=%s;var cur=JSON.parse(JSON.stringify(APPLIED));var M={applied:APPLIED};function planOf(){return cur}\n" % json.dumps(self.PLAN)
              + change + ";planVer++;console.log(JSON.stringify(pendingChanges()));")
        return node(js)

    def test_a_mission_with_cutscenes_just_applied_has_nothing_to_apply(self):
        # it said "-2 changes to apply", which is not none: Apply never said it was done
        self.assertEqual(self.pending(), 0)

    def test_each_kind_of_change_counts(self):
        for what, change in {
            "a thing moved": 'cur.placements[0].x=5',
            "a thing added": 'cur.placements.push({uid:"p3"})',
            "a thing taken out": 'cur.placements.pop()',
            "an objective taken out": 'cur.objectives.pop()',
            "a walkway taken out": 'cur.nodes=[]',
            "a removal undone": 'cur.removeRefs=[]',
            "an edit undone": 'cur.edits=[]',
            "a cutscene changed": 'cur.cutscenes[0].name="x"',
            "a cutscene taken out": 'cur.cutscenes.pop()',
            "the big shapes cleared": 'cur.sculpt=[]',
            "the paint cleared": 'cur.paint=[]',
            "settings cleared": 'cur.settings={}',
            "a level scene put back": 'delete cur.levelScenes["7"]',
            "fails on the alarm": 'cur.failOnAlarm=true',
            "a picture added": 'cur.textures=[{name:"a"}]',
        }.items():
            self.assertGreater(self.pending(change), 0, what)


@unittest.skipUnless(HAS_NODE, "no node here")
class SlidersForTheGround(unittest.TestCase):
    def conv(self, body):
        html = page()
        return node(js_function(html, "slideT").replace("\n}\n", "\n}\n") + js_function(html, "slideV") + body)

    def test_a_value_comes_back_as_it_was(self):
        cases = [[20, 0, 600, 3, 0.1], [6, 1.5, 600, 3, 0.5], [0, -180, 180, 1, 5], [42666.7, 42587, 42747, 1, 0.1], [75, 0, 100, 1, 5]]
        out = self.conv("var c=%s;console.log(JSON.stringify(c.map(function(a){return slideV(slideT(a[0],a[1],a[2],a[3]),a[1],a[2],a[3],a[4])})));" % json.dumps(cases))
        for got, case in zip(out, cases):
            self.assertAlmostEqual(got, case[0], delta=max(case[4], abs(case[0]) * 0.02), msg=str(case))

    def test_the_low_end_of_a_wide_range_has_room(self):
        # 20 m of a 600 m reach is a third of the way along, not a thirtieth
        self.assertGreater(self.conv("console.log(JSON.stringify(slideT(20,0,600,3)));"), 300)

    def test_the_ends_are_the_ends(self):
        self.assertEqual(self.conv("console.log(JSON.stringify([slideV(0,0,600,3,0.1),slideV(1000,0,600,3,0.1),slideT(9999,0,60,2),slideT(-5,0,60,2)]));"),
                         [0, 600, 1000, 0])

    def test_every_number_of_the_panel_has_one(self):
        html = page()
        body = html[html.index("function renderGround(){"):]
        body = body[:body.index("\n}\n")]
        for field in ("gd-d", "gd-by", "gd-w", "gd-hh", "gd-ang", "gd-ablend", "gd-h", "gd-z0", "gd-z1", "gd-str", "gd-sm", "gd-rw",
                      "gd-bsize", "gd-bh", "gd-brough", "gd-bstr", "gd-psize"):
            self.assertIn('sld("%s"' % field, body, field)
        self.assertNotIn('+fld("', body)


class ThePanels(unittest.TestCase):
    def test_the_changes_have_a_panel_of_their_own_on_the_right_wall(self):
        html = page()
        rail = html[html.index('<aside class="rail right">'):html.index('<aside class="logpanel"')]
        self.assertNotIn('id="plist"', rail)
        self.assertIn('id="plist"', html[html.index('<aside class="logpanel"'):])
        ai = (ROOT / "editor" / "ai.js").read_text(encoding="utf-8")
        self.assertIn('id="tab-log"', ai)
        self.assertIn('$("panel-log").hidden = TAB !== "log"', ai)

    def test_a_guard_can_lose_his_patrol_and_his_alarm_alone_and_in_a_group(self):
        html = page()
        self.assertIn('id="iclr"', html)
        self.assertIn('id="al-off"', html)
        self.assertIn('data-g="nopatrol"', html)
        self.assertIn('data-g="noalarm"', html)
        self.assertIn('None: he answers no alarm', html)

    def test_an_agent_can_take_a_guard_off_the_alarm_too(self):
        html = page()
        tool = html[html.index('{name:"edit_guard"'):]
        self.assertIn("alarm:{type:\"string\"}", tool[:tool.index("\n")])
        self.assertIn('if(a.alarm==="none")', html)


@unittest.skipUnless((LEVEL2 / "terrain").exists(), "no game here")
class AsTheBuildWritesIt(unittest.TestCase):
    """A real build of a small mission on an empty map."""

    @classmethod
    def setUpClass(cls):
        t = SF.Terrain(str(LEVEL2), None)
        g = cls.g = t.z
        hx, hy = 30900.0, -9400.0
        # walkways of the mission's own start from one of the level's, on the ground
        graphs = json.loads((paths.data() / "graphs2.json").read_text(encoding="utf-8"))
        cls.graph, n0 = next((gid, n) for gid, gr in graphs.items() for n in gr.get("nodes", [])
                             if g(n["x"], n["y"]) is not None and abs(n["z"] - g(n["x"], n["y"])) <= 0.5)
        nx, ny = n0["x"], n0["y"]
        cls.row = nx, ny
        node_row = [{"uid": "n%d" % i, "graph": cls.graph, "x": nx + 4 + i * 5.0, "y": ny, "z": g(nx + 4 + i * 5.0, ny)} for i in range(5)]
        home = {"uid": "home", "kind": "object", "type": "building", "model": "301_01_1", "name": "Home", "patrol": [],
                "x": hx, "y": hy, "z": g(hx, hy), "gamma": 0}
        slot = {"dx": 2, "dy": 0, "dz": 0, "dh": 0}
        kept = {"uid": "kept", "kind": "object", "type": "building", "model": "300_01_1", "name": "Kept", "patrol": [], "of": "home", "slot": slot,
                "x": hx + 2, "y": hy, "z": g(hx, hy), "gamma": 0, "exact": True}
        moved = {"uid": "moved", "kind": "object", "type": "building", "model": "300_04_1", "name": "Moved", "patrol": [], "of": "home", "slot": slot,
                 "x": hx + 6, "y": hy + 4, "z": g(hx, hy), "gamma": 0, "exact": True}
        guard = {"type": "soldier", "kind": "ai", "ai": "AITYPE_GUARD_AK", "weapon": "WEAPON_ID_AK47", "model": "003_01_1", "patrol": [], "graph": cls.graph}
        plan = {
            "name": "Probe", "base": {"level": 2, "kind": "empty"},
            "placements": [home, kept, moved,
                           {"uid": "ctl", "type": "alarmctl", "kind": "alarm", "name": "Alarm", "patrol": [], "x": nx + 9, "y": ny + 8, "z": g(nx + 9, ny + 8), "gamma": 0, "hackTime": 4},
                           dict(guard, uid="on", name="On the alarm", x=nx + 9, y=ny, z=g(nx + 9, ny), gamma=0, alarmId="own:ctl"),
                           dict(guard, uid="off", name="Off the alarm", x=nx + 14, y=ny, z=g(nx + 14, ny), gamma=0, alarmId="none")],
            "nodes": node_row, "objectives": [], "nodeEdits": [], "edits": [], "removeRefs": [], "removals": [], "ground": [], "brush": [], "sculpt": [],
            "events": [], "paint": [], "textures": [], "cutscenes": [], "failOnAlarm": False, "objBase": False, "ccwLying": True,
            "settings": {}, "levelScenes": {}, "levelVehicles": {}}
        cls.dir = pathlib.Path(tempfile.mkdtemp())
        cls.plan = plan
        cls.first = cls.build(plan, "out")

    @classmethod
    def build(cls, plan, name):
        pf = cls.dir / (name + ".json")
        pf.write_text(json.dumps(plan), encoding="utf-8")
        run = subprocess.run([sys.executable, "-W", "ignore", "-m", "studio.build.plan", "--plan", str(pf), "--out", str(cls.dir / name), "--game", str(GAME)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT), timeout=300)
        return run

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def source(self):
        return (self.dir / "out" / "objects.qsc").read_text(encoding="latin-1")

    def test_it_built(self):
        self.assertEqual(self.first.returncode, 0, self.first.stdout[-1500:])

    def at(self, name):
        m = re.search(r'Task_New\(-?\d+, "\w+", "%s", ([-\d.]+), ([-\d.]+), ([-\d.]+),' % name, self.source())
        return tuple(float(m.group(i)) / PIECE for i in (1, 2, 3))

    def test_what_was_moved_stands_where_it_was_moved(self):
        x, y, _ = self.at("Moved")
        self.assertAlmostEqual(x, 30906.0, places=2)
        self.assertAlmostEqual(y, -9396.0, places=2)

    def test_what_was_not_stands_in_its_place(self):
        x, y, _ = self.at("Kept")
        self.assertAlmostEqual(x, 30902.0, places=2)
        self.assertAlmostEqual(y, -9400.0, places=2)

    def scripts(self):
        # each guard's AI task, with the script written for it
        src = self.source()
        out = {}
        for name in ("On the alarm", "Off the alarm"):
            i = src.index('"%s"' % name)
            aid = re.search(r'Task_New\((\d+), "HumanAI"', src[i:]).group(1)
            out[name] = (self.dir / "out" / "ai" / (aid + ".qsc")).read_text(encoding="latin-1")
        return out

    def test_a_guard_off_the_alarm_is_told_to_answer_none(self):
        s = self.scripts()
        self.assertIn("SetAlarmControlID", s["On the alarm"])
        self.assertNotIn("SetAlarmControlID", s["Off the alarm"])
        self.assertNotIn("ALARMON", s["Off the alarm"])

    def test_a_raised_hill_takes_the_walkways_on_it_up(self):
        nx, ny = self.row
        area = {"uid": "hill", "mode": "raise", "x": nx + 14, "y": ny, "w": 30, "h": 30, "delta": 15, "angle": 0, "round": True, "auto": True, "blend": 12}
        run = self.build(dict(self.plan, ground=[area]), "hill")
        self.assertEqual(run.returncode, 0, run.stdout[-1500:])
        self.assertRegex(run.stdout, r"walkway point.*(follow the shaped ground|on the shaped ground)")
        # (taken away again, nothing is left over from it: each build starts from where they were laid)
        self.assertNotIn("follow the shaped ground", self.first.stdout)


@unittest.skipUnless((GAME / "missions" / "location0" / "level1" / "terrain").exists(), "no game here")
class ALevelsOwnGuard(unittest.TestCase):
    """A guard the level has, on an alarm the level has."""

    @classmethod
    def setUpClass(cls):
        m = json.loads((paths.data() / "level1.json").read_text(encoding="utf-8"))
        on_alarm = {g for a in m.get("alarms") or [] for g in a.get("guards") or []}
        soldiers = [o for o in m["objects"] if o.get("type") == "soldier" and o.get("id") in on_alarm and o.get("ref")]
        cls.off = soldiers[0]
        cls.walker = next(o for o in soldiers[1:] if isinstance(o.get("idlePath"), int))
        cls.dir = pathlib.Path(tempfile.mkdtemp())
        edit = lambda o, **f: dict({"ref": o["ref"], "type": "soldier", "qtype": o.get("qtype"), "id": o["id"], "name": o.get("name") or "guard"}, **f)
        plan = {"name": "Probe", "base": {"level": 1, "kind": "copy"}, "placements": [], "nodes": [], "nodeEdits": [],
                "edits": [edit(cls.off, alarmId="none"), edit(cls.walker, patrol=[], patrolCmds=[], graph=str(cls.walker.get("graph")))],
                "removeRefs": [], "removals": [], "objectives": [], "ground": [], "brush": [], "sculpt": [], "events": [], "paint": [], "textures": [],
                "cutscenes": [], "failOnAlarm": False, "objBase": True, "ccwLying": True, "settings": {}, "levelScenes": {}, "levelVehicles": {}}
        pf = cls.dir / "plan.json"
        pf.write_text(json.dumps(plan), encoding="utf-8")
        cls.run_ = subprocess.run([sys.executable, "-W", "ignore", "-m", "studio.build.plan", "--plan", str(pf), "--out", str(cls.dir / "out"), "--game", str(GAME)],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT), timeout=300)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def script_of(self, o):
        src = (self.dir / "out" / "objects.qsc").read_text(encoding="latin-1")
        i = re.search(r'Task_New\(%d, "HumanSoldier"' % o["id"], src).start()
        aid = re.search(r'Task_New\((\d+), "HumanAI"', src[i:]).group(1)
        return (self.dir / "out" / "ai" / (aid + ".qsc")).read_text(encoding="latin-1")

    def test_it_built(self):
        self.assertEqual(self.run_.returncode, 0, self.run_.stdout[-1500:])

    def test_off_the_alarm_his_script_no_longer_answers_it(self):
        self.assertNotIn("SetAlarmControlID", self.script_of(self.off))

    def test_without_his_patrol_he_is_still_on_it(self):
        self.assertIn("SetAlarmControlID", self.script_of(self.walker))


@unittest.skipUnless(HAS_NODE, "no node here")
class TheStudiosOwnCheckOfWalkways(unittest.TestCase):
    def run_it(self, body):
        html = page()
        grid = """var TERR={h0:"before",h:"now"},INSIDE=false;
function zOn(H,x,y){return H==="before"?100:(x>50?120:100)}
function buildingAt(){return INSIDE}
"""
        return node(grid + js_function(html, "walkZ") + js_function(html, "aWalkUpTheSlope") + body)

    def test_one_under_a_raised_hill_stands_on_it(self):
        self.assertEqual(self.run_it("console.log(JSON.stringify(walkZ({x:60,y:0,z:100})));"), 120)

    def test_one_on_ground_nobody_moved_stays(self):
        self.assertEqual(self.run_it("console.log(JSON.stringify(walkZ({x:10,y:0,z:100})));"), 100)

    def test_indoors_the_floors_decide(self):
        self.assertEqual(self.run_it("INSIDE=true;console.log(JSON.stringify(walkZ({x:60,y:0,z:100})));"), 100)

    def test_one_on_a_tower_on_the_hill_stays(self):
        self.assertEqual(self.run_it("console.log(JSON.stringify(walkZ({x:60,y:0,z:150})));"), 150)

    def test_a_walk_up_the_slope_is_not_another_floor(self):
        self.assertTrue(self.run_it("console.log(JSON.stringify(aWalkUpTheSlope({x:60,y:0,z:120},{x:10,y:0,z:100})));"))

    def test_on_a_roof_it_is(self):
        self.assertFalse(self.run_it("console.log(JSON.stringify(aWalkUpTheSlope({x:60,y:0,z:125},{x:10,y:0,z:100})));"))

    def test_the_builds_dry_run_has_the_last_word(self):
        self.assertIn("if(near.dz>SAME_FLOOR&&buildVerdict()){}", page())


if __name__ == "__main__":
    unittest.main()
