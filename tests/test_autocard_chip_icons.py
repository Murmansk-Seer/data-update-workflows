import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from scripts.seer_unity_assets.autocard_chips import (
    CHIP_ICON_DIRECTORY,
    CHIP_ICON_MANIFEST,
    atlas_sprite_image,
    chip_icon_file_is_current,
    chip_icons_are_current,
)


class ChipIconTests(unittest.TestCase):
    def test_atlas_rectangle_preserves_glyph_and_alpha(self):
        texture = Image.new("RGBA", (8, 8))
        texture.putpixel((3, 2), (255, 255, 255, 255))
        sprite = SimpleNamespace(m_RenderDataKey="key", m_Name="autocardChip_115")
        data = SimpleNamespace(
            texture=None,
            alphaTexture=None,
            settingsRaw=0,
            textureRect=SimpleNamespace(x=2, y=2, width=4, height=4),
        )
        atlas = SimpleNamespace(m_RenderDataMap=[("key", data)])
        with patch(
            "scripts.seer_unity_assets.autocard_chips.get_image", return_value=texture
        ):
            image = atlas_sprite_image(sprite, atlas)
        self.assertEqual(image.size, (4, 4))
        self.assertEqual(image.getpixel((1, 3)), (255, 255, 255, 255))
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0, 0))

    def test_current_manifest_requires_matching_version_and_all_files(self):
        document = {"schema_version": 1, "package_version": "v1", "sprite_ids": [115]}
        self.assertTrue(chip_icons_are_current(document, "v1"))
        self.assertFalse(chip_icons_are_current(document, "v2"))
        self.assertFalse(
            chip_icons_are_current(dict(document, sprite_ids=[115, 115]), "v1")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / CHIP_ICON_MANIFEST
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps(document), encoding="utf-8")
            self.assertFalse(chip_icon_file_is_current(root, "v1"))
            icon = root / CHIP_ICON_DIRECTORY / "autocardChip_115.png"
            icon.parent.mkdir(parents=True)
            Image.new("RGBA", (4, 4), "white").save(icon)
            self.assertTrue(chip_icon_file_is_current(root, "v1"))
