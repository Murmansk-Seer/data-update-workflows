from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.seer_unity_assets.partner_contracts import (
    PARTNER_ASSET_PATH,
    PARTNER_CONTRACTS_SCHEMA_VERSION,
    PARTNER_UPGRADE_ASSET_PATH,
    PartnerContractsError,
    extract_partner_contracts,
    is_partner_contracts_document_current,
    parse_partner_contracts,
)


def _i32(value: int) -> bytes:
    return value.to_bytes(4, byteorder="little", signed=True)


def _text(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(2, byteorder="little") + encoded


def _group(
    *,
    source_id: int,
    key: int,
    name: str,
    members: tuple[int, ...],
    cost: int,
    contract_type: str,
) -> bytes:
    return b"".join(
        (
            _i32(0),
            _i32(source_id),
            _i32(cost),
            _i32(key),
            b"\x01",
            _i32(len(members)),
            *(_i32(member) for member in members),
            _text(name),
            _i32(len(members)),
            _text(contract_type),
        )
    )


def _upgrade(
    *,
    source_id: int,
    pet_id: int,
    skill_ids: tuple[str, ...],
) -> bytes:
    skill_data = (b"\x00",)
    if skill_ids:
        skill_data = (
            b"\x01",
            _i32(len(skill_ids)),
            *(_text(skill_id) for skill_id in skill_ids),
        )
    return b"".join(
        (
            _text("before"),
            _text("after"),
            _i32(source_id),
            _i32(pet_id),
            *skill_data,
        )
    )


class PartnerContractsTests(unittest.TestCase):
    def test_parses_groups_with_colliding_source_ids_and_upgrade_skills(self) -> None:
        partner_data = b"".join(
            (
                b"\x01",
                _i32(2),
                _group(
                    source_id=1,
                    key=1,
                    name="雷电传承",
                    members=(3142, 3150),
                    cost=3,
                    contract_type="1",
                ),
                _group(
                    source_id=1,
                    key=6,
                    name="霜月悬天",
                    members=(4147, 4178, 4096),
                    cost=8,
                    contract_type="2",
                ),
            )
        )
        upgrade_data = b"".join(
            (
                b"\x01",
                _i32(2),
                _upgrade(source_id=1, pet_id=4147, skill_ids=("36696",)),
                _upgrade(source_id=2, pet_id=4178, skill_ids=()),
            )
        )

        document = parse_partner_contracts(
            partner_data,
            upgrade_data,
            config_package_version="test-version",
        )

        self.assertEqual(document["schema_version"], PARTNER_CONTRACTS_SCHEMA_VERSION)
        self.assertEqual(document["source"]["config_package_version"], "test-version")
        self.assertEqual(
            document["groups"],
            [
                {
                    "key": 1,
                    "source_id": 1,
                    "type": "1",
                    "name": "雷电传承",
                    "cost": 3,
                    "member_pet_ids": [3142, 3150],
                    "required_pet_count": 2,
                    "bitbuf": 0,
                },
                {
                    "key": 6,
                    "source_id": 1,
                    "type": "2",
                    "name": "霜月悬天",
                    "cost": 8,
                    "member_pet_ids": [4147, 4178, 4096],
                    "required_pet_count": 3,
                    "bitbuf": 0,
                },
            ],
        )
        self.assertEqual(document["upgrades"][0]["skill_ids"], ["36696"])
        self.assertEqual(document["upgrades"][1]["skill_ids"], [])
        self.assertTrue(
            is_partner_contracts_document_current(
                document,
                config_package_version="test-version",
            )
        )
        self.assertFalse(
            is_partner_contracts_document_current(
                {"schema_version": PARTNER_CONTRACTS_SCHEMA_VERSION, "source": {}},
                config_package_version="test-version",
            )
        )

    def test_rejects_trailing_binary_data(self) -> None:
        partner_data = b"\x00\x01"

        with self.assertRaises(PartnerContractsError):
            parse_partner_contracts(
                partner_data,
                b"\x00",
                config_package_version="test-version",
            )

    def test_extracts_from_the_committed_asset_tree(self) -> None:
        partner_data = b"".join(
            (
                b"\x01",
                _i32(1),
                _group(
                    source_id=1,
                    key=1,
                    name="contract",
                    members=(3142, 3150),
                    cost=3,
                    contract_type="1",
                ),
            )
        )
        upgrade_data = b"".join(
            (
                b"\x01",
                _i32(1),
                _upgrade(source_id=1, pet_id=3142, skill_ids=("36696",)),
            )
        )

        with TemporaryDirectory() as directory:
            asset_root = Path(directory) / "newseer"
            for asset_path, content in (
                (PARTNER_ASSET_PATH, partner_data),
                (PARTNER_UPGRADE_ASSET_PATH, upgrade_data),
            ):
                destination = asset_root / asset_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)

            output_path = Path(directory) / "derived" / "partner_contracts.json"
            self.assertTrue(
                extract_partner_contracts(
                    asset_root=asset_root,
                    config_package_version="test-version",
                    output_path=output_path,
                )
            )
            self.assertFalse(
                extract_partner_contracts(
                    asset_root=asset_root,
                    config_package_version="test-version",
                    output_path=output_path,
                )
            )

            document = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(document["groups"][0]["member_pet_ids"], [3142, 3150])
            self.assertEqual(document["upgrades"][0]["skill_ids"], ["36696"])


if __name__ == "__main__":
    unittest.main()
