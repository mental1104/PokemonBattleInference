# PokemonBattleInference

宝可梦对战推演与伤害计算 Monorepo：C++20 计算引擎、Go/PostgreSQL 在线服务、SwiftUI 离线客户端，以及保留的 Vue 前端。

迁移在独立分支进行，当前生产尚未切换。原 Python 实现和测试保留作为行为参考及兼容入口；完整图库部署验收仍在进行。实际阶段结果、失败记录和人工验收状态以[进度与恢复入口](docs/migration-progress.md)为准，原行为映射见[迁移基线](docs/migration-baseline.md)。

| 用途 | 入口 |
| --- | --- |
| Go/C++ 四角色运行、初始化、升级及回退 | [独立运行配置](docs/go-runtime.md)、[真实 Web 整栈验收](docs/go-stack-validation.md) |
| iPhone/iPad 原生客户端 | [iOS 工程](ios/README.md)、[自动化验收依据](docs/migration-ios-acceptance.md) |
| 双设备固定数据与逐步人工验收 | [iPhone/iPad 验收手册](docs/iphone-ipad-acceptance.md) |
| 同步与知识包更新 | [同步实现与证据](docs/migration-sync.md)、[同步合同](contracts/sync-v1.md) |
| Core、跨语言合同和 benchmark | [Core/绑定验收](docs/migration-core-bindings-acceptance.md)、[配置图测量](docs/benchmarks/configuration-graph-20261125.md) |

## 项目结构

```
PokemonBattleInference/
├── core/                    # C++20/CMake；纯计算、规则、精确概率、状态图与搜索
├── server/                  # Go/CGO；HTTP、任务调度、PostgreSQL、同步
├── ios/                     # SwiftUI；C ABI 调用、独立知识/用户 SQLite
├── web/                     # 原 Vue 前端，同源 /api 连接 Go 或兼容 Python
├── data/                    # SQL、版本化离线知识包与同步数据合同
├── contracts/               # 统一 C ABI、HTTP 与同步合同
├── tools/                   # 数据打包、多语言验证和隔离验收工具
├── tests/                   # 原 Python 参考、迁移差分与共享测试向量
├── deploy/                  # Go 运行配置、构建镜像及 maintenance 验收
├── docs/                    # 迁移证据、benchmark、安装与回退说明
├── legacy/pokeop/            # 原Python行为参考；根pokeop是兼容导入软链
│   ├── api/                 # 保留的原 FastAPI schema/router
│   ├── application/         # 不依赖网关的业务用例与服务
│   ├── assets_data/         # PokeAPI CSV 静态数据（symlink）
│   ├── assets_static/       # Swagger UI 等静态资源
│   ├── domain/              # 领域模型与能力、伤害计算逻辑
│   ├── infrastructure/      # 连接池、日志、外部系统客户端等通用基础设施适配
│   └── persistence/         # ORM model、DAO、DB schema、物化视图、数据导入
├── scripts/                 # 数据库/维护脚本
├── requirements.txt
└── run.sh
```

原 Python 实体位于 `legacy/pokeop/`，根 `pokeop` 软链保留原导入名；CSV软链与common/素材根定位已按新层级调整，运行数据不随源码移动。此布局在独立工作树验证，完整替代验收后再纳入主迁移分支。

## Go/C++ 与原生客户端开发

Go 运行入口为 `deploy/compose.go-runtime.yaml` 和独立的 `make go-compose-*`。显式配置固定源码、独占 PostgreSQL 目录、完整图片来源、镜像和已核对的子网后，按[运行说明](docs/go-runtime.md)执行初始化与启动。默认 Web 为回环 `127.0.0.1:41110`，API/PG 不发布宿主端口；运行镜像不包含 Python。完整素材导入、PG 重启和全图备份恢复尚待同轮验收，不能把现有普通模式回归当作完整图库发布完成。

SwiftUI 工程、Core 静态库、模拟器测试与真机验收分别见 [ios/README.md](ios/README.md) 和[验收手册](docs/iphone-ipad-acceptance.md)。Apple 签名、设备安装和最终使用体验保持各自授权边界，模拟器成功不代填人工验收。

## 原 Python 兼容开发与运行

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

## 原 Python 本地 Compose

保留的 `docker-compose.yaml` 使用 frontend、backend、worker、postgres 四个角色和一次性 db-init；以下 `make compose-*` 仍调用 Python 配置。

```text
frontend  →  backend  →  postgres  ←  worker
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
- `.gitmodules` 当前只登记 `submodules/pokeapi` 和 `submodules/common`。初始化已登记来源：
  ```bash
  git submodule update --init submodules/pokeapi submodules/common
  ```
- sprites 是单独准备的固定版本完整来源，通过只读 bind 导入 PostgreSQL，不进入 frontend/backend 镜像层。Go 配置显式使用 `PBI_GO_SPRITES_ROOT` 和 `PBI_GO_SPRITES_COMMIT`；完整来源检查见[运行说明](docs/go-runtime.md)。原 Python 配置保留 `POKEOP_SPRITES_DIR` 及顶层/嵌套兼容挂载；未登记的 `submodules/pokeapi-sprites` 不能当作现成 submodule 执行初始化。五图样本只用于独立验收，不等于完整图库。
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
make test
```

macOS/Linux 使用相同入口：先 CMake/CTest，再运行原 Python 回归、真实 C++ 差分及 pytest 委托的 Go race/vet 和 Swift XCTest。工具或外部环境不可用时明确 SKIP，显式错误配置必须 FAIL；有 SKIP 的本地结果不能冒充完整集成验收。Core 构建依赖、单独验证及 NAS 隔离验证见 [core/README.md](core/README.md)，真实 Go/PG/Swift/Worker 证据见[迁移进度](docs/migration-progress.md)。前端继续使用 `cd web && npm test && npm run build`。

## 第三方数据与许可

本项目使用 PokeAPI 的 `data/v2/csv` 数据，详见
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。
