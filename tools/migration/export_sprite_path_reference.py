"""从固定Git树的NUL路径清单导出原Python元数据/MIME参考；不读取图片正文或数据库。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pokeop.persistence.assets.importer import _mime_type
from pokeop.persistence.assets.path_parser import SpritePathMetadata, parse_sprite_path


@dataclass(frozen=True)
class _ReferenceRow:
    """JSONL边界记录；metadata保留原14项可空字段，mime_type直接来自原importer。"""

    metadata: SpritePathMetadata
    mime_type: str


def export_reference(paths: Path, output: Path) -> int:
    """逐项调用原解析器，写出供Go独立比较的完整参考记录。

    Args:
        paths: git ls-tree -rz --name-only产生的UTF-8/NUL路径清单，不包含sprites前缀。
        output: JSONL目标文件；父目录须存在，同名文件会覆盖，不修改输入或原实现。

    Returns:
        实际导出的非空路径数量；解析、编码或文件错误直接抛出，不产生成功回执。
    """
    count = 0
    # NUL保留文件名中的空格、非ASCII和换行，不读取git的带引号显示形式。
    with output.open("w", encoding="utf-8") as destination:
        for relative in paths.read_text(encoding="utf-8").split("\0"):
            if not relative:
                continue
            row = _ReferenceRow(parse_sprite_path(relative), _mime_type(relative))
            destination.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> None:
    """解析输入/输出文件参数，导出完整原参考并以ASCII报告数量；失败返回非零。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    count = export_reference(arguments.paths, arguments.output)
    print(f"Exported {count} original sprite metadata and MIME records.")


if __name__ == "__main__":
    main()
