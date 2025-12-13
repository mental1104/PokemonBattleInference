from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, MutableMapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
COMMON_ROOT = ROOT.parent / "common"
COMMON_PYTHON = COMMON_ROOT / "python"
MENTAL1104_PKG = COMMON_PYTHON / "mental1104"


def is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def _merge_pythonpath(env: MutableMapping[str, str]) -> str:
    parts: list[str] = []
    existing = env.get("PYTHONPATH")
    if COMMON_PYTHON.exists():
        parts.append(str(COMMON_PYTHON))
    parts.append(str(ROOT))
    if existing:
        parts.extend([p for p in existing.split(os.pathsep) if p])

    merged: list[str] = []
    for path in parts:
        if path and path not in merged:
            merged.append(path)
            if path not in sys.path:
                sys.path.insert(0, path)
    env["PYTHONPATH"] = os.pathsep.join(merged)
    return env["PYTHONPATH"]


def ensure_pythonpath(env: MutableMapping[str, str]) -> str:
    return _merge_pythonpath(env)


def ensure_common_repo(strict: bool = False) -> bool:
    def _check() -> list[str]:
        missing = []
        if not COMMON_ROOT.exists():
            missing.append(f"未找到 common 仓库: {COMMON_ROOT}")
        if not COMMON_PYTHON.exists():
            missing.append(f"common 仓库缺少 python 目录: {COMMON_PYTHON}")
        if not MENTAL1104_PKG.exists():
            missing.append(f"未找到 mental1104 包: {MENTAL1104_PKG}")
        return missing

    missing = _check()
    if missing:
        for line in missing:
            print(f"[dev] {line}")
        print(
            "[dev] 请执行: git clone https://github.com/mental1104/common.git ../common"
        )
        if strict:
            raise SystemExit(1)
        return False
    return True


def base_env(verbose: bool = False) -> dict[str, str]:
    env: dict[str, str] = os.environ.copy()
    env["REPO_ROOT"] = str(ROOT)
    env["COMMON_ROOT"] = str(COMMON_ROOT)
    env["COMMON_PYTHON"] = str(COMMON_PYTHON)
    venv_dir = ROOT / ".venv"
    venv_bin = venv_dir / ("Scripts" if is_windows() else "bin")
    env.setdefault("PYTHON", sys.executable or ("py" if is_windows() else "python3"))
    env["PY_VENV"] = str(venv_dir)
    env["PY_VENV_BIN"] = str(venv_bin)
    env["PY_VENV_PYTHON"] = str(venv_bin / ("python.exe" if is_windows() else "python"))
    env["PY_VENV_PIP"] = str(venv_bin / ("pip.exe" if is_windows() else "pip"))
    env["PYTHONPATH"] = ensure_pythonpath(env)
    env["VERBOSE"] = "1" if verbose else env.get("VERBOSE", "0")
    return env


def sh(
    cmd: Sequence[str] | str, env: Mapping[str, str], cwd: Path | None = None
) -> None:
    if env.get("VERBOSE") == "1":
        display = cmd if isinstance(cmd, str) else " ".join(map(str, cmd))
        print(f"[dev] $ {display}")
    subprocess.run(cmd, cwd=cwd or ROOT, env=env, check=True)
