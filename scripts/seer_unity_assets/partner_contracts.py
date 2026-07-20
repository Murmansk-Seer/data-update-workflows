"""Extract contract-partner data from the official Unity ConfigPackage."""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Final


PARTNER_CONTRACTS_SCHEMA_VERSION: Final = 1
PARTNER_CONTRACTS_REPO_PATH: Final = "newseer/derived/partner_contracts.json"
PARTNER_ASSET_PATH: Final = "assets/game/configs/bytes/partner.bytes"
PARTNER_UPGRADE_ASSET_PATH: Final = (
    "assets/game/configs/bytes/partnerEffectUpgrade.bytes"
)
_MAX_COLLECTION_SIZE: Final = 100_000


class PartnerContractsError(ValueError):
    """Raised when the official contract configuration is malformed."""


class _BytesReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._position = 0

    @property
    def remaining(self) -> int:
        return len(self._data) - self._position

    def _require(self, size: int, label: str) -> None:
        if size < 0 or self.remaining < size:
            raise PartnerContractsError(
                f"Unexpected end of {label}: need {size} bytes, "
                f"have {self.remaining}"
            )

    def read_bool(self, label: str) -> bool:
        self._require(1, label)
        value = self._data[self._position]
        self._position += 1
        if value not in (0, 1):
            raise PartnerContractsError(f"Invalid boolean for {label}: {value}")
        return value == 1

    def read_i32(self, label: str) -> int:
        self._require(4, label)
        value = struct.unpack_from("<i", self._data, self._position)[0]
        self._position += 4
        return int(value)

    def read_u16(self, label: str) -> int:
        self._require(2, label)
        value = struct.unpack_from("<H", self._data, self._position)[0]
        self._position += 2
        return int(value)

    def read_text(self, label: str) -> str:
        length = self.read_u16(f"{label}.length")
        self._require(length, label)
        value = self._data[self._position : self._position + length]
        self._position += length
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PartnerContractsError(f"Invalid UTF-8 for {label}") from error

    def ensure_finished(self, label: str) -> None:
        if self.remaining:
            raise PartnerContractsError(
                f"Unexpected trailing bytes in {label}: {self.remaining}"
            )


def _read_count(reader: _BytesReader, label: str) -> int:
    count = reader.read_i32(label)
    if count < 0 or count > _MAX_COLLECTION_SIZE:
        raise PartnerContractsError(f"Invalid {label}: {count}")
    return count


def parse_partner_groups(data: bytes) -> list[dict[str, object]]:
    """Decode ``partner.bytes`` without passing binary data through UTF-8 text."""

    reader = _BytesReader(data)
    if not reader.read_bool("partner.present"):
        reader.ensure_finished("partner.bytes")
        return []

    groups: list[dict[str, object]] = []
    keys: set[int] = set()
    for index in range(_read_count(reader, "partner.count")):
        bitbuf = reader.read_i32(f"partner[{index}].bitbuf")
        source_id = reader.read_i32(f"partner[{index}].source_id")
        cost = reader.read_i32(f"partner[{index}].cost")
        key = reader.read_i32(f"partner[{index}].choice")
        has_members = reader.read_bool(f"partner[{index}].members.present")
        if not has_members:
            raise PartnerContractsError(f"partner[{index}] has no members")
        member_count = _read_count(reader, f"partner[{index}].members.count")
        member_pet_ids = [
            reader.read_i32(f"partner[{index}].members[{member_index}]")
            for member_index in range(member_count)
        ]
        name = reader.read_text(f"partner[{index}].name").strip()
        required_pet_count = reader.read_i32(
            f"partner[{index}].required_pet_count"
        )
        contract_type = reader.read_text(f"partner[{index}].type").strip()

        if key <= 0 or key in keys:
            raise PartnerContractsError(f"Invalid or duplicate contract key: {key}")
        if source_id <= 0 or cost < 0 or not name or not contract_type:
            raise PartnerContractsError(f"Invalid contract group at index {index}")
        if (
            not member_pet_ids
            or any(pet_id <= 0 for pet_id in member_pet_ids)
            or len(set(member_pet_ids)) != len(member_pet_ids)
        ):
            raise PartnerContractsError(f"Invalid members for contract group {key}")
        if required_pet_count < 0:
            raise PartnerContractsError(
                f"Invalid required pet count for contract group {key}"
            )

        keys.add(key)
        groups.append(
            {
                "key": key,
                "source_id": source_id,
                "type": contract_type,
                "name": name,
                "cost": cost,
                "member_pet_ids": member_pet_ids,
                "required_pet_count": required_pet_count,
                "bitbuf": bitbuf,
            }
        )

    reader.ensure_finished("partner.bytes")
    return groups


