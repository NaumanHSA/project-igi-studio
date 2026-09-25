import unittest

from studio.build import taskargs


def alarm(n_after_hack):
    """An AlarmControl as the build writes one, with n_after_hack expressions
    after its hack time (the game's take two: trigger and alarm)."""
    tail = ['"!AlarmControl_7.isAlarm && (SCamera_3.isDetection)"', '"EditVariable_8.nValue == 1"'][:n_after_hack]
    return ('Task_New(7, "AlarmControl", "Camera alarm", 0, 0, 0, 0, 0, 0, "", "", 1, 0.5, 0.5, 1, 0, 5, 4, "", '
            '"explo_02_m", "1", 4.0, ' + ", ".join(tail) + ")")


class TaskArgsTests(unittest.TestCase):
    def test_an_alarm_with_all_its_parameters_passes(self):
        self.assertEqual(taskargs.mismatches(alarm(2) + ";"), [])

    def test_an_alarm_one_short_is_caught(self):
        # the camera alarm that stopped the game: "Too few parameters in line 0"
        bad = taskargs.mismatches(alarm(1) + ";")
        self.assertEqual(bad, [("AlarmControl", '"Camera alarm"', 20, (21,))])

    def test_nested_tasks_are_not_counted_as_parameters(self):
        src = ('Task_New(-1, "Container", "Root", ' + alarm(2) + ", "
               'Task_New(8, "EditVariable", "Camera alarm state", 0, 0, 0, 0, "EditVariable_8.nValue == 0", ""));')
        self.assertEqual(taskargs.mismatches(src), [])

    def test_strings_with_commas_and_brackets_are_one_parameter(self):
        src = ('Task_New(8, "EditVariable", "x, (y)", 0, 0, 0, 0, '
               '"EditVariable_8.nValue == 0 && (A_1.isDead || B_2.isDead), \\"q\\"", "");')
        self.assertEqual(taskargs.mismatches(src), [])

    def test_kinds_the_table_does_not_know_are_left_alone(self):
        self.assertEqual(taskargs.mismatches('Task_New(9, "SomethingNew", "", 1);'), [])

    def test_every_count_is_a_whole_number(self):
        for kind, n in taskargs.COUNTS.items():
            self.assertIsInstance(n, int, kind)
            self.assertGreaterEqual(n, 0, kind)


if __name__ == "__main__":
    unittest.main()
