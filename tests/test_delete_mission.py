"""Deleting a mission: one Delete takes it out of the studio and out of the game,
for good (studio/server/app.py delete_mission, studio/build/slots.py delete_slot).
A mission in the game that the studio no longer holds is deleted from its row in
the library (slot_remove), and the same way.

Runs on a game folder made up for it: two slots the studio made, nothing else of
the game. Nothing is written outside the test's own folders."""
import json, os, pathlib, shutil, tempfile, unittest
from unittest import mock


def _define(n, name, base):
    return ('DefineMission(%d, "%s", "", "", MISSION_NEXT_MISSION_UNDEFINED, "missions/location0/level%d", '
            '"missions/location0/common", "missions/location0/level%d", "location0", "level%d", "mission%d.spr");\r\n'
            % (n, name, n, n, base, base))


class DeleteMissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="igi-delete-"))
        self.home, self.game = self.tmp / "home", self.tmp / "game"
        self.home.mkdir()
        (self.home / "config.json").write_text(json.dumps({"gamePath": str(self.game)}), encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"IGISTUDIO_HOME": str(self.home)})
        self.env.start()
        from studio import paths
        from studio.build import slots as SL
        from studio.qvm import write as QW
        from studio.server import app, missions as MS
        self.SL, self.MS, self.app = SL, MS, app
        # everything the studio writes goes into the test's folder, never the checkout's backups
        # (which hold the restore points of the game a dev window applies to)
        self.patches = [mock.patch.object(paths, "writable", lambda: self.home),
                        mock.patch.object(paths, "backups", lambda: self.home / "backups"),
                        mock.patch.object(MS, "STORE", self.home / "missions" / "custom"),
                        mock.patch.object(MS, "TRASH", self.home / "missions" / "custom" / ".trash"),
                        mock.patch.object(app, "game_running", lambda: False)]
        for p in self.patches:
            p.start()
        MS.STORE.mkdir(parents=True)
        # the game: slots 15 and 16, made by the studio
        for n, mid, name in ((15, "raid-111111", "Raid"), (16, "old-222222", "Old One")):
            d = self.game / "missions" / "location0" / ("level%d" % n)
            d.mkdir(parents=True)
            (d / "mission.qvm").write_bytes(QW.compile_text(_define(n, name, 4)))
            (d / "objects.qvm").write_bytes(b"x")
            (d / "_mission_studio.json").write_text(json.dumps(
                {"missionId": mid, "name": name, "mission": {"id": mid, "name": name, "plan": {"placements": []}}}),
                encoding="utf-8")
            for kind in ("models", "graphs"):           # an Apply's restore points for the slot
                r = self.home / "backups" / kind / ("level%d" % n)
                r.mkdir(parents=True)
                (r / "kept.bin").write_bytes(b"x")
        # the studio holds the first of them
        m = MS.create("Raid", 4, "copy", "")
        os.rename(MS.STORE / m["id"], MS.STORE / "raid-111111")
        raw = json.loads((MS.STORE / "raid-111111" / "mission.json").read_text(encoding="utf-8"))
        raw["id"] = "raid-111111"
        (MS.STORE / "raid-111111" / "mission.json").write_text(json.dumps(raw), encoding="utf-8")

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def slot(self, n):
        return self.game / "missions" / "location0" / ("level%d" % n)

    def test_delete_takes_it_out_of_the_studio_and_the_game_for_good(self):
        r = self.app.delete_mission("raid-111111")
        self.assertTrue(r["ok"])
        self.assertEqual(r["slots"], [15])
        self.assertFalse(self.slot(15).exists())                                   # out of the game
        self.assertFalse((self.MS.STORE / "raid-111111").exists())                  # out of the studio
        self.assertFalse(self.MS.TRASH.exists() and any(self.MS.TRASH.iterdir()))   # and not in a trash
        for kind in ("models", "graphs"):                                          # nothing kept of its slot
            self.assertFalse((self.home / "backups" / kind / "level15").exists())
        self.assertFalse((self.home / "backups" / "slots").exists())
        # the other mission in the game is left as it was
        self.assertTrue(self.slot(16).exists())
        self.assertTrue((self.home / "backups" / "models" / "level16").exists())

    def test_a_slot_is_found_by_its_marker_not_by_the_missions_record(self):
        # the mission's own record says another slot (it was moved in the game since): the game decides
        self.MS.save("raid-111111", plan={"placements": []})
        raw = json.loads((self.MS.STORE / "raid-111111" / "mission.json").read_text(encoding="utf-8"))
        raw["slot"] = 16
        (self.MS.STORE / "raid-111111" / "mission.json").write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(self.app.delete_mission("raid-111111")["slots"], [15])
        self.assertFalse(self.slot(15).exists())
        self.assertTrue(self.slot(16).exists())

    def test_not_while_the_game_runs(self):
        with mock.patch.object(self.app, "game_running", lambda: True):
            r = self.app.delete_mission("raid-111111")
        self.assertFalse(r["ok"])
        self.assertTrue(self.slot(15).exists())
        self.assertTrue((self.MS.STORE / "raid-111111").exists())

    def test_a_mission_not_in_the_game_is_simply_deleted(self):
        m = self.MS.create("Draft", 3, "copy", "")
        self.assertEqual(self.app.delete_mission(m["id"])["slots"], [])
        self.assertFalse((self.MS.STORE / m["id"]).exists())
        self.assertTrue(self.slot(15).exists() and self.slot(16).exists())

    def test_a_mission_in_the_game_but_not_in_the_studio_is_deleted_from_its_row(self):
        r = self.app.slot_remove(16)
        self.assertTrue(r["ok"])
        self.assertFalse(self.slot(16).exists())
        self.assertFalse((self.home / "backups" / "models" / "level16").exists())
        self.assertTrue(self.slot(15).exists())

    def test_one_of_yours_is_deleted_from_its_card_not_its_row(self):
        r = self.app.slot_remove(15)
        self.assertFalse(r["ok"])
        self.assertTrue(self.slot(15).exists())

    def test_the_built_in_missions_cannot_be_deleted(self):
        d = self.game / "missions" / "location0" / "level4"
        d.mkdir(parents=True)
        (d / "mission.qvm").write_bytes(b"x")
        from studio import protect
        with self.assertRaises(protect.ProtectedPath):
            self.SL.delete_slot(str(self.game), 4, log=lambda x: None)
        self.assertTrue(d.exists())


if __name__ == "__main__":
    unittest.main()
