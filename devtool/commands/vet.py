from __future__ import annotations

from devtool.commands import register
from devtool.context import base_env
from devtool.ops import python as python_ops


@register("vet")
def configure_vet(subparsers):
    parser = subparsers.add_parser("vet", help="Static analysis and linting")
    parser.set_defaults(_runner=run_vet)


@register("vet-python")
def configure_vet_python(subparsers):
    parser = subparsers.add_parser("vet-python", help="Static analysis for Python")
    parser.set_defaults(_runner=run_vet_python)


def run_vet(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.vet(env)
    return 0


def run_vet_python(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.vet(env)
    return 0
