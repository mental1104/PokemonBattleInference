"""
Bootstrap import paths so the vendored common submodule is preferred over other
local checkouts and system-wide installs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _inject_common_paths() -> None:
    """
    Prefer this repository's submodules/common checkout for shared libraries.
    If it is unavailable, fall back to COMMON_ROOT, then ~/code/common. If none
    exists, leave sys.path untouched so system-installed packages can be used.
    """

    repo_root = Path(__file__).resolve().parents[1]
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
