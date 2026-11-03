"""A fence panel or wall laid along the ground (studio/build/surface.py follow):
on a slope it was rested on the lowest ground under it, and a 16 m panel stood
metres deep at its uphill end (2026-11-03). Held here to where its ends really
are once the game turns it: alpha about x, then beta about y, then the heading."""
import math, unittest

from studio.build import surface as SF

SIZES = {
    # the game's long fence panel: its origin at one end, 16 m along x
    "303_02_1": {"w": 16.31, "d": 0.54, "h": 4.59, "cx": 7.96, "cy": 0.0, "z0": -0.161},
    # one along y, to hold the other angle
    "wall_y": {"w": 0.5, "d": 10.0, "h": 3.0, "cx": 0.0, "cy": 5.0, "z0": 0.0},
    "crate": {"w": 1.6, "d": 1.6, "h": 1.39, "cx": 0.0, "cy": 0.0, "z0": 0.0},
}


class Ground:
    def __init__(self, f):
        self.z = f


class Flat(SF.Surface):
    """A Surface over a made-up ground, nothing built on it."""
    def __init__(self, f):
        self.terrain, self._sizes = Ground(f), SIZES

    def height(self, x, y, near_z, reach_up=0.8, skip=None, trust_near=True):
        return "terrain", self.terrain.z(x, y)


def turned(p, alpha, beta, gamma):
    """A point of the model where the game puts it (x, y, z), its origin at 0."""
    x, y, z = p
    y, z = y * math.cos(alpha) - z * math.sin(alpha), y * math.sin(alpha) + z * math.cos(alpha)
    x, z = x * math.cos(beta) + z * math.sin(beta), -x * math.sin(beta) + z * math.cos(beta)
    x, y = x * math.cos(gamma) - y * math.sin(gamma), x * math.sin(gamma) + y * math.cos(gamma)
    return x, y, z


class FollowTests(unittest.TestCase):
    def ends_on_ground(self, model, ground, x, y, gamma, tol=0.05):
        s = Flat(ground)
        z, a, b, under = s.follow(model, x, y, gamma)
        seat = SF.seat_of(SIZES, model)
        along_x, lo, hi, mid = SF.segment(SIZES, model)
        for u in (lo, hi):
            px, py, pz = turned((u, mid, 0) if along_x else (mid, u, 0), a, b, gamma)
            self.assertAlmostEqual(z - seat + pz, ground(x + px, y + py), delta=tol)
        return a, b, under

    def test_a_panel_up_a_slope_has_both_ends_on_it(self):
        g = lambda x, y: 100 + 0.1 * x
        for gamma in (0.0, 0.7, math.pi / 2, math.pi, 4.0):
            a, b, under = self.ends_on_ground("303_02_1", g, 50, 20, gamma)
            self.assertLess(under, 0.05)

    def test_a_panel_along_y_too(self):
        g = lambda x, y: 10 - 0.12 * y
        for gamma in (0.0, 1.2, math.pi):
            self.ends_on_ground("wall_y", g, 5, 5, gamma)

    def test_across_a_slope_it_stands_level(self):
        g = lambda x, y: 100 + 0.1 * y
        z, a, b, under = Flat(g).follow("303_02_1", 0, 0, 0)
        self.assertEqual((a, b), (0.0, -0.0))

    def test_too_steep_it_tilts_no_further_and_is_let_in(self):
        g = lambda x, y: 0.4 * x
        z, a, b, under = Flat(g).follow("303_02_1", 0, 0, 0)
        self.assertAlmostEqual(b, -math.atan(SF.Surface.FOLLOW_SLOPE), places=4)
        self.assertGreater(under, 1.0)

    def test_over_a_dip_it_is_let_down_into_it(self):
        g = lambda x, y: -1.0 if 6 < x < 10 else 0.0
        z, a, b, under = Flat(g).follow("303_02_1", 0, 0, 0)
        seat = SF.seat_of(SIZES, "303_02_1")
        self.assertLessEqual(z - seat, -1.0 + SF.Surface.FOLLOW_OVER + 1e-6)

    def test_only_panels_and_walls(self):
        self.assertIsNone(Flat(lambda x, y: 0.0).follow("crate", 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
