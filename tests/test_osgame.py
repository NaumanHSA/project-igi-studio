# How the studio tells that the game runs, and how it starts it, off Windows.
import unittest
from unittest import mock

from studio import osgame as O


WINE = "/Applications/Wine Devel.app/Contents/Resources/wine/bin/wine-preloader"


@unittest.skipIf(O.WINDOWS, "Windows asks tasklist instead")
class RunningTests(unittest.TestCase):
    def running(self, procs):
        """procs: [(command line, the file the process really runs)]"""
        listed = [(i + 100, cmd) for i, (cmd, _) in enumerate(procs)]
        files = {i + 100: exe for i, (_, exe) in enumerate(procs)}
        with mock.patch.object(O, "_processes", return_value=listed), \
             mock.patch.object(O, "_program_file", side_effect=files.get):
            return O.running("IGI.exe")

    def test_the_game_under_wine_is_running(self):
        # as Wine names it: the Windows path, or the Mac path it was started with
        self.assertTrue(self.running([(r"C:\Program Files (x86)\Project IGI\IGI.exe Window", WINE)]))
        self.assertTrue(self.running([(r"Z:\Users\me\Documents\Project IGI\IGI.exe", WINE)]))
        self.assertTrue(self.running([("/Users/me/Documents/Project IGI/IGI.exe Window", WINE)]))

    def test_a_command_that_only_mentions_it_is_not(self):
        self.assertFalse(self.running([
            ("grep -i IGI.exe studio.log", "/usr/bin/grep"),
            ("/usr/bin/tail -f /Users/me/Documents/Project IGI/IGI.exe", "/usr/bin/tail"),
            ("python3 -c print('IGI.exe')", "/opt/homebrew/bin/python3"),
            (r"C:\windows\system32\notepad.exe C:\IGI\IGI.exe", WINE),
        ]))

    def test_nothing_running(self):
        self.assertFalse(self.running([]))


@unittest.skipIf(O.WINDOWS, "Windows starts the game itself")
class CommandTests(unittest.TestCase):
    def test_a_game_in_a_bottle_starts_in_that_bottle(self):
        with mock.patch.object(O, "wine", return_value="/opt/wine/bin/wine"):
            argv, env = O.command("/Users/me/.wine-igi/drive_c/IGI/IGI.exe", ["Window"])
        self.assertEqual(argv, ["/opt/wine/bin/wine", "/Users/me/.wine-igi/drive_c/IGI/IGI.exe", "Window"])
        self.assertEqual(env["WINEPREFIX"], "/Users/me/.wine-igi")

    def test_without_wine_it_says_what_to_install(self):
        with mock.patch.object(O, "wine", return_value=None):
            with self.assertRaises(OSError) as e:
                O.command("/Users/me/Documents/Project IGI/IGI.exe")
        self.assertIn("Wine was not found", str(e.exception))


if __name__ == "__main__":
    unittest.main()
