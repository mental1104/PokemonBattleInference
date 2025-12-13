from __future__ import annotations

from devtool.commands import register
from devtool.context import base_env
from devtool.ops import python as python_ops


@register("setup")
def configure_setup(subparsers):
    parser = subparsers.add_parser("setup", help="Setup all language environments")
    parser.set_defaults(_runner=run_setup)


@register("setup-python")
def configure_setup_python(subparsers):
    parser = subparsers.add_parser("setup-python", help="Setup Python venv and deps")
    parser.set_defaults(_runner=run_setup_python)


def run_setup(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.setup(env)
    return 0


def run_setup_python(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.setup(env)
    return 0
