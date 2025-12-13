from __future__ import annotations

import argparse
import importlib
import pkgutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Iterable

from devtool.commands import CONFIGURATORS
from devtool.context import ROOT


def _import_command_modules() -> None:
    pkg = importlib.import_module("devtool.commands")
    prefix = pkg.__name__ + "."
    for module in pkgutil.walk_packages(pkg.__path__, prefix):  # type: ignore[attr-defined]
        name = module.name
        if name.split(".")[-1].startswith("_"):
            continue
        importlib.import_module(name)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Developer utilities entrypoint.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    _import_command_modules()
    for _, configurator in CONFIGURATORS.items():
        configurator(subparsers)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    runner = getattr(args, "_runner", None)
    if runner is None:
        parser.print_help()
        return 1
    try:
        return int(runner(args) or 0)
    except subprocess.CalledProcessError as exc:
        cmd_display = " ".join(map(str, exc.cmd)) if exc.cmd else ""
        print(f"[dev] 子进程执行失败，退出码 {exc.returncode}")
        if cmd_display:
            print(f"[dev] 命令：{cmd_display}")
        return exc.returncode
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
