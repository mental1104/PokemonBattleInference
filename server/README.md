# Go 服务端（P3 进行中）

当前可运行入口是 `cmd/pbi-server`，默认监听 `127.0.0.1:41105`，可显式设置 `PBI_LISTEN`。只提供：

- `GET /healthz`
- `POST /v1/core/calculate`：原样交给版本化 C ABI 的 JSON 批次，返回引擎/规则版本和精确结果。

JSON 输入、资源限制、内存与取消合同见 `contracts/c/README.md`。没有在 Go 中复制计算规则；CGO 的 C 指针不越过调用生命周期，响应复制后立即用 Core allocator 释放。context 取消传播至原生原子令牌。

从仓库根先 `make test-core`，再在 server 中使用 `CGO_LDFLAGS="-L$(pwd)/../build/core" go build -a -o ../build/pbi-server ./cmd/pbi-server`。库目录必须是绝对路径，因为 CGO 的编译目录与 shell 工作目录不同。外部静态库变更不会被 Go 缓存自动检测，因此保留 `-a`。`make test-native` 自动准备库路径并委托 `go test -a -race` 与 `go vet`。

NAS 独立 HTTP 验收由 `bash tools/migration/accept-go-core.sh` 自动执行，读取固定向量、启动一次性实例、用容器外 curl 核对实际响应、保存证据并回收实例。它不切换现有部署。

旧 FastAPI 的 41 项 HTTP、PostgreSQL、Worker/lease/heartbeat/幂等/进度/恢复/取消/分页及完整图重算尚未迁移；当前服务不能替代旧后端，也尚未接通现有 Vue。复杂推演的 CGO 进程故障隔离必须随独立 Worker 实现，不能用本同步入口冒充完成。
