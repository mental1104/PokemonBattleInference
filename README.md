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

默认 Compose project name 由目录名决定，容器、network 和 volume 都由该 project
namespace 隔离；普通 `make compose-down` 不删除数据库数据。默认发布端口固定为
`41100`、`41104` 和仅绑定本机的 `41132`。

访问入口：

```text
前端：http://127.0.0.1:41100
FastAPI：http://127.0.0.1:41104/docs
健康检查：http://127.0.0.1:41104/healthz
```

## 数据与脚本

- `scripts/` 目录包含数据库维护脚本，默认读取 `pokeop/assets_data` 中的 CSV。
- CSV 数据源来自 `submodules/pokeapi`；sprites 图片数据源应作为主仓库直接管理的
  `submodules/pokeapi-sprites` submodule 初始化，不需要递归拉取
  `submodules/pokeapi/data/v2/sprites` 中的嵌套副本：
  ```bash
  git submodule update --init submodules/pokeapi submodules/common submodules/pokeapi-sprites
  ```
- sprites 仅供 `db-init` 通过只读 bind mount 导入 PostgreSQL，已经从 Docker build
  context 排除，不会进入 frontend/backend 镜像层。可用 `POKEOP_SPRITES_DIR` 指向
  PokeAPI/sprites 仓库根目录或其中的 `sprites/` 目录。Compose 的 `db-init`
  同时只读挂载顶层 `submodules/pokeapi-sprites` 和嵌套
  `submodules/pokeapi/data/v2/sprites`；顶层目录未初始化时会自动使用嵌套目录，
  顶层目录包含 `sprites/` 后会自动优先使用顶层数据源。
- 执行脚本前请确保数据库环境变量已设置（`PGUSER/PGPASSWORD/PGHOST/...`）并运行：
  ```bash
  python3 scripts/reset_postgres_db.py --with-materialized-views
  ```

Compose 初始化 CSV、sprites 和物化视图：

```bash
make compose-up
make compose-init
```

## 测试

```bash
pytest tests
```

## 第三方数据与许可

本项目使用 PokeAPI 的 `data/v2/csv` 数据，详见
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。
