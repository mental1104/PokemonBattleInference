from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Mapping

from devtool.context import (
    ROOT,
    COMMON_PYTHON,
    ensure_common_repo,
    ensure_pythonpath,
    sh,
)


DEFAULT_TEST_PATHS = ("tests", "api/testing")
DEFAULT_FORMAT_TARGETS = (
    "api",
    "pokemon_battle_inference",
    "scripts",
    "devtool",
    "tests",
)
DEFAULT_COV_TARGETS = ("api", "pokemon_battle_inference")


def _venv_env(env: Mapping[str, str]) -> dict[str, str]:
    ensure_common_repo(strict=True)
    env = dict(env)
    ensure_pythonpath(env)
    venv_dir = Path(env["PY_VENV"])
    if not venv_dir.exists():
        sh([env["PYTHON"], "-m", "venv", str(venv_dir)], env=env)
    run_env = dict(env)
    run_env["PATH"] = str(Path(env["PY_VENV_BIN"])) + os.pathsep + env.get("PATH", "")
    return run_env


def _install_requirements(env: Mapping[str, str]) -> None:
    req = ROOT / "requirements.txt"
    if req.exists():
        with _patched_common_requirements_for_export():
            sh([env["PY_VENV_PIP"], "install", "-r", str(req)], env=env)


@contextmanager
def _patched_common_requirements_for_export():
    req_path = COMMON_PYTHON / "requirements.txt"
    placeholder = "file://../export/python"
    if not req_path.exists():
        yield
        return
    raw = req_path.read_text()
    if placeholder not in raw:
        yield
        return
    export_path = (COMMON_PYTHON.parent / "export" / "python").resolve()
    replaced = raw.replace(placeholder, f"file://{export_path}")
    try:
        req_path.write_text(replaced)
        yield
    finally:
        req_path.write_text(raw)


def _ensure_tools(env: Mapping[str, str], modules: Iterable[str], hint: str) -> None:
    for module in modules:
        try:
            subprocess.run(
                [env["PY_VENV_PYTHON"], "-c", f"import {module}"],
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"[dev] 缺少依赖 {module}，请先运行 `python dev setup`。{hint}"
            ) from exc


def _assert_can_import_mental1104(env: Mapping[str, str]) -> None:
    script = "import mental1104; print(mental1104.__name__)"
    sh([env["PY_VENV_PYTHON"], "-c", script], env=env)


def setup(env: Mapping[str, str]) -> None:
    run_env = _venv_env(env)
    sh(
        [run_env["PY_VENV_PIP"], "install", "--upgrade", "pip", "setuptools", "wheel"],
        env=run_env,
    )
    _install_requirements(run_env)
    _assert_can_import_mental1104(run_env)


def build(env: Mapping[str, str]) -> None:
    run_env = _venv_env(env)
    targets = [
        str(p) for p in (ROOT / "api", ROOT / "pokemon_battle_inference") if p.exists()
    ]
    if targets:
        sh([run_env["PY_VENV_PYTHON"], "-m", "compileall", *targets], env=run_env)


def test(env: Mapping[str, str], *, pytest_args: Iterable[str]) -> None:
    run_env = _venv_env(env)
    _ensure_tools(run_env, ("pytest",), "测试依赖未安装。")
    paths = [p for p in DEFAULT_TEST_PATHS if (ROOT / p).exists()]
    sh([run_env["PY_VENV_PYTHON"], "-m", "pytest", *paths, *pytest_args], env=run_env)


def coverage(env: Mapping[str, str], *, pytest_args: Iterable[str]) -> None:
    run_env = _venv_env(env)
    _ensure_tools(run_env, ("pytest", "pytest_cov"), "覆盖率依赖未安装。")
    targets = [p for p in DEFAULT_COV_TARGETS if (ROOT / p).exists()]
    args = [run_env["PY_VENV_PYTHON"], "-m", "pytest"]
    if targets:
        for target in targets:
            args.append(f"--cov={target}")
    else:
        args.append("--cov=.")
    args.extend(["--cov-report=term-missing", "--cov-report=xml"])
    paths = [p for p in DEFAULT_TEST_PATHS if (ROOT / p).exists()]
    args.extend(paths)
    args.extend(pytest_args)
    sh(args, env=run_env)


def fmt(env: Mapping[str, str], *, check: bool) -> None:
    run_env = _venv_env(env)
    _ensure_tools(run_env, ("black",), "格式化依赖未安装。")
    targets = [str(ROOT / p) for p in DEFAULT_FORMAT_TARGETS if (ROOT / p).exists()]
    if not targets:
        targets = [str(ROOT)]
    args = [run_env["PY_VENV_PYTHON"], "-m", "black"]
    if check:
        args.append("--check")
    args.extend(targets)
    sh(args, env=run_env)


def vet(env: Mapping[str, str]) -> None:
    run_env = _venv_env(env)
    _ensure_tools(run_env, ("ruff",), "静态检查依赖未安装。")
    targets = [str(ROOT / p) for p in DEFAULT_FORMAT_TARGETS if (ROOT / p).exists()]
    if not targets:
        targets = [str(ROOT)]
    sh([run_env["PY_VENV_PYTHON"], "-m", "ruff", "check", *targets], env=run_env)
