from __future__ import annotations

from devtool.commands import register
from devtool.context import base_env
from devtool.ops import python as python_ops


@register("build")
def configure_build(subparsers):
    parser = subparsers.add_parser(
        "build", help="Build all languages (delegates to language-specific targets)"
    )
    parser.set_defaults(_runner=run_build)


@register("build-python")
def configure_build_python(subparsers):
    parser = subparsers.add_parser("build-python", help="Build Python artifacts")
    parser.set_defaults(_runner=run_build_python)


def run_build(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.build(env)
    return 0


def run_build_python(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.build(env)
    return 0
