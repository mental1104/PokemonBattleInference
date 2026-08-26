"""提供跨测试目录共享的 pytest fixture。"""

from __future__ import annotations

import os
import platform
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, text


_POSTGRES_CONTRACT_VAR = "POKEOP_TEST_POSTGRES_URL"


@dataclass(frozen=True)
class PostgresTestEnvironment:
    """描述 PostgreSQL integration tests 可以直接使用的就绪环境。

    Attributes:
        url: 可传给 SQLAlchemy 的 PostgreSQL 连接 URL。
        owned: 当前 pytest 进程是否负责清理该环境；外部传入 URL 时始终为 ``False``。
        container_name: pytest 自动 provision 的 Docker 容器名；外部环境没有容器名。
    """

    url: str
    owned: bool
    container_name: str | None = None


@pytest.fixture
def anyio_backend() -> str:
    """让 AnyIO 测试使用项目实际采用的 asyncio 后端。

    Returns:
        固定返回 ``asyncio``，避免 AnyIO 自动参数化未声明依赖的 Trio 后端。
    """

    return "asyncio"


@pytest.fixture(scope="session")
def postgres_test_environment() -> Iterator[PostgresTestEnvironment]:
    """解析或 provision PostgreSQL integration test 的 Environment Contract。

    Yields:
        已经通过 ``SELECT 1`` 验证可连接的 PostgreSQL 测试环境。

    Raises:
        pytest.fail: Linux 上 Docker provision 或 readiness 检查失败时终止测试。
    """

    external_url = os.environ.get(_POSTGRES_CONTRACT_VAR)
    if external_url:
        _wait_for_postgres_ready(external_url)
        yield PostgresTestEnvironment(url=external_url, owned=False)
        return

    system_name = platform.system()
    if system_name == "Darwin":
        pytest.skip(
            f"set {_POSTGRES_CONTRACT_VAR} to run PostgreSQL integration tests on macOS"
        )
    if system_name != "Linux":
        pytest.skip(
            f"set {_POSTGRES_CONTRACT_VAR} to run PostgreSQL integration tests on {system_name}"
        )
    if not _docker_available():
        pytest.skip(
            f"set {_POSTGRES_CONTRACT_VAR} or start Docker to run PostgreSQL integration tests"
        )

    environment = _provision_postgres_container()
    try:
        _wait_for_postgres_ready(environment.url)
        yield environment
    finally:
        if environment.owned:
            _remove_postgres_container(environment.container_name)


def _docker_available() -> bool:
    """检查当前 Linux 主机是否可以调用 Docker daemon。

    Returns:
        Docker CLI 和 daemon 都可用时返回 ``True``，否则返回 ``False``。
    """

    try:
        completed = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _provision_postgres_container() -> PostgresTestEnvironment:
    """启动 PostgreSQL integration tests 所需的最小 Docker 环境。

    Returns:
        指向临时 PostgreSQL 容器的测试环境描述。

    Raises:
        pytest.fail: 容器启动或端口解析失败时终止测试。
    """

    container_name = f"pokeop-test-postgres-{uuid.uuid4().hex[:12]}"
    completed = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-e",
            "POSTGRES_DB=pokeop",
            "-e",
            "POSTGRES_USER=pokeop",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-p",
            "127.0.0.1::5432",
            "postgres:16-alpine",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        pytest.fail(
            "failed to provision PostgreSQL test container: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )

    port = _docker_container_port(container_name)
    return PostgresTestEnvironment(
        url=f"postgresql+psycopg2://pokeop@127.0.0.1:{port}/pokeop",
        owned=True,
        container_name=container_name,
    )


def _docker_container_port(container_name: str) -> str:
    """读取 Docker 为容器 PostgreSQL 端口分配的宿主机端口。

    Args:
        container_name: pytest 自动 provision 的 PostgreSQL 容器名。

    Returns:
        可从宿主机访问的 TCP 端口字符串。

    Raises:
        pytest.fail: Docker 没有返回有效端口映射时终止测试。
    """

    completed = subprocess.run(
        ["docker", "port", container_name, "5432/tcp"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        _remove_postgres_container(container_name)
        pytest.fail(
            "failed to inspect PostgreSQL test container port: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )

    first_mapping = completed.stdout.strip().splitlines()[0]
    return first_mapping.rsplit(":", maxsplit=1)[-1]


def _wait_for_postgres_ready(url: str, timeout_seconds: float = 60.0) -> None:
    """等待 PostgreSQL URL 完成一次真实 SQL 连接检查。

    Args:
        url: 待验证的 PostgreSQL SQLAlchemy URL。
        timeout_seconds: 最长等待秒数，超时后测试失败。

    Raises:
        pytest.fail: 超时前始终无法执行 ``SELECT 1`` 时终止测试。
    """

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 - readiness 需要保留最后一次底层失败原因。
            last_error = exc
            time.sleep(1)
        finally:
            engine.dispose()

    pytest.fail(f"PostgreSQL test environment was not ready in time: {last_error}")


def _remove_postgres_container(container_name: str | None) -> None:
    """清理 pytest 自动 provision 的 PostgreSQL Docker 容器。

    Args:
        container_name: pytest 自动 provision 的容器名；为空时不执行任何清理。
    """

    if not container_name:
        return
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
