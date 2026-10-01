"""Export the official S2 chip atlas without using stale tight-mesh UVs."""

from __future__ import annotations

import json
from pathlib import Path
import re

from PIL import Image
import UnityPy
from UnityPy.enums import SpritePackingRotation
from UnityPy.export.SpriteHelper import SpriteSettings, get_image

CHIP_ICON_DIRECTORY = "newseer/assets/game/ui/autocard/s2chip"
CHIP_ICON_MANIFEST = "newseer/derived/autocard_chip_icons.json"
CHIP_ICON_SCHEMA_VERSION = 1
_SPRITE_NAME = re.compile(r"autocardChip_([1-9][0-9]*)\Z")


def is_chip_bundle(path: Path) -> bool:
    return path.name in {"game_ui_autocard", "game_ui_autocard.bundle"}


def chip_icons_are_current(document: object, package_version: str) -> bool:
    if not isinstance(document, dict):
        return False
    ids = document.get("sprite_ids")
    return (
        document.get("schema_version") == CHIP_ICON_SCHEMA_VERSION
        and document.get("package_version") == package_version
        and isinstance(ids, list)
        and bool(ids)
        and all(type(value) is int and value > 0 for value in ids)
        and len(ids) == len(set(ids))
    )


def chip_icon_file_is_current(root: Path, package_version: str) -> bool:
    try:
        document = json.loads((root / CHIP_ICON_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not chip_icons_are_current(document, package_version):
        return False
    for value in document["sprite_ids"]:
        try:
            with Image.open(
                root / CHIP_ICON_DIRECTORY / f"autocardChip_{value}.png"
            ) as image:
                if image.format != "PNG":
                    return False
                image.load()
                if image.convert("RGBA").getchannel("A").getbbox() is None:
                    return False
        except (OSError, ValueError):
            return False
    return True


def atlas_sprite_image(sprite, atlas) -> Image.Image:
    data = next(
        value for key, value in atlas.m_RenderDataMap if key == sprite.m_RenderDataKey
    )
    texture = get_image(sprite, data.texture, data.alphaTexture)
    rect = data.textureRect
    image = texture.crop(
        (
            round(rect.x),
            round(rect.y),
            round(rect.x + rect.width),
            round(rect.y + rect.height),
        )
    )
    rotation = SpriteSettings(data.settingsRaw).packingRotation
    operations = {
        SpritePackingRotation.kSPRFlipHorizontal: Image.Transpose.FLIP_LEFT_RIGHT,
        SpritePackingRotation.kSPRFlipVertical: Image.Transpose.FLIP_TOP_BOTTOM,
        SpritePackingRotation.kSPRRotate180: Image.Transpose.ROTATE_180,
        SpritePackingRotation.kSPRRotate90: Image.Transpose.ROTATE_270,
    }
    if rotation in operations:
        image = image.transpose(operations[rotation])
    # Tight sprite UVs describe the source texture, not the packed atlas.
    # Cropping the atlas rectangle preserves the actual silhouette and alpha.
    image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert("RGBA")
    if image.getchannel("A").getbbox() is None:
        raise ValueError(f"Empty chip sprite: {sprite.m_Name}")
    return image


def extract_chip_icons(bundle: Path, root: Path, package_version: str) -> int:
    # Loading bytes avoids UnityPy retaining a Windows file handle in staging.
    env = UnityPy.load(bundle.read_bytes())
    atlas = next(
        (
            obj.read()
            for obj in env.objects
            if obj.type.name == "SpriteAtlas" and obj.read().m_Name == "s2Chip"
        ),
        None,
    )
    if atlas is None:
        raise ValueError("The autocard bundle has no s2Chip atlas")
    sprites = []
    for obj in env.objects:
        if obj.type.name != "Sprite":
            continue
        sprite = obj.read()
        if match := _SPRITE_NAME.fullmatch(sprite.m_Name):
            sprites.append((int(match[1]), sprite))
    if not sprites:
        raise ValueError("The s2Chip atlas has no chip sprites")
    ids = sorted(value for value, _sprite in sprites)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate chip sprite IDs")
    output = root / CHIP_ICON_DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    for value, sprite in sprites:
        atlas_sprite_image(sprite, atlas).save(output / f"autocardChip_{value}.png")
    for path in output.glob("autocardChip_*.png"):
        if match := _SPRITE_NAME.fullmatch(path.stem):
            if int(match[1]) not in ids:
                path.unlink()
    manifest = root / CHIP_ICON_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": CHIP_ICON_SCHEMA_VERSION,
                "package_version": package_version,
                "source_bundle": "game_ui_autocard",
                "source_atlas": "Assets/Game/UI/autocard/s2Chip.spriteatlas",
                "sprite_ids": ids,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return len(ids)
