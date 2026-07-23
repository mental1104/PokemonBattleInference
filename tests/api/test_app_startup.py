from __future__ import annotations

from unittest.mock import Mock

import pytest

from pokeop import main


@pytest.mark.anyio
async def test_app_startup_registers_postgres_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """FastAPI worker 启动时必须注册当前进程的 PostgreSQL runtime。

    `db-init` 容器只能准备数据库内容，不能把 shared common 的进程内 registry 状态传给
    backend worker。该测试直接执行新建 app 的 startup handler，确认 HTTP 服务启动阶段会
    调用轻量连接注册函数，从而让 calculator repository 请求进入 `tx_scope(DBKind.POSTGRES)`
    时不再因为默认连接缺失而返回 500。

    Args:
        monkeypatch: pytest 提供的属性替换工具，用于避免测试触碰真实数据库 registry。
    """
    register_postgres_runtime = Mock()
    monkeypatch.setattr(main, "register_postgres_runtime", register_postgres_runtime)
    application = main.create_app()

    async with application.router.lifespan_context(application):
        pass

    register_postgres_runtime.assert_called_once_with()
