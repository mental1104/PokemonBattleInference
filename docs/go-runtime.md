# Go/C++ 独立运行入口

状态：IN_PROGRESS。`deploy/compose.go-runtime.yaml`已通过维护入口Compose2.40.3解析及实际隔离启动预检；Make启动/停止顺序dry-run、原Compose约束测试3/3通过。新配置真实PG独占bind、API健康、Vue/Nginx回环端口、42项Core完整响应及离线浏览器依赖缓存均通过。**完整图库四角色重启/回滚/恢复尚未执行**；已有完整业务证据来自`go-stack-validation.md`，不能冒充该新入口的全量验收。

预检证据为`Backup/PokemonBattleInference/runtime-full-20261125/preflight-ready/`，应用源码d3fbb97、镜像`pokemon-go-{server,data,frontend}:p6-d3fbb97`。PG内置SHA256与宿主独立结果相同，Core实际HTTP响应完整等于42项冻结向量。预检退出0，自有实例和网络已回收，PG目录保留。初次发现internal网络未发布前端端口，修正为普通项目bridge，仅前端发布回环；API/PG仍不发布端口。PGDATA明确指定对应bind，避免维护入口叠加继承其他目录。验收就绪检查等待正式TCP服务且目标库实际执行SELECT 1，避免initdb临时socket服务提前被判断为初始化完成。

后续将实际发布配置中的PG健康探针也改为TCP `psql ... SELECT 1`，防止Compose的service_healthy在临时socket阶段提前解锁db-init。`runtime-full-20261125/preflight-health-ready/`使用同一真实配置和已验证r2镜像，实际Docker探针返回1并达到healthy；独立TCP SQL、PG SHA、Nginx回环、42项Core全响应和离线npm缓存均通过，退出0。配置/探针日志、执行脚本及实际image元数据已归档，自有实例/网络已清理。前一次预检首个Nginx连接被重置（退出56），保留原文；验收客户端改为有界等待真实代理健康，超时仍明确失败，完整普通模式栈r3也已复验通过。

该入口保留frontend、backend、worker、postgres职责，另有一次性ops/db-init。API和Worker使用`deploy/Dockerfile.go`的Go/C++镜像，初始化器使用独立CSV镜像；运行时不含Python。默认项目为`pokemon-go-preview`、Web仅绑定`127.0.0.1:41110`，API与PG不发布宿主端口。原`docker-compose.yaml`及`make compose-*`保持原Python路径。

## 显式输入

| 变量 | 用途 |
| --- | --- |
| `PBI_GO_SOURCE_ROOT` | 干净的固定源码checkout；Make默认本仓库根目录。 |
| `PBI_GO_POSTGRES_ROOT` | 预先准备的、归属明确的独占PG目录；bind禁止自动创建缺失路径。NAS运行状态放`/volume2/docker/`所属应用目录。 |
| `PBI_GO_SPRITES_ROOT` | 已完整检出并校验的PokeAPI sprites源；只读bind，不进入镜像。 |
| `PBI_GO_SPRITES_COMMIT` | 已核实的素材commit，不根据目录名猜测来源。 |
| `PBI_GO_SUBNET` | 已与宿主路由和Docker IPAM核对的空闲子网。 |
| `PBI_GO_SERVER_IMAGE` / `PBI_GO_DATA_IMAGE` / `PBI_GO_FRONTEND_IMAGE` | 本次构建/发布镜像标签；默认各自的preview标签，回退应传入留存的已验证版本。 |
| `GO_COMPOSE_PROJECT` | Make项目名，默认`pokemon-go-preview`；不得复用未知或旧生产项目名。 |
| `PBI_GO_BIND` / `PBI_GO_PORT` | Web监听，默认回环41110；实际HomeLab发布地址仍待Human确认。 |

编译阶段需要已验证的`pokemon-migration-validation:local`工具镜像，或通过Docker build参数提供等价工具链。初始来源固定PokeAPI1567d530和sprites c0542f7；不得用五图验收样本代替完整素材。

