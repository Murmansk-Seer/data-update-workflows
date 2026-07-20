from typing_extensions import NotRequired, TypedDict

UNITY_ASSETS_REPO = "Murmansk-Seer/seer-unity-assets"


class PackageConfig(TypedDict):
    updater_name: str
    extractor_name: str
    update_args: list[str]
    skip_extract: bool
    min_size: NotRequired[str | int]
    max_size: NotRequired[str | int]
    push_patterns: NotRequired[list[str]]


CONFIG: dict[str, PackageConfig] = {
    "ConfigPackage": {
        "updater_name": "newseer.config",
        "extractor_name": "newseer",
        "update_args": [],
        "skip_extract": False,
        "push_patterns": [
            "package-manifests/",
            "newseer/assets/",
            "newseer/derived/",
        ],
    },
    "DefaultPackage": {
        "updater_name": "newseer.default",
        "extractor_name": "newseer",
        "update_args": [
            "*game_audios_cv*",
            "*art_ui_pettype*",
            "*art_ui_battleeffect*",
            "*art_ui_avatar*",
            "*art_ui_titlebg*",
            "*art_ui_namecard*",
            "*art_ui_common*",
            "*assets_art_ui_assets_pet_head*",
            "*assets_art_ui_assets_pet_body*",
            "*assets_art_ui_assets_archive*",
            "*assets_art_ui_assets_countermark*",
            "*assets_art_ui_assets_item*",
            "*art_ui_achieve*",
            "*art_ui_assets_achieve_icon*",
            "*art_ui_item_cloth_prev*",
            "*art_ui_expression*",
            "*art_ui_fitment*",
            "*art_ui_nono*",
            "*art_ui_item_*",
            "*art_ui_soulbead*",
            "*art_ui_countermark_*",
            "*art_ui_achieve*",
            "*art_autocard_texture_cards*",
            "*art_autocard_texture_roles*",
            "*art_autocard_texture_minipet*",
        ],
        "skip_extract": False,
    },
}
