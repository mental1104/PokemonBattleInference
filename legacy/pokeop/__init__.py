"""
Bootstrap import paths so the vendored common submodule is preferred over other
local checkouts and system-wide installs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _inject_common_paths() -> None:
    """按仓库、COMMON_ROOT、~/code/common选择首个存在的common根目录。

    无参数、返回None；把该根目录中存在的Python层加入sys.path，保持原有优先级。
    所有根目录都不存在时不修改sys.path，仍允许原来的系统安装来源。
    """

    # 源码实体归入legacy/pokeop；根兼容软链不改变resolve后的真实层级。
    repo_root = Path(__file__).resolve().parents[2]
    roots = [repo_root / "submodules" / "common"]

    common_root = os.getenv("COMMON_ROOT")
    if common_root:
        roots.append(Path(common_root).expanduser())

    roots.append(Path.home() / "code" / "common")

    seen: set[Path] = set()
    for root in roots:
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        if not root.exists():
            continue

        python_layer = root / "python"
        export_python_layer = root / "export" / "python"
        for candidate in (export_python_layer, python_layer):
            if candidate.exists():
                candidate_str = str(candidate)
                if candidate_str not in sys.path:
                    sys.path.insert(0, candidate_str)
        # Stop at the first root we find.
        break


_inject_common_paths()
