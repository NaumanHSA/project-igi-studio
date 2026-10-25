"""The game's fixed-size task lists (studio/build/limits.py): what takes a place
in which, the map computer's markers made to fit, and the budget a mission is
held to so that none of them fills up ("QTaskList is full") in the game."""
import re, unittest

from studio.build import limits as L


def task(kind, tid=-1, name="x", rest=""):
    return 'Task_New(%d, "%s", "%s", 1.0, 2.0, 3.0%s)' % (tid, kind, name, rest)


def marker(name, sprite=""):
    return ('Task_New(-1, "ComputerHilight", "%s", 1.0, 2.0, 3.0, "1", "100", "%s", "MARKER_NONE", "MARKER_COLOR_NONE", "", "")'
            % (name, sprite))


def container(children):
    return 'Task_New(-1, "Container", "Computer Highlights", \n\t\t' + ", \n\t\t".join(children) + ")"


class LimitsTests(unittest.TestCase):
    def test_a_kind_takes_a_place_in_the_lists_of_the_types_it_is_made_from(self):
        src = ", ".join([task("HumanSoldierRPG"), task("HumanPlayer"), task("Terminal"), task("GunPickup"), task("Building")])
        u = L.usage(src)
        self.assertEqual(u["humans"], 2)                  # every kind of soldier, and the player
        self.assertEqual(u["dynamic"], 3)                 # the people, and a terminal (an ExplodeObject)
        self.assertEqual(u["objects"], 1)                 # the terminal again
        self.assertEqual(u["pickups"], 1)
        self.assertEqual(sum(u.values()), 7)              # a building takes no place in any

    def test_the_markers_fit_and_the_objectives_stay(self):
        labels = [marker("Label %d" % i) for i in range(30)]
        objectives = [marker("Objective %d" % i, "COMPUTER:h_%d.spr" % i) for i in range(1, 6)]
        src = container(labels[:20] + objectives + labels[20:])
        self.assertEqual(L.usage(src)["markers"], 35)
        out, gone = L.fit_markers(src)
        self.assertEqual(L.usage(out)["markers"], 32)
        self.assertEqual(gone, ["Label 27", "Label 28", "Label 29"])       # the last labels in the list
        self.assertEqual(len(re.findall(r"COMPUTER:h_", out)), 5)
        self.assertNotRegex(out, r",\s*,|,\s*\)")                          # the list is still a list
        self.assertTrue(out.endswith('"", "")' + ")"))

    def test_a_marker_with_an_id_is_never_taken(self):
        src = container([marker("Objective %d" % i, "COMPUTER:h_%d.spr" % i) for i in range(1, 4)] +
                        [marker("Label %d" % i).replace("Task_New(-1,", "Task_New(%d," % (500 + i)) for i in range(31)])
        out, gone = L.fit_markers(src)
        self.assertEqual(gone, [])
        self.assertEqual([p[0] for p in L.problems(out)], ["markers"])    # it is then the build's to refuse

    def test_the_budget(self):
        src = ", ".join(task("HumanSoldier") for _ in range(129))
        (key, what, used, room), = [p for p in L.problems(src) if p[0] == "humans"]
        self.assertEqual((used, room), (129, 128))
        # the game adds to two of them as it plays: room is kept for that
        self.assertEqual(L.room("dynamic"), 240)
        self.assertEqual(L.room("blasts"), 96)
        self.assertEqual(L.problems(", ".join(task("HumanSoldier") for _ in range(128))), [])

    def test_the_levels_as_they_ship_fit(self):
        from studio import paths
        from studio.qvm import read as QR
        base = paths.pristine() / "missions" / "location0"
        if not (base / "level1" / "objects.qvm").exists():
            self.skipTest("no copy of the game's levels here")
        for n in range(1, 15):
            src = QR.decompile(QR.parse(str(base / ("level%d" % n) / "objects.qvm")))
            self.assertEqual(L.problems(src), [], "level %d" % n)


if __name__ == "__main__":
    unittest.main()
