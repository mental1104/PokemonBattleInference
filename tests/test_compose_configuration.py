from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repository_root_has_no_dotenv_files() -> None:
    """仓库根目录不应再保留任何 `.env*` 配置文件。

    Compose 是本地服务、端口和连接参数的唯一配置源；该断言同时防止示例文件、
    生成文件或真实凭据重新以 `.env*` 形式进入仓库。
    """
    dotenv_paths = sorted(path.name for path in REPO_ROOT.glob(".env*"))

    assert dotenv_paths == []


def test_compose_owns_service_ports_runtime_settings_and_startup() -> None:
    """Compose 和 Makefile 应共同声明完整的本地服务启动契约。

    该断言保护配置所有权边界：Compose 直接声明端口、数据库参数和进程命令；Makefile
    的 `compose-up` 与 `compose-rebuild` 在一次初始化完成后同时启动 backend、worker
    和 frontend，避免任务成功入库后因 coordinator 未启动而长期停留在 pending。
    """
    compose_text = (REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
    makefile_text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    backend_dockerfile = (REPO_ROOT / "Dockerfile.backend").read_text(encoding="utf-8")

    assert re.search(r"(?<!\$)\$\{", compose_text) is None
    assert "env_file:" not in compose_text
    assert '"41100:80"' in compose_text
    assert '"41104:41104"' in compose_text
    assert '"127.0.0.1:41132:5432"' in compose_text
    assert "POSTGRES_DB: *postgres-database" in compose_text
    assert "POSTGRES_USER: *postgres-user" in compose_text
    assert "POSTGRES_HOST_AUTH_METHOD: trust" in compose_text
    assert "POSTGRES_PASSWORD" not in compose_text
    assert "PGPASSWORD" not in compose_text
    assert 'command: ["uvicorn", "pokeop.main:app"' in compose_text
    assert 'command: ["python3", "-m", "pokeop.workers.battle_inference"]' in compose_text

    assert "--env-file" not in makefile_text
    assert "COMPOSE_ENV" not in makefile_text
    assert "compose-env-check" not in makefile_text
    assert "compose-port-check" not in makefile_text
    assert "$(COMPOSE) up -d backend worker frontend --remove-orphans" in makefile_text
    assert (
        "$(COMPOSE) up -d --force-recreate backend worker frontend --remove-orphans"
        in makefile_text
    )

    assert "EXPOSE " not in backend_dockerfile
    assert "\nCMD " not in backend_dockerfile
