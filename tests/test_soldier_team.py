import unittest

from studio.build.objects import set_soldier_team


class SoldierTeamTests(unittest.TestCase):
    def setUp(self):
        self.task = (
            'Task_New(12, "HumanSoldier", "guard", 1, 2, 3, 0.5, '
            '"003_01_1", 1, 7, -1, '
            'Task_New(-1, "Gun", "", "WEAPON_ID_AK47", 0))'
        )

    def test_team_zero_makes_soldier_friendly(self):
        self.assertIn('"003_01_1", 0, 7', set_soldier_team(self.task, "003_01_1", 0))

    def test_team_one_keeps_enemy_default(self):
        self.assertEqual(self.task, set_soldier_team(self.task, "003_01_1", 1))

    def test_custom_team_id_is_written(self):
        self.assertIn('"003_01_1", 23, 7', set_soldier_team(self.task, "003_01_1", 23))

    def test_only_team_value_changes(self):
        updated = set_soldier_team(self.task, "003_01_1", 2)
        self.assertEqual(
            self.task.replace('"003_01_1", 1, 7', '"003_01_1", 2, 7'),
            updated,
        )

    def test_missing_model_fails_instead_of_silently_ignoring_edit(self):
        with self.assertRaises(ValueError):
            set_soldier_team(self.task, "missing-model", 2)


if __name__ == "__main__":
    unittest.main()
