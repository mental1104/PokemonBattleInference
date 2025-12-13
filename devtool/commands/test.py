from __future__ import annotations

from devtool.commands import register
from devtool.context import base_env
from devtool.ops import python as python_ops


@register("test")
def configure_test(subparsers):
    parser = subparsers.add_parser("test", help="Run all tests")
    parser.add_argument("pytest_args", nargs="*", help="Extra args forwarded to pytest")
    parser.set_defaults(_runner=run_test)


@register("test-python")
def configure_test_python(subparsers):
    parser = subparsers.add_parser("test-python", help="Run Python tests")
    parser.add_argument("pytest_args", nargs="*", help="Extra args forwarded to pytest")
    parser.set_defaults(_runner=run_test_python)


def run_test(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.test(env, pytest_args=args.pytest_args)
    return 0


def run_test_python(args) -> int:
    env = base_env(getattr(args, "verbose", False))
    python_ops.test(env, pytest_args=args.pytest_args)
    return 0
