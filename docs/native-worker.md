# Go 持久化 Worker

`server/cmd/pbi-worker` 从 PostgreSQL 的冻结 Go 任务定义领取工作，通过独立 `pbi-core-worker` 进程计算，再将结果和计数原子提交到原运行表。它不调用 Python、不在 Go 重写概率或战斗规则，也不会领取没有 Go 冻结定义的旧 Python 任务。

当前可执行切片是单个正式 `graph` 批次；这是真实图/SCC/精确求解，尚未代替完整宝可梦配置推演。正式 `fixed_battle` 操作及其实际构图进度正在另一批次接入，不能将本切片当作 P3/P6 已完成。

任务首次领取与过期恢复都匹配明确的 calculation revision；运行时按冻结规格的 process_count 并行，最多八个原生子进程。只有有效 owner 才能续租和写结果，失去租约立即回收自己的子进程。队列、用例与稳定结果都在 PostgreSQL 中，daemon 重启不会丢弃已提交用例或重复增加完成计数。

用户取消会停止后续领取并回收活跃子进程，保存 cancelled 终态；daemon 自身停机则保留未确认租约供下一 owner 过期恢复。当前单响应执行模式的取消策略是杀死并等待确切原生子进程，后续进度模式将单独验证协作取消与宽限。所有错误分类保留原结果合同，截断或未解决图不产生默认胜率。CGO fatal 可能以 exit=2 退出，因此仅退出码与完整 ABI 错误 JSON 同时匹配才认定业务拒绝，其他信号/损坏输出属于 worker_crash。

结果保存原生引擎/规则版本、精确分数与视角，完整输入保留在冻结定义。分页摘要不会复制全部 SCC；未来完整战斗图仍须通过对应 API 按需重算，不能声称已经交付该接口。

## 运行条件

先由独立初始化步骤建立原运行表与 Go 冻结定义表。daemon 必须收到 `PBI_POSTGRES_DSN`、`-revision` 和绝对 `-native-executable`，不会自行导入知识或破坏已有数据库。默认 lease 为 120 秒、heartbeat 为 20 秒、取消/队列轮询为 250 毫秒；构造时拒绝不安全的相对路径和租约时序。数据库错误不输出连接字符串，交给外层监督者重启。

`pbi-healthcheck` 是无 shell/curl 运行镜像中的 HTTP 探针；从 `PBI_LISTEN` 推导本机地址，成功时退出 0，不输出响应或凭据。

## 实际验证

2026-11-24：`tools/migration/validate-native-worker.sh` 使用已声明的 maintenance、只读源码、独立 tmpfs PG 与真实原生可执行文件验证。输入为已构建 Core archive，使用 `PBI_NATIVE_CORE_BUILD_DIR` 指定容器内路径；报告根可按已有 `POKEOP_REPORT_ROOT` 配置。

最终 **五项真实 PostgreSQL/独立原生进程测试 PASS**（3.616 秒），`go test -a -race` 与 `go vet` 通过：

1. 真正 `pbi-worker` daemon 进程消费持久化任务，空闲后 SIGTERM 正常退出。
2. 并行原生子进程得到精确 `1/3`、`2/3`、期望一回合；攻守视角转换不改变原概率，重启不重复处理终态。
3. daemon 停机保留已确认工作和未确认租约，新 owner 过期后恢复全部用例。
4. 用户取消停止队列/活跃子进程，最终所有进度桶守恒。
5. 原生拒绝、不完整图和引擎版本不一致保存明确非成功结果，不伪造成平局或零胜率。

证据在 `/volume1/homes/mental1104/Backup/PokemonBattleInference/nativeworker-20261124/final/`，含 archive 摘要、构建/race/vet 与精确 PG 实例日志。第一次四项业务测试通过后 `go vet` 捕获外包结构体未命名字段，修正为命名字段后最终五项重跑通过；首次证据保留在相邻 `acceptance/`。自有实例退出后已自动移除，不涉及生产切换。
