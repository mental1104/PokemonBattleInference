"""按显式清单打包朱紫PNG小图标；不扫描整库、不下载、不改图，也不包含动画或大立绘。"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

PositiveID = Annotated[int, Field(gt=0)]
SourceCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
ItemIdentifier = Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
MAX_ICON_PACK_BYTES = 32 * 1024 * 1024


class PokemonIconSource(StrEnum):
    """朱紫缺图时允许使用的真实游戏菜单PNG目录；按清单顺序查找同一宝可梦编号。"""

    CHAMPIONS = "generation-ix/champions"
    LEGENDS_ZA = "generation-ix/legends-za"
    LEGENDS_ARCEUS = "generation-viii/legends-arceus"
    BRILLIANT_DIAMOND_SHINING_PEARL = "generation-viii/brilliant-diamond-shining-pearl"
    SWORD_SHIELD = "generation-viii/sword-shield"
    GENERATION_VII = "generation-vii"


class IconKind(StrEnum):
    """图标使用职责，不能把招式或道具名称当成宝可梦编号。"""

    POKEMON = "pokemon"
    ITEM = "item"
    TYPE = "type"


class IconSelection(BaseModel):
    """可审查的唯一打包清单；只允许指定朱紫宝可梦、当前道具和属性编号。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1]
    source_commit: SourceCommit
    game: Literal["scarlet-violet"]
    pokemon_ids: tuple[PositiveID, ...]
    pokemon_fallback_sources: tuple[PokemonIconSource, ...] = ()
    item_identifiers: tuple[ItemIdentifier, ...]
    type_ids: tuple[PositiveID, ...]


class IconAsset(BaseModel):
    """一个未修改PNG的来源、Swift资源名及完整性合同；source_path相对上游sprites目录。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: IconKind
    identifier: str
    source_path: str
    server_path: str
    resource_name: str
    sha256: str
    byte_size: int
    width: int
    height: int


class IconManifest(BaseModel):
    """服务端与Swift共用的固定图标包清单，准确记录实际数量/总字节和上游版本。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    source_commit: SourceCommit
    game: Literal["scarlet-violet"] = "scarlet-violet"
    source_policy: Literal["scarlet-violet-preferred"] = "scarlet-violet-preferred"
    asset_count: int
    byte_size: int
    assets: tuple[IconAsset, ...]


@dataclass(frozen=True)
class _IconRequest:
    """一个显式选项对应唯一上游PNG，不通过运行时注册表或模糊名称发现。"""

    kind: IconKind
    identifier: str
    source_path: str


@dataclass(frozen=True)
class _BuiltIcon:
    """构建期间拥有一份小PNG及其完整记录；全图鉴总量限制32MiB，验证完成前不发布输出。"""

    asset: IconAsset
    content: bytes


