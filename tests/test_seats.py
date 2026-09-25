import unittest

from studio.build import surface
from studio.extract import seats


class SeatTests(unittest.TestCase):
    def test_a_seat_read_from_the_levels_wins(self):
        # the big warehouse: 3.2 m into the ground, its floor the yard's
        self.assertEqual(surface.seat_of({"428_01_1": {"z0": 1.96, "seat": -3.22}}, "428_01_1"), -3.22)
        # a barracks: its origin at the ground, 11 m of cellar below it
        self.assertEqual(surface.seat_of({"403_01_1": {"z0": -11.08, "seat": 0.0}}, "403_01_1"), 0.0)

    def test_without_one_a_model_stands_on_its_lowest_point(self):
        self.assertAlmostEqual(surface.seat_of({"m": {"z0": -0.64}}, "m"), 0.64)
        # a base plate of a few cm is not stood on
        self.assertEqual(surface.seat_of({"m": {"z0": -0.05}}, "m"), 0.0)
        self.assertEqual(surface.seat_of({}, "unknown"), 0.0)

    def test_the_copies_most_of_which_agree(self):
        self.assertAlmostEqual(seats.consensus([-3.29, -3.22, -2.99]), -3.22)
        self.assertAlmostEqual(seats.consensus([0.01, -0.01, 0.0, 3.0]), 0.0)
        self.assertEqual(seats.consensus([0.3]), 0.3)

    def test_no_majority_no_seat(self):
        self.assertIsNone(seats.consensus([0.0, 5.0]))
        self.assertIsNone(seats.consensus([0.0, 0.1, 4.0, 4.1]))


if __name__ == "__main__":
    unittest.main()
