"""验证Python参考归位后的真实导入、固定数据来源及本地静态资源。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pokeop
from pokeop.main import STATIC_DIR
from pokeop.persistence.bootstrap import _DEFAULT_CSV_DIR, _DEFAULT_SPRITES_DIR

ROOT = Path(__file__).resolve().parents[2]


class TestLegacyLayout:
    """只读取参考布局；不连接数据库，不依赖当前进程预装的common来掩盖根定位错误。"""

    def test_package_and_fixed_csv_link(self) -> None:
        """源码实体与CSV分别位于legacy和固定子模块，兼容命名空间只指向同一份实现。"""
        assert (ROOT / "pokeop").is_symlink()
        assert (ROOT / "pokeop").resolve() == ROOT / "legacy" / "pokeop"
        source = pokeop.__file__
        assert source is not None
        assert Path(source).resolve() == ROOT / "legacy" / "pokeop" / "__init__.py"
        assert _DEFAULT_CSV_DIR.resolve() == ROOT / "submodules" / "pokeapi" / "data" / "v2" / "csv"
        assert (_DEFAULT_CSV_DIR / "pokemon.csv").is_file()
        assert _DEFAULT_SPRITES_DIR == ROOT / "submodules" / "pokeapi-sprites"

    def test_static_resources_follow_the_reference_package(self) -> None:
        """Swagger资源跟随真实包，不依赖进程当前工作目录或旧的根目录实体。"""
        assert STATIC_DIR == ROOT / "legacy" / "pokeop" / "assets_static"
        assert (STATIC_DIR / "swagger-ui.css").is_file()
        assert (STATIC_DIR / "swagger-ui-bundle.js").is_file()

    def test_fresh_process_prefers_this_repository_common(self) -> None:
        """清除环境路径后在新解释器真实导入db，核对common仍来自当前仓库子模块。"""
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("COMMON_ROOT", None)
        completed = subprocess.run(
            [sys.executable, "-c", "import pokeop; import mental1104.db; print(mental1104.db.__file__)"],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert Path(completed.stdout.strip()).is_relative_to(ROOT / "submodules" / "common" / "python")
