import struct
import unittest

from studio.build import models


def name_chunk(name, align=4):
    """A NAME chunk as the game's archives have them: tag, length, alignment,
    next, then the name with its terminator, padded to the alignment."""
    payload = name.encode("latin1") + b"\x00"
    padded = payload + b"\x00" * (-len(payload) % align)
    return b"NAME" + struct.pack("<III", len(payload), align, 0) + padded


class ImportedTextureNameTests(unittest.TestCase):
    def test_free_name_keeps_the_shape_and_counts_down_from_99(self):
        self.assertEqual(models._free_name("001_11_1", {"001_11_1"}), "001_99_1")
        self.assertEqual(models._free_name("001_11_1", {"001_11_1", "001_99_1"}), "001_98_1")

    def test_free_name_keeps_a_suffix(self):
        self.assertEqual(models._free_name("302_01_1_argb8888", set()), "302_99_1_argb8888")

    def test_free_name_gives_up_on_names_of_another_shape(self):
        self.assertIsNone(models._free_name("sky", set()))

    def test_renamed_chunk_keeps_its_size_and_path(self):
        nc = name_chunk("textures\\001_11_1.tex")
        out = models._renamed(nc, "001_11_1", "001_99_1")
        self.assertEqual(len(out), len(nc))
        self.assertEqual(out[:16], nc[:16])
        self.assertIn(b"textures\\001_99_1.tex", out)
        self.assertNotIn(b"001_11_1", out)

    def test_renamed_refuses_a_name_of_another_length(self):
        self.assertIsNone(models._renamed(name_chunk("001_11_1.tex"), "001_11_1", "001_9_1"))

    def test_payload_is_the_chunk_without_header_or_padding(self):
        body = b"LOOP" + b"\x01" * 9
        chunk = b"BODY" + struct.pack("<III", len(body), 4, 0) + body + b"\x00" * 3
        self.assertEqual(models._payload(chunk), body)


if __name__ == "__main__":
    unittest.main()
