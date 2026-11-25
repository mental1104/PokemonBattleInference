# Go 服务端（P3 进行中）

`cmd/pbi-server` 默认监听 `127.0.0.1:41105`，可设置 `PBI_LISTEN`。无数据库连接时提供 `GET /healthz` 与 `POST /v1/core/calculate`；Core JSON 合同见 `contracts/c/README.md`。

Core HTTP 全部通过真实独立 `pbi-core-worker` 执行。显式 `PBI_CORE_WORKER_PATH` 必须为绝对路径；默认只找 server 同目录的 child，缺少时返回 503，不回退进程内 CGO。默认计算 context 最长30秒，HTTP写超时35秒；请求取消/SIGTERM会回收 child，health仍只表示进程存活。

显式设置 `PBI_POSTGRES_DSN` 后，启用原 41 项 API 中已迁移的28项接口和 P5 用户同步，另有尚存两项兼容缺口的静态calculator。仅 `PBI_MIGRATE=1` 时非破坏性创建运行表及同步表；默认不执行迁移、CSV 导入或物化视图刷新。可信身份 header 的边界、完整已测范围及剩余任务见 [migration-server.md](../docs/migration-server.md)。

构建需先 `make test-core`，然后在 server 目录设置绝对路径 `CGO_LDFLAGS` 并运行 `go build -a ./cmd/pbi-server`。外部静态库变更不会被 Go 缓存自动检测，必须保留 `-a`；`go test -a -race ./...` 与 `go vet ./...` 执行 Go 检查。PostgreSQL 集成仅接受显式 `PBI_TEST_POSTGRES_DSN`，目录集成另需 `PBI_TEST_CATALOG_DSN` 指向自有临时知识库。

`cmd/pbi-core-worker` 是单请求原生子进程。复杂请求可由 `workerprocess.Execute` 经 stdin/stdout 隔离，不在 Go 中实现第二套战斗规则。PG coordinator、完整推演生命周期及剩余计算 API 正在迁移；当前服务还不能替换原后端。

NAS 实际验证入口为 `bash tools/migration/validate-go-server.sh`：声明的维护服务、自有 tmpfs PG、真实 CSV 与原物化视图、Go race/vet、容器外 curl、证据归档及精确实例清理。它不操作生产部署。Core-only HTTP 验收仍可单独运行 `bash tools/migration/accept-go-core.sh`。

`cmd/pbi-db-init` 是纯 Go 显式初始化命令，读取 `PBI_POSTGRES_DSN` 与 `--csv-root`，校验固定源、导入177 CSV并建立原179raw表/8MV；同版本复用且不接管未知非空知识库。独立数据验收由 `bash tools/migration/validate-go-knowledge.sh` 执行，完整来源/类型/许可和版本边界见迁移文档。运行时不需要 Python。

显式 `--sprites-root` 可接收完整 PokeAPI/sprites 仓库或其 `sprites/` 子目录，`--sprites-commit` 可记录固定来源。图片经纯Go写入原BYTEA表，保留完整元数据、原manifest幂等、变更内容、first_seen身份及上游删除失效语义；事务全部成功后刷新两个选图MV。省略该参数不会扫描或改动图库。来源必须是希望登记的完整集合，专用验收样本只用于自有空库。图片不进入API镜像或依赖外部图片CDN。

`tools/migration/accept-go-sprites.sh` 用显式来源与自有空PG验收首次/重跑、原Python完整行及实际公开PNG/ETag；Go包另外验证并发重跑、真实中途SQL失败回滚和删除失效。可选Compose覆盖 `deploy/compose.go-stack-sprites.yaml` 只给db-init增加只读来源，保留四角色边界。来源与实测限制见 `docs/migration-server.md`。
