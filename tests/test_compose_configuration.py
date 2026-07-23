from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repository_root_has_no_dotenv_files() -> None:
    """仓库根目录不应再保留任何 `.env*` 配置文件。

    Compose 是本地服务、端口和连接参数的唯一配置源；该断言同时防止示例文件、
    生成文件或真实凭据重新以 `.env*` 形式进入仓库。
    """
    dotenv_paths = sorted(path.name for path in REPO_ROOT.glob(".env*"))

    assert dotenv_paths == []


def test_compose_owns_service_ports_and_runtime_settings() -> None:
    """Compose 应直接声明服务端口、数据库参数和 backend 启动命令。

    该断言保护配置所有权边界：Makefile 只调用 Compose，backend 镜像只负责提供
    运行环境，不再通过 dotenv 插值或 Dockerfile 默认命令维护第二份运行配置。
    """
    compose_text = (REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
    makefile_text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    backend_dockerfile = (REPO_ROOT / "Dockerfile.backend").read_text(encoding="utf-8")

    assert "${" not in compose_text
    assert "env_file:" not in compose_text
    assert '"41100:80"' in compose_text
    assert '"41104:41104"' in compose_text
    assert '"41132:5432"' in compose_text
    assert "POSTGRES_DB: *postgres-database" in compose_text
    assert "POSTGRES_USER: *postgres-user" in compose_text
    assert "POSTGRES_PASSWORD: *postgres-password" in compose_text
    assert 'command: ["uvicorn", "pokeop.main:app"' in compose_text

    assert "--env-file" not in makefile_text
    assert "COMPOSE_ENV" not in makefile_text
    assert "compose-env-check" not in makefile_text
    assert "compose-port-check" not in makefile_text

    assert "EXPOSE " not in backend_dockerfile
    assert "\nCMD " not in backend_dockerfile
