"""
Bootstrap import paths so local `~/code/common` (and its export layer) are preferred
over system-wide installs. This keeps shared capabilities in mental1104 taking
precedence during development while still allowing a system-installed fallback.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _inject_common_paths() -> None:
    """
    Prefer the developer's ~/code/common checkout (or a sibling ../common) for
    shared libraries. If neither exists, we leave sys.path untouched so that any
    system-installed packages are used instead.
    """

    preferred_root = Path(
        os.getenv("COMMON_ROOT", Path.home() / "code" / "common")
    ).expanduser()
    fallback_root = Path(__file__).resolve().parents[2] / "common"

    for root in (preferred_root, fallback_root):
        if not root.exists():
            continue

        python_layer = root / "python"
        export_python_layer = root / "export" / "python"
        for candidate in (python_layer, export_python_layer):
            if candidate.exists():
                candidate_str = str(candidate)
                if candidate_str not in sys.path:
                    sys.path.insert(0, candidate_str)
        # Stop at the first root we find.
        break


_inject_common_paths()