## 启动、停止与数据保留

准备上述显式输入后，`make go-compose-config`只输出服务名。`make go-compose-build`构建API、数据和Vue镜像；`make go-compose-init`启动PG、等其健康后执行一次性纯Go初始化。`make go-compose-up`在初始化成功后启动API、独立Worker和Vue，API探针通过后前端才启动。任何初始化失败都会阻止后续角色启动。

Worker版本固定为原公开任务的`battle-inference.summary-exploration.v2`，默认lease120秒、heartbeat20秒，不能改成任意验收版本号。SIGTERM清理实际计算子进程，未确认租约由恢复路径处理。

`make go-compose-ps`和`make go-compose-logs`检查本项目。`make go-compose-down`只停止该项目并移除网络，不删除PG目录；没有Go自动reset目标。新启动后仍使用同一显式PG目录，完整图库无需放入2GiB tmpfs。

## 升级及回退边界

默认Go知识初始化仍仅接受空库或相同Go版本标记的库。原Python历史库必须使用新增的显式`pbi-db-init --csv-root <固定CSV目录> --adopt-legacy-knowledge`入口：在同一事务里按固定生成模型比较列顺序、类型、可空性及主键/唯一/CHECK/FK，再流式构造自有临时期望表，双向EXCEPT ALL比较每个字段和重复行语义。SHARE锁阻止核对后、登记前的并发写入；历史raw数据和序列不被改写。任何不一致或中断都回滚，默认入口不会隐式接管。

接管输出`legacy_adopted=true`，`inserted_rows`是已核验的规范数据行数，不表示重新插入历史表。后续普通初始化可按版本正常复用。该入口只识别当前固定PokeAPI来源；不同知识版本仍明确拒绝，尚不是任意版本迁移器。不应删除版本表或清空raw表绕过保护。

`tools/migration/accept-go-legacy-adoption.sh`在专属空PG用原Python的RawBase和CSV importer建立177表、1,051,800条来源记录及五张上游图片样本，加入原用户配置和任务后实际接管Go。全部接管前已有raw/runtime表及序列的导出，在接管前/后/再次复用三个时点逐字节一致，统一SHA-256为`e7bed0bac2e45a6cf494f6db1d6afde015d013e001859ed81e77862fc41284d8`。这里只去除pg_dump随机执行令牌，不删除业务字段。五图是历史BYTEA保留样本，不替代完整图库导入。原始证据位于`Backup/PokemonBattleInference/legacy-adoption-20261125/python-first/`。

隔离演练已证明两个已验证Go镜像之间回退、真实pg_dump及恢复到独立库后，用户配置完整JSON不变。新运行入口仍需完整素材导入、重复初始化、实例重启、当前镜像/旧镜像及独立恢复库的同轮验收。镜像回退应保留数据库，不能用down -v或清空目录实现。

完整素材验收使用`PBI_STACK_RUNTIME_COMPOSE=1 bash tools/migration/validate-go-stack.sh`，额外显式提供`PBI_STACK_SPRITES_ROOT`、从固定Git树核对的`PBI_STACK_EXPECTED_SPRITE_COUNT=105947`、`PBI_SPRITES_SOURCE_COMMIT`及不存在的新`PBI_STACK_POSTGRES_DATA_ROOT`。其他固定源码、三镜像、已验证旧镜像、子网和报告变量沿用`go-stack-validation.md`。维护overlay仅增加验收客户端和资源限制，不改变实际挂载、Worker版本或探针。脚本将检查初次导入全部数量/每个BYTEA SHA，真实停止PG后在同一目录重启，复用初始化与用户配置/全图校验，再执行镜像回退及独立恢复库全图校验。此分支尚待完整素材展开完成后实际运行；不把预检或五图样本计为全量成功。

正式数据库备份、生产切换和最终合并仍按原Goal由Human确认；本文不表示已执行这些操作。手机安装暂停，不把临时验证容器当成已提供给双设备的长期测试服务。
