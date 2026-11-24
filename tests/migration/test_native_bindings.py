"""统一 pytest 入口委托 Go/Swift 原生测试；缺少工具可跳过，显式错误配置必须失败。"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _tool(name: Literal["go", "swift"]) -> str:
    """定位原生测试工具，不尝试安装或启动外部环境。

    Args:
        name: 当前原生测试对应的工具名。

    Returns:
        可执行文件路径。工具未安装时明确跳过；PBI_GO/PBI_SWIFT 显式配置无效则失败。
    """
    configured = os.environ.get(f"PBI_{name.upper()}")
    resolved = shutil.which(configured if configured is not None else name)
    if resolved is None:
        if configured is not None:
            pytest.fail(f"PBI_{name.upper()} must point to an executable tool")
        pytest.skip(f"install {name} to run native binding tests; NAS: validate-nas.sh bindings")
    return resolved


@pytest.fixture(scope="module")
def native_library_dir() -> Path:
    """提供已构建 ABI 静态库目录，不在测试内部编译 Core。

    Returns:
        同时含 pbi_abi/core 静态库的目录。显式配置缺失为失败，否则提示 make test-core。
    """
    configured = os.environ.get("PBI_CORE_LIBRARY_DIR")
    directory = Path(configured) if configured is not None else ROOT / "build/core"
    if not all((directory / name).is_file() for name in ("libpbi_abi.a", "libpbi_core.a")):
        if configured is not None:
            pytest.fail("PBI_CORE_LIBRARY_DIR must contain the built C ABI and core libraries")
        pytest.skip("run make test-core before native binding tests")
    return directory


class TestNativeBindings:
    """原生语言各自执行真实 ABI、共享向量和取消测试，不模拟 Core。"""

    def test_go(self, native_library_dir: Path) -> None:
        """native_library_dir 为当前 Core 产物；执行 Go race suite 和 vet。"""
        executable = _tool("go")
        environment = os.environ.copy()
        environment["CGO_ENABLED"] = "1"
        environment["CGO_LDFLAGS"] = environment.get("CGO_LDFLAGS", "") + " -L" + shlex.quote(str(native_library_dir))
        environment["PBI_CONTRACT_FIXTURES"] = str(ROOT / "tests/vectors")
        for key, name in (("GOCACHE", "go-cache"), ("GOTMPDIR", "go-tmp")):
            directory = native_library_dir.parent / name
            directory.mkdir(parents=True, exist_ok=True)
            environment[key] = str(directory)
        # go help cache 明确说明 cgo 外部库不触发缓存失效，-a 确保重链当前 Core。
        subprocess.run([executable, "test", "-a", "-race", "-count=1", "./..."], cwd=ROOT / "server", env=environment, check=True, timeout=240)
        subprocess.run([executable, "vet", "./..."], cwd=ROOT / "server", env=environment, check=True, timeout=120)

    def test_swift(self, native_library_dir: Path) -> None:
        """native_library_dir 为同环境的 Core 产物；SwiftPM 使用独立可写缓存并执行 XCTest。"""
        executable = _tool("swift")
        environment = os.environ.copy()
        environment["PBI_SWIFT"] = executable
        subprocess.run([
            "bash", str(ROOT / "tools/migration/test-swift.sh"), str(native_library_dir),
        ], env=environment, check=True, timeout=240)