class _IconBuilder:
    """只读取选中的文件；宝可梦使用朱紫菜单原PNG，道具用标准小图，属性用朱紫徽标。"""

    def __init__(self, source: Path, selection: IconSelection) -> None:
        """source为只读sprites目录，selection为已解码清单；不修改输入或主动下载。"""
        self._source = source
        self._selection = selection

    def _pokemon_request(self, identifier: int) -> _IconRequest:
        """为identifier先查朱紫，再查显式批准的菜单图来源；始终保持同一ID，缺图直接失败。"""
        directories = (
            "pokemon/versions/generation-ix/scarlet-violet/icons",
            *(f"pokemon/versions/{source.value}/icons"
              for source in self._selection.pokemon_fallback_sources),
        )
        for directory in directories:
            relative = f"{directory}/{identifier}.png"
            if (self._source / relative).is_file():
                return _IconRequest(IconKind.POKEMON, str(identifier), relative)
        raise FileNotFoundError(f"No selected menu icon source covers Pokemon {identifier}")

    def _requests(self) -> tuple[_IconRequest, ...]:
        """按固定清单生成资源请求；顺序稳定，同一身份重复出现即明确拒绝。"""
        pokemon = tuple(
            self._pokemon_request(identifier)
            for identifier in self._selection.pokemon_ids
        )
        items = tuple(
            _IconRequest(IconKind.ITEM, identifier, f"items/{identifier}.png")
            for identifier in self._selection.item_identifiers
        )
        types = tuple(
            _IconRequest(
                IconKind.TYPE, str(identifier),
                f"types/generation-ix/scarlet-violet/{identifier}.png",
            )
            for identifier in self._selection.type_ids
        )
        requests = (*pokemon, *items, *types)
        if len({(item.kind, item.identifier) for item in requests}) != len(requests):
            raise ValueError("duplicate icon selection")
        return requests

    def build(self) -> tuple[_BuiltIcon, ...]:
        """核验所有选中PNG的签名、IHDR尺寸及总预算后返回完整产物；失败不写输出目录。"""
        result: list[_BuiltIcon] = []
        total_bytes = 0
        for request in self._requests():
            content = (self._source / request.source_path).read_bytes()
            if (
                len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n"
                or content[12:16] != b"IHDR"
            ):
                raise ValueError("selected icon is not a PNG with IHDR")
            width = int.from_bytes(content[16:20], "big")
            height = int.from_bytes(content[20:24], "big")
            if not (0 < width <= 256 and 0 < height <= 256):
                raise ValueError("selected icon exceeds small image dimensions")
            total_bytes += len(content)
            if total_bytes > MAX_ICON_PACK_BYTES:
                raise ValueError("selected icon pack exceeds 32 MiB")
            asset = IconAsset(
                kind=request.kind, identifier=request.identifier,
                source_path=request.source_path,
                # 通用URL使用原默认槽位，清单同时保留朱紫真实来源，不混入旧像素图。
                server_path=(f"pokemon/{request.identifier}.png"
                             if request.kind == IconKind.POKEMON
                             else request.source_path),
                resource_name=f"{request.kind.value}-{request.identifier}",
                sha256=hashlib.sha256(content).hexdigest(), byte_size=len(content),
                width=width, height=height,
            )
            result.append(_BuiltIcon(asset, content))
        return tuple(result)


def build_icon_pack(
    source: Path, selection: IconSelection, output: Path, swift_resources: Path
) -> IconManifest:
    """生成仅包含选中图标的服务端包与Swift资源；两份正文逐字节相同。

    Args:
        source: 上游固定commit的sprites目录；只访问清单列出的文件。
        selection: 显式选取的版本、宝可梦、道具、属性，不自动扩展。
        output: 尚不存在的服务端包目录，保存原相对路径和manifest.json。
        swift_resources: 尚不存在的Swift Icons目录，资源名带类别前缀避免SPM扁平化碰撞。

    Returns:
        完整清单。任一来源错误会在创建输出前失败；已有目标明确拒绝，防止覆盖历史产物。
    """
    if output.exists() or swift_resources.exists():
        raise FileExistsError("icon output directories must not already exist")
    icons = _IconBuilder(source, selection).build()
    manifest = IconManifest(
        source_commit=selection.source_commit, asset_count=len(icons),
        byte_size=sum(item.asset.byte_size for item in icons),
        assets=tuple(item.asset for item in icons),
    )
    output.mkdir(parents=True)
    swift_resources.mkdir(parents=True)
    for icon in icons:
        destination = output / "sprites" / icon.asset.server_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(icon.content)
        (swift_resources / f"{icon.asset.resource_name}.png").write_bytes(icon.content)
    descriptor = manifest.model_dump_json(indent=2) + "\n"
    (output / "manifest.json").write_text(descriptor, encoding="utf-8")
    (swift_resources / "icons-manifest.json").write_text(descriptor, encoding="utf-8")
    return manifest


def main() -> None:
    """读取固定清单和路径参数；成功输出准确包体摘要，不调用网络或图像编辑工具。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--swift-resources", required=True, type=Path)
    arguments = parser.parse_args()
    selection = IconSelection.model_validate_json(arguments.selection.read_text())
    report = build_icon_pack(
        arguments.source, selection, arguments.output, arguments.swift_resources
    )
    print(f"Built {report.asset_count} selected icons, {report.byte_size} bytes.")


if __name__ == "__main__":
    main()
