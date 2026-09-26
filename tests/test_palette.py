import pathlib, tempfile, unittest

from studio.build import models as M

HEADER = "*** This file is machine generated\r\n*** DO NOT EDIT!\r\n\r\n"


def level(tmp, dat_text, pal):
    d = pathlib.Path(tmp)
    (d / "level10.mtp").write_bytes(M.build_mtp(pal))
    (d / "level10.dat").write_text(dat_text, encoding="latin1", newline="")
    return M.level_files(d)


class PaletteTests(unittest.TestCase):
    PAL = {"header": HEADER, "models": [("100_01_1", ["100_01_1", "000_07_1"]), ("100_01_2", ["000_07_1"])],
           "textures": ["100_01_1", "000_07_1"], "tail": [], "newline": "\r\n"}

    def test_a_dat_that_compiles_to_the_mtp_is_the_palette(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = level(tmp, M.write_dat(self.PAL), self.PAL)
            d, why = M.palette(f)
            self.assertEqual((d["models"], why), (self.PAL["models"], ""))

    def test_a_stale_dat_gives_way_to_the_mtp(self):
        # level 10 ships a .dat that lists more models than it says it has
        stale = HEADER + "\r\n".join(["1", "100_01_1", "1", "100_01_1", "100_01_2", "1", "000_07_1", "1", "100_01_1"]) + "\r\n"
        with tempfile.TemporaryDirectory() as tmp:
            f = level(tmp, stale, self.PAL)
            with self.assertRaises((StopIteration, ValueError)):
                M.read_dat(f["dat"])
            d, why = M.palette(f)
            self.assertEqual(why, "")
            self.assertEqual(d["models"], self.PAL["models"])
            self.assertEqual(d["textures"], self.PAL["textures"])
            self.assertEqual(M.build_mtp(d), (pathlib.Path(tmp) / "level10.mtp").read_bytes())
            self.assertTrue(d["header"].startswith("*** This file is machine generated"))


if __name__ == "__main__":
    unittest.main()
