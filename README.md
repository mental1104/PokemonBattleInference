# PokemonBattleInference

一个用于宝可梦对战推演与伤害计算的 FastAPI 服务。

## 项目结构

```
PokemonBattleInference/
├── pokeop/
│   ├── api/                 # FastAPI schema/router（后续网关层）
│   ├── application/         # 不依赖网关的业务用例与服务
│   ├── assets_data/         # PokeAPI CSV 静态数据（symlink）
│   ├── assets_static/       # Swagger UI 等静态资源
│   ├── domain/              # 领域模型与能力、伤害计算逻辑
│   ├── infrastructure/      # 连接池、日志、外部系统客户端等通用基础设施适配
│   └── persistence/         # ORM model、DAO、DB schema、物化视图、数据导入
├── scripts/                 # 数据库/维护脚本
├── tests/                   # Pytest 用例
├── requirements.txt
└── run.sh
```

## 开发与运行

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
2. 设置 `PYTHONPATH` 方便直接导入包（本地与容器均可）：
   ```bash
   export PYTHONPATH=$PYTHONPATH:/data/PokemonBattleInference
   ```
3. 本地启动 FastAPI 服务：
   ```bash
   uvicorn pokeop.main:app --reload
   ```
4. 或者使用 Docker：
   ```bash
   cp .env.compose.example .env.compose
   # 修改 .env.compose 中的 POSTGRES_PASSWORD 后启动三服务
   make compose-up
   ```

## Calculator v0.1 本地 Compose

本仓库提供项目隔离的三服务 Compose 基线：

```text
frontend  →  backend  →  postgres
41100        41104       41132
```

首次启动：

```bash
cp .env.compose.example .env.compose
make compose-up
```

常用操作：

```bash
make compose-ps
make compose-logs
make compose-down
make compose-rebuild
```

显式清空当前项目 PostgreSQL volume：

```bash
make compose-reset
```

`.env.compose` 不提交仓库。默认 Compose project name 是
`pokemon-battle-inference`，容器、network 和 volume 都由该 project namespace
隔离；普通 `make compose-down` 不删除数据库数据。默认发布端口保留在
`41100-41199`，可通过 `.env.compose` 中的 `POKEOP_FRONTEND_PORT`、
`POKEOP_BACKEND_PORT`、`POKEOP_POSTGRES_PORT` 覆盖。

访问入口：

```text
前端：http://127.0.0.1:41100
FastAPI：http://127.0.0.1:41104/docs
健康检查：http://127.0.0.1:41104/healthz
```

## 数据与脚本

- `scripts/` 目录包含数据库维护脚本，默认读取 `pokeop/assets_data` 中的 CSV。
- 执行脚本前请确保数据库环境变量已设置（`PGUSER/PGPASSWORD/PGHOST/...`）并运行：
  ```bash
  python3 scripts/reset_postgres_db.py --with-materialized-views
  ```

## 测试

```bash
pytest tests
```

## 第三方数据与许可

本项目使用 PokeAPI 的 `data/v2/csv` 数据，详见
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。
