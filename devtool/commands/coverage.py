from __future__ import annotations

from devtool.commands import register
from devtool.context import base_env
from devtool.ops import python as python_ops


@register("coverage")
def configure_coverage(subparsers):
    parser = subparsers.add_parser("coverage", help="Run tests with coverage")
    parser.add_argument("pytest_args", nargs="*", help="Extra args forwarded to pytest")
    parser.set_defaults(_runner=run_coverage)


@register("coverage-python")
def configure_coverage_python(subparsers):
    parser = subparsers.add_parser("coverage-python", help="Run Python coverage")
    parser.add_argument("pytest_args", nargs="*", help="Extra args forwarded to pytest")
    parser.set_defaults(_runner=run_coverage_python)


def run_coverage(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.coverage(env, pytest_args=args.pytest_args)
    return 0


def run_coverage_python(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.coverage(env, pytest_args=args.pytest_args)
    return 0
