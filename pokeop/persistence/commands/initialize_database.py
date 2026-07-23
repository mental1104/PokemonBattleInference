from __future__ import annotations

import os
from pathlib import Path

from pokeop.persistence.bootstrap import init_db


def _sprites_source_dir() -> Path:
    """选择一次性初始化命令可读取的 sprites 数据源目录。

    `POKEOP_SPRITES_DIR` 可以是单个路径，也可以用 `os.pathsep` 分隔多个候选路径。
    Compose 会同时挂载顶层 `submodules/pokeapi-sprites` 和嵌套
    `submodules/pokeapi/data/v2/sprites`；这里优先使用第一个实际包含 `sprites/`
    子目录的候选项，保证顶层 submodule 初始化前后都能幂等运行同一条命令。

    Returns:
        PokeAPI/sprites 仓库根目录，或已经指向其中 `sprites/` 的目录。

    Raises:
        FileNotFoundError: 所有候选路径都不存在或都不包含 sprites 文件目录。
    """
    raw_value = os.environ.get("POKEOP_SPRITES_DIR", "/data/pokeapi-sprites")
    candidates = [Path(value) for value in raw_value.split(os.pathsep) if value]
    for candidate in candidates:
        if (candidate / "sprites").is_dir() or (candidate.is_dir() and candidate.name == "sprites"):
            return candidate
    raise FileNotFoundError(
        "sprites directory not found in candidates: "
        + ", ".join(str(candidate) for candidate in candidates)
    )


def initialize_database() -> None:
    """执行一次性 PostgreSQL 初始化流水线。

    当前阶段准备可从 PokeAPI CSV 和 sprites 再生的 `poke_raw` 表、二进制资产和
    `poke_champion` 物化视图。该命令由 Compose `db-init` 一次性服务执行，FastAPI
    进程不得调用它。

    未来接入 Alembic 时，应在本入口中先升级承载用户配置的 schema，再执行资产
    准备；不能把 migration 重新塞回 HTTP 服务生命周期。

    Side Effects:
        连接 PostgreSQL，按需创建 raw tables、导入 CSV/sprites，并创建或刷新物化视图。
    """
    sprites_dir = _sprites_source_dir()
    init_db(
        create_tables=True,
        import_csv=True,
        import_sprites=True,
        sprites_dir=sprites_dir,
        create_materialized_views=True,
        refresh_materialized_views=True,
    )


def main() -> None:
    """运行数据库一次性初始化命令，并将失败通过进程退出码交给编排层处理。"""
    initialize_database()


if __name__ == "__main__":
    main()
