# Go 服务端（P3 进行中）

`cmd/pbi-server` 默认监听 `127.0.0.1:41105`，可设置 `PBI_LISTEN`。无数据库连接时提供 `GET /healthz` 与 `POST /v1/core/calculate`；Core JSON 合同见 `contracts/c/README.md`。

显式设置 `PBI_POSTGRES_DSN` 后，启用原 41 项 API 中的 19 项配置/知识/图片/任务查询取消接口和 P5 用户同步。仅 `PBI_MIGRATE=1` 时非破坏性创建运行表及同步表；默认不执行迁移、CSV 导入或物化视图刷新。可信身份 header 的边界、完整已测范围及剩余任务见 [migration-server.md](../docs/migration-server.md)。

构建需先 `make test-core`，然后在 server 目录设置绝对路径 `CGO_LDFLAGS` 并运行 `go build -a ./cmd/pbi-server`。外部静态库变更不会被 Go 缓存自动检测，必须保留 `-a`；`go test -a -race ./...` 与 `go vet ./...` 执行 Go 检查。PostgreSQL 集成仅接受显式 `PBI_TEST_POSTGRES_DSN`，目录集成另需 `PBI_TEST_CATALOG_DSN` 指向自有临时知识库。

`cmd/pbi-core-worker` 是单请求原生子进程。复杂请求可由 `workerprocess.Execute` 经 stdin/stdout 隔离，不在 Go 中实现第二套战斗规则。PG coordinator、完整推演生命周期及剩余计算 API 正在迁移；当前服务还不能替换原后端。

NAS 实际验证入口为 `bash tools/migration/validate-go-server.sh`：声明的维护服务、自有 tmpfs PG、真实 CSV 与原物化视图、Go race/vet、容器外 curl、证据归档及精确实例清理。它不操作生产部署。Core-only HTTP 验收仍可单独运行 `bash tools/migration/accept-go-core.sh`。
