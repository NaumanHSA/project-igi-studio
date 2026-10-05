import unittest

from studio.extract import motion

# a level script cut down to what motion.py reads: an intro with two cameras
# and a subtitle, a skip key, an outro the level ends on, an APC the AI drives
# on the alarm, and a helicopter on a recorded drive in the intro
SCRIPT = r'''
Task_New(-1, "Container", "",
  Task_New(4004, "EditVariable", "", 0, 0, 0, 0, "EditVariable_4004.nValue == 0 && LevelFlow_GetBreakCutSceneKey()", ""),
  Task_New(4001, "ConditionalContainer", "Intro cutscene", "!CutScene_1200.isFinished && !EditVariable_4004.nValue", "MenuManager_SetEnabled(FALSE)", "MenuManager_SetEnabled(TRUE)",
    Task_New(1502, "Heli", "", 4096, 8192, 12288, 0, 0, 1.5708, 0, 0, 0, 0, "709_01_1", TRUE, FALSE, "", "", "", 180, 360, 30),
    Task_New(-1, "AnimTask", "", 0, 0, 0, 0, 0, 0, 1502, "CutScene_1200.isRun", FALSE, 3, 0, 1, 32, 60, 32, 30),
    Task_New(999, "LevelTimer", "", 0, 0, 0, 0, 0, 0, "ConditionalContainer_4001.isRun", "", FALSE),
    Task_New(998, "StatusMessage", "", 0, 0, 0, 0, 0, 0, "LevelTimer_999.nTick > 2*GAME_FREQUENCY", "M1_CUT_01", "", "", TRUE, TRUE, 3.5),
    Task_New(1200, "CutScene", "Insertion", 0, 0, 0, 0, 0, 0, "!CutScene_1200.isFinished", "", "", 0, FALSE, 1, 0.7, 0, 0, 0, "", "",
      Task_New(-1, "EditCamera", "Wide", 40960, 0, 409600, -3.14159, 0, 0, 1, 4.0, -1, TRUE, -1, TRUE, TRUE, -1, "CAMERAFILTER_TYPE_NONE", 0, 0, 0, 0, 0),
      Task_New(-1, "EditCamera", "Wide", 40960, 0, 409600, -3.14159, 0, 0, 0.5, 0, -1, TRUE, -1, TRUE, FALSE, -1, "CAMERAFILTER_TYPE_LINE", 0, 0, 0, 0, 0.01))),
  Task_New(4007, "ConditionalContainer", "Outro Cutscene", "EditVariable_199.nValue == 1 && !CutScene_1204.isFinished", "Game_CutsceneDelete()", "",
    Task_New(1204, "CutScene", "", 0, 0, 0, 0, 0, 0, "!CutScene_1204.isFinished", "", "", 0, FALSE, 1, 0.7, 0, 0, 0, "", "",
      Task_New(-1, "EditCamera", "Out", 0, 0, 0, -1.5708, 0, 0.5, 1, 6.0, -1, TRUE, 800, TRUE, FALSE, -1, "CAMERAFILTER_TYPE_NONE", 0, 0, 0, 0, 0))),
  Task_New(350, "ConditionalContainer", "APC", "AlarmControl_98.isAlarm || this.isRun", "", "",
    Task_New(800, "Car", "APC", 409600, 0, 0, 0, 0, 1.5708, 0, 0, 0, 0, "601_01_1", TRUE, FALSE, "", "1", "", 180, 360, 50,
      Task_New(850, "CarAI", "", 800, 1, 602))),
  Task_New(602, "PatrolPath", "APC path",
    Task_New(-1, "PatrolPathCommand", "", 2, 1),
    Task_New(-1, "PatrolPathCommand", "", 1, 30),
    Task_New(-1, "PatrolPathCommand", "", 3, 9)));
Task_New(10, "LevelFlow", "", 0, 0, 0, 0, 0, 0, 0, "CutScene_1204.isFinished", "HumanPlayer_0.isDead", FALSE, 0);
'''


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = motion.read(SCRIPT, {"M1_CUT_01": "ANYA: Good work."})

    def test_the_intro_its_skip_key_and_its_cameras(self):
        intro = self.m["cutscenes"][0]
        self.assertEqual((intro["id"], intro["role"], intro["skip"], intro["ends"]), (4001, "intro", 4004, False))
        shots = intro["scenes"][0]["shots"]
        self.assertEqual([s["dur"] for s in shots], [4.0, 0.0])
        self.assertTrue(shots[0]["smooth"])
        self.assertEqual((shots[0]["x"], shots[0]["z"]), (10.0, 100.0))       # metres
        self.assertEqual(shots[1].get("filter"), "line")
        self.assertEqual(shots[1].get("shake"), 0.01)
        self.assertEqual(intro["scenes"][0]["letterbox"], 0.7)
        self.assertEqual(intro["seconds"], 4.0)

    def test_subtitles_on_the_intro_timer_with_their_text(self):
        self.assertEqual(self.m["cutscenes"][0]["subtitles"],
                         [{"at": 2.0, "dur": 3.5, "key": "M1_CUT_01", "text": "ANYA: Good work."}])

    def test_the_outro_ends_the_mission(self):
        outro = self.m["cutscenes"][1]
        self.assertEqual((outro["role"], outro["ends"], outro["skip"]), ("outro", True, None))
        self.assertEqual(outro["scenes"][0]["shots"][0]["target"], 800)

    def test_an_ai_vehicle_its_route_and_when_it_comes(self):
        apc = [v for v in self.m["vehicles"] if v["id"] == 800][0]
        self.assertEqual(apc["ai"], {"graph": 1, "route": 602, "nodes": [1, 9]})
        self.assertEqual(apc["when"], "AlarmControl_98.isAlarm || this.isRun")
        self.assertEqual(apc["rot"][2], 1.5708)          # its heading, not its speed
        self.assertEqual(apc["canFire"], "1")

    def test_a_recorded_drive_in_game_ticks(self):
        heli = [v for v in self.m["vehicles"] if v["id"] == 1502][0]
        self.assertEqual(heli["cutscene"], 4001)
        self.assertEqual(heli["drives"][0]["seconds"], 3.0)      # 90 ticks at 30 a second
        self.assertEqual(heli["drives"][0]["run"], "CutScene_1200.isRun")


if __name__ == "__main__":
    unittest.main()
