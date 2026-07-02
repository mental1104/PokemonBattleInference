from __future__ import annotations

import csv
from pathlib import Path

from pokeop.domain.battle.rulesets.resolver import VERSION_GROUP_TO_GENERATION


def test_static_version_group_generation_mapping_matches_local_csv():
    """
    验证 domain 静态 VERSION_GROUP_TO_GENERATION 映射与本地 PokeAPI CSV 保持一致。
    resolver 生产代码不能运行时读取 CSV 或数据库，但开发期必须及时发现数据源更新导致的静态表漂移；
    本测试检查 CSV 中所有 id 都被覆盖、generation_id 完全一致、静态表没有多余 id，保护 Phase 2 走读时的规则入口合同。
    """
    csv_path = Path("pokeop/assets_data/version_groups.csv")
    assert csv_path.exists(), "pokeop/assets_data/version_groups.csv must exist"

    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        csv_mapping = {
            int(row["id"]): int(row["generation_id"])
            for row in reader
        }

    assert VERSION_GROUP_TO_GENERATION == csv_mapping
