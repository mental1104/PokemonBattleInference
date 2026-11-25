"""精选朱紫小图标的交付合同：保留原PNG、按需选取、控制包体并保持失败时不发布。"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from tools.data.build_icon_pack import (
    MAX_ICON_PACK_BYTES,
    IconKind,
    IconManifest,
    IconSelection,
    PokemonIconSource,
    build_icon_pack,
)

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data/assets/scarlet-violet"


def _selected_source(directory: Path) -> tuple[Path, IconSelection]:
    """在directory建立3项真实PNG的上游路径夹具，额外放入不应打包的旧图和动画文件。"""
    manifest = IconManifest.model_validate_json((PACK / "manifest.json").read_text())
    selected = {
        (IconKind.POKEMON, "212"), (IconKind.ITEM, "life-orb"), (IconKind.TYPE, "9")
    }
    source = directory / "upstream"
    for asset in manifest.assets:
        if (asset.kind, asset.identifier) in selected:
            filename = source / asset.source_path
            filename.parent.mkdir(parents=True, exist_ok=True)
            filename.write_bytes((PACK / "sprites" / asset.server_path).read_bytes())
    # 同ID的旧像素图与动画即使存在，也不能通过整目录复制混入成品。
    (source / "pokemon/212.png").write_bytes(b"unselected old pixel sprite")
    (source / "pokemon/versions/generation-ix/scarlet-violet/212.webp").write_bytes(
        b"unselected animation"
    )
    selection = IconSelection(
        schema_version=1, source_commit=manifest.source_commit, game="scarlet-violet",
        pokemon_ids=(212,), item_identifiers=("life-orb",), type_ids=(9,),
    )
    return source, selection


class TestSelectedIconPack:
    """只通过公开构建入口核验选取和成品，不依赖NAS大素材源或网络。"""

    def test_only_selected_unchanged_pngs(self, tmp_path: Path) -> None:
        """三种类别正确映射到服务端和Swift，正文、来源SHA和真实字节数全部一致。"""
        source, selection = _selected_source(tmp_path)
        output, swift = tmp_path / "server", tmp_path / "swift"
        manifest = build_icon_pack(source, selection, output, swift)
        assert manifest.asset_count == 3
        assert manifest.byte_size == sum(asset.byte_size for asset in manifest.assets)
        assert manifest.byte_size < MAX_ICON_PACK_BYTES
        assert len(list((output / "sprites").rglob("*.png"))) == 3
        assert not list(output.rglob("*.webp"))
        assert not list(output.rglob("*.gif"))
        assert (output / "manifest.json").read_bytes() == (swift / "icons-manifest.json").read_bytes()
        for asset in manifest.assets:
            expected = (source / asset.source_path).read_bytes()
            assert (output / "sprites" / asset.server_path).read_bytes() == expected
            assert (swift / f"{asset.resource_name}.png").read_bytes() == expected
            assert asset.sha256 == hashlib.sha256(expected).hexdigest()
            assert asset.byte_size == len(expected)
            if asset.kind == IconKind.POKEMON:
                assert asset.source_path == "pokemon/versions/generation-ix/scarlet-violet/icons/212.png"
                assert asset.server_path == "pokemon/212.png"
                assert asset.resource_name == "pokemon-212"

    def test_missing_selected_file_publishes_nothing(self, tmp_path: Path) -> None:
        """缺失任何显式选项时必须失败，不能静默漏图或创建部分成品。"""
        source, selection = _selected_source(tmp_path)
        (source / "items/life-orb.png").unlink()
        output, swift = tmp_path / "server", tmp_path / "swift"
        with pytest.raises(FileNotFoundError):
            build_icon_pack(source, selection, output, swift)
        assert not output.exists()
        assert not swift.exists()

    def test_other_game_fills_missing_scarlet_violet_icon(self, tmp_path: Path) -> None:
        """绿毛虫没有朱紫菜单图时，显式选择的BDSP同编号图标应补齐，来源不得伪装成朱紫。"""
        manifest = IconManifest.model_validate_json((PACK / "manifest.json").read_text())
        caterpie = next(asset for asset in manifest.assets if asset.kind == IconKind.POKEMON and asset.identifier == "10")
        source = tmp_path / "upstream"
        original = source / caterpie.source_path
        original.parent.mkdir(parents=True)
        original.write_bytes((PACK / "sprites" / caterpie.server_path).read_bytes())
        selection = IconSelection(
            schema_version=1, source_commit=manifest.source_commit, game="scarlet-violet",
            pokemon_ids=(10,), item_identifiers=(), type_ids=(),
            pokemon_fallback_sources=(PokemonIconSource.BRILLIANT_DIAMOND_SHINING_PEARL,),
        )
        actual = build_icon_pack(source, selection, tmp_path / "server", tmp_path / "swift")
        assert actual.asset_count == 1
        assert actual.assets[0].source_path == caterpie.source_path
        assert actual.assets[0].server_path == "pokemon/10.png"
        assert actual.assets[0].sha256 == caterpie.sha256

    def test_duplicate_selection_is_rejected(self, tmp_path: Path) -> None:
        """重复编号不能重复占用包体或覆盖另一个记录。"""
        source, original = _selected_source(tmp_path)
        selection = IconSelection(
            schema_version=1, source_commit=original.source_commit,
            game="scarlet-violet", pokemon_ids=(212, 212),
            item_identifiers=(), type_ids=(),
        )
        with pytest.raises(ValueError, match="duplicate"):
            build_icon_pack(source, selection, tmp_path / "server", tmp_path / "swift")

    def test_large_pack_is_rejected_before_publish(self, tmp_path: Path) -> None:
        """即使文件扩展名和小图尺寸正确，也不能夹带超过预算的正文。"""
        source, selection = _selected_source(tmp_path)
        filename = source / "pokemon/versions/generation-ix/scarlet-violet/icons/212.png"
        filename.write_bytes(filename.read_bytes() + b"x" * MAX_ICON_PACK_BYTES)
        output, swift = tmp_path / "server", tmp_path / "swift"
        with pytest.raises(ValueError, match="32 MiB"):
            build_icon_pack(source, selection, output, swift)
        assert not output.exists()
        assert not swift.exists()

    def test_delivered_manifest_matches_both_packages(self) -> None:
        """全图鉴1350条记录必须全部覆盖，5项道具和19种属性仍按需，Swift所有资源逐字相同。"""
        manifest = IconManifest.model_validate_json((PACK / "manifest.json").read_text())
        swift = ROOT / "ios/Sources/PokemonAppSupport/Resources/Icons"
        assert manifest.game == "scarlet-violet"
        assert manifest.asset_count == 1374
        assert manifest.byte_size == 20079618
        assert sum(asset.kind == IconKind.POKEMON for asset in manifest.assets) == 1350
        assert sum(asset.kind == IconKind.ITEM for asset in manifest.assets) == 5
        assert sum(asset.kind == IconKind.TYPE for asset in manifest.assets) == 19
        assert len(list((PACK / "sprites").rglob("*.png"))) == 1374
        assert len(list(swift.glob("*.png"))) == 1374
        with (ROOT / "submodules/pokeapi/data/v2/csv/pokemon.csv").open() as catalog:
            expected_ids = {int(row["id"]) for row in csv.DictReader(catalog)}
        actual_ids = {int(asset.identifier) for asset in manifest.assets if asset.kind == IconKind.POKEMON}
        assert actual_ids == expected_ids
        assert sum(asset.kind == IconKind.POKEMON and "/scarlet-violet/icons/" in asset.source_path for asset in manifest.assets) == 869
        for asset in manifest.assets:
            payload = (PACK / "sprites" / asset.server_path).read_bytes()
            assert payload == (swift / f"{asset.resource_name}.png").read_bytes()
            assert hashlib.sha256(payload).hexdigest() == asset.sha256
            if asset.kind == IconKind.POKEMON:
                assert Path(asset.source_path).stem == asset.identifier
