"""Where a mission's own tasks go in a level's script (studio/build/splice.py):
beside the game's guards, never in a branch that waits for something - a
container that comes to life late in the mission, or a GuardGenerator - where
whatever is put would not be there when the mission is played."""
import re, unittest

from studio.build import splice as S


def soldier(tid, name=""):
    return 'Task_New(%d, "HumanSoldier", "%s", 1.0, 2.0, 3.0, 0, "001_01_1", 1, 1, -1, Task_New(-1, "Gun", "", "WEAPON_ID_AK47", 0))' % (tid, name)


def box(kind, name, kids, cond=None, tid=-1):
    args = '"%s", "", ""' % cond if kind == "ConditionalContainer" else ("5" if kind == "GuardGenerator" else "")
    head = 'Task_New(%d, "%s", "%s"%s' % (tid, kind, name, (", " + args) if args else "")
    return head + ", \n\t" + ", \n\t".join(kids) + ")"


PLAYER = 'Task_New(1, "HumanPlayer", "", 1.0, 2.0, 3.0, 0, "000_01_1", Task_New(-1, "Gun", "", "WEAPON_ID_M16A2", 0))'


def where(text):
    """The container the chosen offset is in, and the task that follows it."""
    at = S.pick(text)[1]
    chain = S.container_chain(text, at)
    return chain[-1][3], re.match(r'Task_New\((-?\d+)', text[at:]).group(1)


class SpliceTests(unittest.TestCase):
    def test_not_in_a_branch_that_waits_for_something(self):
        # level 8: the best-named guards wait for the SAM site; ours go beside that branch
        text = box("Dynamic", "", [PLAYER, box("Container", "AI", [box("Container", "HumanSoldier", [
            soldier(440, "Ammo building patroller"),
            box("ConditionalContainer", "SAM guard 442", [soldier(442, "SAM guard")],
                cond="AreaActivate_483.nActive && GenericPickup_870.isPickedUp || this.isRun", tid=452)])])])
        self.assertEqual(where(text), ("HumanSoldier", "440"))

    def test_not_inside_a_guard_generator(self):
        text = box("Dynamic", "", [PLAYER, box("Container", "AI", [box("Container", "Guards", [
            box("GuardGenerator", "Barracks Guard 429", [soldier(429)], tid=601)])])])
        self.assertEqual(where(text), ("Guards", "601"))

    def test_a_branch_that_only_waits_for_the_cutscenes_is_there_for_play(self):
        # level 2: the guards' container waits for the intro to end, written with a \n
        text = box("Dynamic", "", [
            box("ConditionalContainer", "Intro", [soldier(1505, "heli pilot")], cond="!CutScene_9.isFinished", tid=4002),
            box("ConditionalContainer", "Player", [PLAYER], cond="!ConditionalContainer_4002.isRun", tid=4001),
            box("ConditionalContainer", "", [box("Container", "AI", [box("Container", "Guards", [soldier(2000)])])],
                cond="!ConditionalContainer_4002.isRun\\n", tid=4012)])
        self.assertEqual(where(text), ("Guards", "2000"))

    def test_the_player_s_own_branch_is_there_for_play(self):
        text = box("Dynamic", "", [box("ConditionalContainer", "Main character", [
            PLAYER, box("Container", "AI", [box("Container", "Guards", [soldier(7)])])],
            cond="StatusMessage_1.isSendt || this.isRun", tid=3901)])
        self.assertEqual(where(text), ("Guards", "7"))

    def test_the_levels_as_they_ship(self):
        from studio import paths
        from studio.qvm import read as QR
        base = paths.pristine() / "missions" / "location0"
        if not (base / "level1" / "objects.qvm").exists():
            self.skipTest("no copy of the game's levels here")
        for n in range(1, 15):
            src = QR.decompile(QR.parse(str(base / ("level%d" % n) / "objects.qvm")))
            score, at, chain = S.pick(src)
            pm = re.search(r'Task_New\(-?\d+, "HumanPlayer", "', src)
            player = {c[0] for c in S.container_chain(src, pm.start())}
            enclosing = S.container_chain(src, at)
            live, stop = S.live_part(src, enclosing, player)
            self.assertIsNone(stop, "level %d: in %s" % (n, S.describe(enclosing)))
            # beside the level's own guards: the next of them is in the same container
            guard = re.compile(r'Task_New\(\d+, "HumanSoldier", "').search(src, at)
            self.assertIn(enclosing[-1], S.container_chain(src, guard.start()), "level %d" % n)


if __name__ == "__main__":
    unittest.main()
