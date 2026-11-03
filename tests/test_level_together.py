"""Everything you place on the ground levels it, and what stands close together shares
one height (studio/build/flatten.py level_together): the game's own missions stand on
level ground, and a fence on uneven ground was buried in places and above it in others
(2026-11-03). The editor does the same sums to show that ground (plotter.html
levelTogether): held to the same answers here."""
import json, pathlib, shutil, subprocess, unittest

from studio.build import flatten as FL

ROOT = pathlib.Path(__file__).resolve().parent.parent


def pad(x, zs, width=16.0, gate=None, fixed=None, y=0.0):
    """A panel along x from (x, y), the ground under it being zs."""
    n = len(zs)
    pts = [(x + width * i / max(1, n - 1), y) for i in range(n)]
    reach = FL.FLAT + FL.BLEND
    srt = sorted(zs)
    return {"name": "p", "x": x, "y": y, "c": 1.0, "s": 0.0, "rects": [[0.0, -0.25, width, 0.5]], "zs": srt, "pts": pts,
            "gate": gate, "fixed": fixed is not None, "target": fixed if fixed is not None else srt[len(srt) // 2],
            "box": (x - reach, x + width + reach, y - 0.25 - reach, y + 0.25 + reach)}


class Together(unittest.TestCase):
    def targets(self, pads):
        FL.level_together(pads)
        return [p["target"] for p in pads]

    def test_a_run_of_fence_stands_at_one_height(self):
        t = self.targets([pad(0, [10, 11, 12]), pad(16, [12, 12.5, 13]), pad(32, [13, 12, 11])])
        self.assertEqual(len(set(t)), 1)
        self.assertTrue(10 <= t[0] <= 13)

    def test_far_apart_each_keeps_its_own(self):
        t = self.targets([pad(0, [10, 10, 10]), pad(100, [20, 20, 20])])
        self.assertEqual(t, [10, 20])

    def test_a_run_up_a_real_slope_steps_where_the_ground_changes_most(self):
        t = self.targets([pad(0, [10, 10.5, 11]), pad(16, [11, 11.5, 12]), pad(32, [20, 20.5, 21]), pad(48, [21, 21.5, 22])])
        self.assertEqual(t[0], t[1])
        self.assertEqual(t[2], t[3])
        self.assertNotEqual(t[1], t[2])

    def test_no_group_spreads_further_than_it_may(self):
        t = self.targets([pad(16 * i, [10 + i * 1.5] * 3) for i in range(8)])
        for a, b in zip(t, t[1:]):
            self.assertLess(abs(a - b), FL.LEVEL_SPREAD + 2)
        self.assertGreater(len(set(t)), 1)

    def test_the_leaves_of_a_gate_always_share_it(self):
        t = self.targets([pad(0, [10] * 3, width=4, gate="sw"), pad(40, [30] * 3, width=4, gate="sw")])
        self.assertEqual(t[0], t[1])

    def test_a_thing_put_down_by_hand_stays_and_nothing_joins_it(self):
        t = self.targets([pad(0, [10, 11, 12], fixed=15.0), pad(16, [11, 11, 11])])
        self.assertEqual(t, [15.0, 11])


class TheGroundBetween(unittest.TestCase):
    def sample(self, pads, x, keeps=()):
        g = FL._sample(pads, list(keeps), {}, False, x, 0.0, 64.0, lambda: 0.0)[0]
        return 0.0 if g is None else g           # nothing touched it: the level's own, 0 here

    def real(self, x, target):
        p = pad(x, [target] * 3)
        p["target"] = target
        return p

    def test_a_pad_holds_its_own_footprint(self):
        a, b = self.real(0, 10.0), self.real(16, 12.0)
        self.assertAlmostEqual(self.sample([a, b], 8.0), 10.0, delta=0.05)
        self.assertAlmostEqual(self.sample([a, b], 24.0), 12.0, delta=0.05)

    def test_no_step_where_two_meet(self):
        a, b = self.real(0, 10.0), self.real(16, 12.0)
        last, most = None, 0.0
        for i in range(0, 121):
            z = self.sample([a, b], 10.0 + i * 0.1)
            if last is not None:
                most = max(most, abs(z - last))
            last = z
        # 2 m between two pads that touch comes in a metre or two, not at once
        self.assertLess(most, 0.4, "a step of %.2f m between two samples 10 cm apart" % most)

    def test_it_eases_back_over_five_metres(self):
        a = self.real(0, 10.0)
        self.assertAlmostEqual(self.sample([a], 16.0 + FL.FLAT), 10.0, delta=0.01)
        self.assertGreater(self.sample([a], 16.0 + FL.FLAT + FL.BLEND / 2), 1.0)
        self.assertAlmostEqual(self.sample([a], 16.0 + FL.FLAT + FL.BLEND), 0.0, delta=0.01)

    def test_what_a_thing_of_the_levels_own_stands_on_stays(self):
        a = self.real(0, 10.0)
        k = FL.keep_for({"x": 8.0, "y": 0.0, "gamma": 0.0, "model": "x"}, {})
        k["world"] = True
        self.assertEqual(self.sample([a], 8.0, [k]), 0.0)
        k["world"] = False              # one of yours, a pickup: it goes with the ground
        self.assertAlmostEqual(self.sample([a], 8.0, [k]), 10.0, delta=0.01)


@unittest.skipUnless(shutil.which("node"), "no node here")
class TheEditorAgrees(unittest.TestCase):
    def source(self, name, html):
        i = html.index("function %s(" % name)
        return html[i:html.index("\n}\n", i) + 3]

    def test_the_same_answers(self):
        html = (ROOT / "editor" / "plotter.html").read_text(encoding="utf-8").replace("\r\n", "\n")
        cases = [
            [pad(0, [10, 11, 12]), pad(16, [12, 12.5, 13]), pad(32, [13, 12, 11])],
            [pad(0, [10, 10.5, 11]), pad(16, [11, 11.5, 12]), pad(32, [20, 20.5, 21]), pad(48, [21, 21.5, 22])],
            [pad(16 * i, [10 + i * 1.5, 10.3 + i * 1.5, 9.8 + i * 1.5]) for i in range(8)],
            [pad(0, [10] * 3, width=4, gate="sw"), pad(40, [30] * 3, width=4, gate="sw"), pad(46, [29] * 3)],
            [pad(0, [10, 11, 12], fixed=15.0), pad(16, [11, 11, 11]), pad(0, [11, 12], y=8.0), pad(0, [30, 30], y=40.0)],
        ]
        js = ("var LEVEL_NEAR=%r,LEVEL_SPREAD=%r;\n" % (FL.LEVEL_NEAR, FL.LEVEL_SPREAD) + self.source("padDist", html) +
              self.source("levelTogether", html) +
              "var cases=%s;\ncases.forEach(levelTogether);\n"
              "console.log(JSON.stringify(cases.map(function(c){return c.map(function(p){return p.target})})));\n"
              % json.dumps(cases))
        out = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        for pads in cases:
            FL.level_together(pads)
        self.assertEqual(json.loads(out.stdout), [[p["target"] for p in c] for c in cases])

    def test_the_same_figures(self):
        html = (ROOT / "editor" / "plotter.html").read_text(encoding="utf-8")
        self.assertIn("PAD_FLAT=%s,PAD_BLEND=%s,LEVEL_NEAR=%s,LEVEL_SPREAD=%s,ON_GROUND=%s,FLAT_ENOUGH=%s"
                      % (FL.FLAT, FL.BLEND, FL.LEVEL_NEAR, FL.LEVEL_SPREAD, FL.ON_GROUND, FL.FLAT_ENOUGH), html)


if __name__ == "__main__":
    unittest.main()
