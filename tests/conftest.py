"""提供跨测试目录共享的 pytest fixture。"""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """让 AnyIO 测试使用项目实际采用的 asyncio 后端。

    Returns:
        固定返回 ``asyncio``，避免 AnyIO 自动参数化未声明依赖的 Trio 后端。
    """

    return "asyncio"
