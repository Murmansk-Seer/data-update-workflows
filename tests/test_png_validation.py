import struct
import tempfile
import unittest
from pathlib import Path
import zlib

from scripts.seer_unity_assets.png_validation import validate_changed_pngs, validate_png


def chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))


def png() -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00\xff")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


class PngValidationTests(unittest.TestCase):
    def test_valid_png_and_changed_file_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "newseer/assets/pet/body/1.png"
            path.parent.mkdir(parents=True)
            path.write_bytes(png())
            self.assertEqual(validate_changed_pngs(root, ["newseer/assets/pet/body/1.png", "other.png"]), 1)

    def test_crc_damage_blocks_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.png"
            content = bytearray(png())
            content[46] ^= 1
            path.write_bytes(content)
            with self.assertRaisesRegex(ValueError, "Invalid PNG image data|checksum mismatch"):
                validate_png(path)

    def test_truncation_blocks_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.png"
            path.write_bytes(png()[:-7])
            with self.assertRaises(ValueError):
                validate_png(path)


if __name__ == "__main__":
    unittest.main()
