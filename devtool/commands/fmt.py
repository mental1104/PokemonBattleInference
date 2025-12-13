from __future__ import annotations

from devtool.commands import register
from devtool.context import base_env
from devtool.ops import python as python_ops


@register("fmt")
def configure_fmt(subparsers):
    parser = subparsers.add_parser(
        "fmt", help="Format code (delegates to language formatters)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check formatting without writing changes",
    )
    parser.set_defaults(_runner=run_fmt)


@register("fmt-python")
def configure_fmt_python(subparsers):
    parser = subparsers.add_parser("fmt-python", help="Format Python code")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check formatting without writing changes",
    )
    parser.set_defaults(_runner=run_fmt_python)


def run_fmt(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.fmt(env, check=bool(args.check))
    return 0


def run_fmt_python(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.fmt(env, check=bool(args.check))
    return 0
