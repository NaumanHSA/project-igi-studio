"""How the game's own levels are measured for agents (studio/extract/anatomy.py), and
that the pages stay in the person's own folder, made from their own game."""
import json, os, pathlib, shutil, tempfile, unittest

from studio.extract import anatomy as A


def thing(kind, x, y, **kw):
    return dict({"type": kind, "x": x, "y": y, "z": 0, "name": ""}, **kw)


def level():
    return {"level": 3, "bounds": {"minX": 0, "maxX": 1, "minY": 0, "maxY": 1}, "alarms": [{"id": 1}],
            "objectiveSets": [{"slots": [{"text": "Find the radar"}, {"text": "Get out"}]}],
            "objects": [thing("player", 0, 0),
                        # a camp: three guards, two buildings, a camera, and a door and a pickup beside them
                        thing("soldier", 100, 0, ai="AITYPE_GUARD_AK", weapon="WEAPON_ID_AK47"),
                        thing("soldier", 110, 0, ai="AITYPE_GUARD_AK", weapon="WEAPON_ID_AK47"),
                        thing("soldier", 120, 0, ai="AITYPE_SNIPER", weapon="WEAPON_ID_DRAGUNOV"),
                        thing("building", 105, 20, name="Barracks"), thing("building", 115, 20, name="HQ"),
                        thing("camera", 110, 10), thing("door", 106, 20), thing("pickup", 112, 8),
                        # a second place, 500 m away
                        thing("soldier", 600, 0, ai="AITYPE_GUARD_AK", weapon="WEAPON_ID_AK47"),
                        thing("building", 605, 10, name="Depot"), thing("building", 595, 10),
                        # only in a cutscene: not part of the level as it is played
                        thing("soldier", 110, 5, ai="AITYPE_GUARD_AK", cutscene=True),
                        thing("building", 300, 300, cutscene=True)]}


class MeasureTests(unittest.TestCase):
    def test_what_only_a_cutscene_uses_does_not_count(self):
        m = A.measure(level())
        self.assertEqual(m["guards"], 4)
        self.assertEqual(m["buildings"], 4)

    def test_the_counts(self):
        m = A.measure(level())
        self.assertEqual((m["cameras"], m["doors"], m["pickups"], m["alarm_systems"]), (1, 1, 1, 1))
        self.assertEqual(m["types"], {"AITYPE_GUARD_AK": 3, "AITYPE_SNIPER": 1})
        self.assertEqual(m["objectives"], ["Find the radar", "Get out"])
        self.assertEqual(m["first_guard_m"], 100)

    def test_things_that_stand_together_are_one_place(self):
        m = A.measure(level())
        self.assertEqual(len(m["places"]), 2)
        camp, depot = m["places"]
        self.assertEqual((camp["guards"], camp["buildings"], camp["cameras"]), (3, 2, 1))
        self.assertEqual(camp["names"], ["Barracks", "HQ"])
        self.assertEqual((camp["doors"], camp["pickups"]), (1, 1))
        self.assertEqual((depot["guards"], depot["buildings"]), (1, 2))
        self.assertGreater(m["between_places_m"], 400)

    def test_a_lone_thing_is_not_a_place(self):
        lv = level()
        lv["objects"].append(thing("soldier", 5000, 5000, ai="AITYPE_SNIPER"))
        self.assertEqual(len(A.measure(lv)["places"]), 2)

    def test_a_thing_far_off_the_map_does_not_make_the_level_look_huge(self):
        lv = level()
        for i in range(60):
            lv["objects"].append(thing("prop", i * 5, i * 5))
        lv["objects"].append(thing("prop", 900000, 900000))
        self.assertLess(max(A.measure(lv)["size_m"]), 2000)

    def test_a_level_with_nothing_in_it(self):
        m = A.measure({"objects": []})
        self.assertEqual((m["guards"], m["first_guard_m"], m["nearest_guard_m"], m["places"]), (0, None, None, []))
        self.assertIn("Level 1", A.level_page(1, {}, m))


class PageTests(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp(prefix="igi-an-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        self.data, self.out = self.d / "data", self.d / "guide"
        self.data.mkdir()
        (self.data / "level3.json").write_text(json.dumps(level()))
        (self.data / "builtins.json").write_text(json.dumps({"missions": [{"level": 3, "name": "Airbase", "environment": {"label": "Airfield", "when": "night"}}]}))

    def test_a_page_for_each_level_and_one_for_all(self):
        self.assertEqual(A.build(self.data, self.out), 1)
        self.assertEqual(sorted(p.name for p in self.out.glob("*.md")), ["level-3.md", "levels.md"])
        one = (self.out / "level-3.md").read_text(encoding="utf-8")
        self.assertIn("# Level 3: Airbase", one)
        self.assertIn("Barracks, HQ", one)
        self.assertIn("Find the radar", one)
        self.assertIn("Airbase", (self.out / "levels.md").read_text(encoding="utf-8"))

    def test_no_level_data_no_pages(self):
        self.assertEqual(A.build(self.d / "nothing", self.out), 0)
        self.assertFalse(self.out.exists())

    def test_a_broken_level_does_not_stop_the_rest(self):
        (self.data / "level5.json").write_text("{not json")
        self.assertEqual(A.build(self.data, self.out), 1)


class GuideTests(unittest.TestCase):
    def test_the_measured_pages_reach_read_guide_and_stay_in_the_person_s_folder(self):
        from studio.server import mcp as M
        d = pathlib.Path(tempfile.mkdtemp(prefix="igi-an-"))
        self.addCleanup(shutil.rmtree, d, True)
        was = os.environ.get("IGISTUDIO_HOME")
        os.environ["IGISTUDIO_HOME"] = str(d)
        self.addCleanup(lambda: os.environ.__setitem__("IGISTUDIO_HOME", was) if was else os.environ.pop("IGISTUDIO_HOME", None))
        (d / "data").mkdir()
        (d / "data" / "level3.json").write_text(json.dumps(level()))
        names = [g["name"] for g in M.guides()]
        self.assertIn("design", names)             # the written one, from the program
        self.assertIn("levels", names)             # the measured ones, made now
        self.assertIn("level-3", names)
        self.assertTrue((d / "guide" / "level-3.md").exists())

    def test_nothing_measured_is_in_the_repository(self):
        guide = pathlib.Path(__file__).resolve().parents[1] / "editor" / "guide"
        self.assertEqual([p.name for p in guide.glob("*.md") if p.name.startswith("level")], [])


if __name__ == "__main__":
    unittest.main()