def parse_partner_upgrades(data: bytes) -> list[dict[str, object]]:
    """Decode ``partnerEffectUpgrade.bytes`` from its native binary format."""

    reader = _BytesReader(data)
    if not reader.read_bool("partnerEffectUpgrade.present"):
        reader.ensure_finished("partnerEffectUpgrade.bytes")
        return []

    upgrades: list[dict[str, object]] = []
    pet_ids: set[int] = set()
    for index in range(_read_count(reader, "partnerEffectUpgrade.count")):
        before_description = reader.read_text(
            f"partnerEffectUpgrade[{index}].before_description"
        )
        after_description = reader.read_text(
            f"partnerEffectUpgrade[{index}].after_description"
        )
        source_id = reader.read_i32(f"partnerEffectUpgrade[{index}].source_id")
        pet_id = reader.read_i32(f"partnerEffectUpgrade[{index}].pet_id")
        has_skills = reader.read_bool(f"partnerEffectUpgrade[{index}].skills.present")
        skill_ids: list[str] = []
        if has_skills:
            skill_ids = [
                reader.read_text(
                    f"partnerEffectUpgrade[{index}].skills[{skill_index}]"
                ).strip()
                for skill_index in range(
                    _read_count(reader, f"partnerEffectUpgrade[{index}].skills.count")
                )
            ]

        if source_id <= 0 or pet_id <= 0 or pet_id in pet_ids:
            raise PartnerContractsError(f"Invalid or duplicate partner upgrade at {index}")
        if any(not skill_id for skill_id in skill_ids):
            raise PartnerContractsError(f"Invalid skill ID for partner upgrade {pet_id}")

        pet_ids.add(pet_id)
        upgrades.append(
            {
                "source_id": source_id,
                "pet_id": pet_id,
                "before_description": before_description,
                "after_description": after_description,
                "skill_ids": skill_ids,
            }
        )

    reader.ensure_finished("partnerEffectUpgrade.bytes")
    return upgrades


def parse_partner_contracts(
    partner_data: bytes,
    partner_upgrade_data: bytes,
    *,
    config_package_version: str,
) -> dict[str, object]:
    """Build the stable JSON contract consumed by downstream data builders."""

    version = config_package_version.strip()
    if not version:
        raise PartnerContractsError("ConfigPackage version is required")

    return {
        "schema_version": PARTNER_CONTRACTS_SCHEMA_VERSION,
        "source": {
            "package": "ConfigPackage",
            "config_package_version": version,
            "assets": [PARTNER_ASSET_PATH, PARTNER_UPGRADE_ASSET_PATH],
        },
        "groups": parse_partner_groups(partner_data),
        "upgrades": parse_partner_upgrades(partner_upgrade_data),
    }


def is_partner_contracts_document_current(
    document: object,
    *,
    config_package_version: str,
) -> bool:
    """Return whether a published document matches the current source package."""

    if not isinstance(document, Mapping):
        return False
    if document.get("schema_version") != PARTNER_CONTRACTS_SCHEMA_VERSION:
        return False
    source = document.get("source")
    groups = document.get("groups")
    upgrades = document.get("upgrades")
    return (
        isinstance(source, Mapping)
        and source.get("package") == "ConfigPackage"
        and source.get("config_package_version") == config_package_version
        and isinstance(groups, list)
        and bool(groups)
        and isinstance(upgrades, list)
    )


def partner_contracts_file_is_current(
    path: Path,
    *,
    config_package_version: str,
) -> bool:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return is_partner_contracts_document_current(
        document,
        config_package_version=config_package_version,
    )


def _load_partner_assets(asset_root: Path) -> dict[str, bytes]:
    """Read the already-extracted official ConfigPackage bytes from the repo.

    ``seer-unity-assets`` intentionally does not commit transient bundle files.
    Its stable ``newseer/assets`` tree is therefore the authoritative input for
    derived data, including first-time generation after this parser is added.
    """

    assets: dict[str, bytes] = {}
    missing: list[str] = []
    for asset_path in (PARTNER_ASSET_PATH, PARTNER_UPGRADE_ASSET_PATH):
        source_path = asset_root / asset_path
        try:
            assets[asset_path] = source_path.read_bytes()
        except FileNotFoundError:
            missing.append(asset_path)
        except OSError as error:
            raise PartnerContractsError(
                f"Unable to read ConfigPackage asset {asset_path}: {error}"
            ) from error

    if missing:
        raise PartnerContractsError(
            "ConfigPackage is missing contract assets: " + ", ".join(missing)
        )
    return assets


def extract_partner_contracts(
    *,
    asset_root: Path,
    config_package_version: str,
    output_path: Path,
) -> bool:
    """Extract and write canonical contract data, returning whether it changed."""

    assets = _load_partner_assets(asset_root)
    document = parse_partner_contracts(
        assets[PARTNER_ASSET_PATH],
        assets[PARTNER_UPGRADE_ASSET_PATH],
        config_package_version=config_package_version,
    )
    payload = json.dumps(
        document,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if output_path.read_text(encoding="utf-8") == payload:
            return False
    except FileNotFoundError:
        pass
    output_path.write_text(payload, encoding="utf-8")
    return True
