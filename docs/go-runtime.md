# Go/C++ 独立运行入口

运行入口验收：PASS，范围为当前选取的全图鉴小图包。17a5fda的`deploy/compose.go-runtime.yaml`完整隔离验收已通过：1,374张/20,079,618字节正文存HDD，PG只存元数据；独立逐文件SHA、真实Vue图片和业务、42项Core响应、四角色与PG重启、重复初始化、拒绝不兼容候选后的恢复，以及元数据备份/独立恢复均通过。证据为`Backup/PokemonBattleInference/filesystem-assets-20261125/runtime-r1/`。不再要求部署105,947文件/28.7GB全来源素材。

实际NAS使用独立的`deploy/compose.nas.yaml`接入home项目，复用共享PG17；已获授权并部署，Web为`https://pokemon.mental1104.xyz/`，App API为同域`/api`。操作入口、私有配置、真实镜像ID及备份/恢复见[nas-deployment.md](nas-deployment.md)。下面的独立运行入口使用自己明确准备的PG目录，不用于重建或替换NAS共享PG。

以下两段保留d3fbb97时期的历史预检和失败说明；当前完整验收以上述17a5fda结果为准。

预检证据为`Backup/PokemonBattleInference/runtime-full-20261125/preflight-ready/`，应用源码d3fbb97、镜像`pokemon-go-{server,data,frontend}:p6-d3fbb97`。PG内置SHA256与宿主独立结果相同，Core实际HTTP响应完整等于42项冻结向量。预检退出0，自有实例和网络已回收，PG目录保留。初次发现internal网络未发布前端端口，修正为普通项目bridge，仅前端发布回环；API/PG仍不发布端口。PGDATA明确指定对应bind，避免维护入口叠加继承其他目录。验收就绪检查等待正式TCP服务且目标库实际执行SELECT 1，避免initdb临时socket服务提前被判断为初始化完成。

后续将实际发布配置中的PG健康探针也改为TCP `psql ... SELECT 1`，防止Compose的service_healthy在临时socket阶段提前解锁db-init。`runtime-full-20261125/preflight-health-ready/`使用同一真实配置和已验证r2镜像，实际Docker探针返回1并达到healthy；独立TCP SQL、PG SHA、Nginx回环、42项Core全响应和离线npm缓存均通过，退出0。配置/探针日志、执行脚本及实际image元数据已归档，自有实例/网络已清理。前一次预检首个Nginx连接被重置（退出56），保留原文；验收客户端改为有界等待真实代理健康，超时仍明确失败，完整普通模式栈r3也已复验通过。

该入口保留frontend、backend、worker、postgres职责，另有一次性ops/db-init。API和Worker使用`deploy/Dockerfile.go`的Go/C++镜像，初始化器使用独立CSV镜像；运行时不含Python。默认项目为`pokemon-go-preview`、Web仅绑定`127.0.0.1:41110`，API与PG不发布宿主端口。原`docker-compose.yaml`及`make compose-*`保持原Python路径。

## 显式输入

| 变量 | 用途 |
| --- | --- |
| `PBI_GO_SOURCE_ROOT` | 干净的固定源码checkout；Make默认本仓库根目录。 |
| `PBI_GO_POSTGRES_ROOT` | 预先准备的、归属明确的独占PG目录；bind禁止自动创建缺失路径。NAS运行状态放`/volume2/docker/`所属应用目录。 |
| `PBI_GO_SPRITES_ROOT` | 经过核验的HDD快照父目录，必须包含`<项目提交>/sprites/`；只读挂载，不是28.7GB上游工作树或其sprites子目录。 |
| `PBI_GO_SPRITES_COMMIT` | 拥有已发布小图包的项目40位Git SHA；当前已验版本为17a5fdac3567c4da0f855fe69efe29935a5a8087，不是上游sprites提交c0542f7。 |
| `PBI_GO_SUBNET` | 已与宿主路由和Docker IPAM核对的空闲子网。 |
| `PBI_GO_SERVER_IMAGE` / `PBI_GO_DATA_IMAGE` / `PBI_GO_FRONTEND_IMAGE` | 本次构建/发布镜像标签；默认各自的preview标签，回退应传入留存的已验证版本。 |
| `GO_COMPOSE_PROJECT` | Make项目名，默认`pokemon-go-preview`；不得复用未知或旧生产项目名。 |
| `PBI_GO_BIND` / `PBI_GO_PORT` | 独立预览Web监听，默认回环41110；NAS已授权的域名入口另由NAS配置管理。 |

编译阶段需要构建器可见的已验证工具链。NAS统一构建器使用`tools/deploy/build-nas-images.sh`及其固定OCI工具链上下文，不能假定Docker Engine中的本地工具镜像也对共享BuildKit可见。知识来源固定PokeAPI1567d530；图片清单另记录上游c0542f7，实际交付只选每ID一份菜单PNG：1,350宝可梦、5道具、19属性，共1,374张。

## 启动、停止与数据保留

先通过`tools/deploy/prepare-sprite-snapshot.sh`准备小图快照：参数1是干净且已提交的`data/assets/scarlet-violet`绝对目录，参数2必须等于该checkout的项目HEAD，参数3为HDD快照父目录。工具逐张检查数量/SHA和32MiB预算，然后发布到`<父目录>/<项目SHA>/`；已有同版本必须逐字匹配，不覆盖历史快照。实际NAS已发布17a5fda快照，纯文档或CI变更不要求为同一包重新导入或改名。

以下105,947路径记录是解析器历史全来源回归，不是运行所需的图片数量。固定sprites commit c0542f7、子树ec56a5fae60f2a6363083d7d0581271744673695，由`git ls-tree -rz --name-only <commit>:sprites`导出NUL清单，`tools/migration/export_sprite_path_reference.py --paths <清单> --output <JSONL>`直接调用原Python解析器与MIME函数。Go测试`TestSpritePathsFullPythonReference`读取显式`PBI_TEST_SPRITE_REFERENCE_JSONL`，逐项比较全部14字段、NULL/false和MIME，同时拒绝重复路径；缺省数据集明确SKIP，显式文件错误失败。

`sprite-metadata-full-20261125/`中105,947条唯一路径全部一致，race下该全路径用例6.53秒，另两项既有边界/manifest用例及knowledge vet通过。导出工具/新增测试Ruff0.17.6和strict mypy2.4.1通过。首个失败揭示原Python3.11缺少WebP MIME注册，按BASE-ASSET-MIME-001独立修复（e8b2f6b），保留未修参考和失败日志，再生成新参考；全部元数据及所有非WebP记录前后逐字节相同，只改变16,526条WebP MIME。参考文件/清单SHA已保存。这里验证的是完整路径语义，不代替图片正文、数据库导入或备份恢复；原PNG选图MV未改变。

准备上述显式输入后，`make go-compose-config`只输出服务名。`make go-compose-build`构建API、数据和Vue镜像；`make go-compose-init`启动PG、等其健康后执行一次性纯Go初始化。`make go-compose-up`在初始化成功后启动API、独立Worker和Vue，API探针通过后前端才启动。任何初始化失败都会阻止后续角色启动。

Worker版本固定为原公开任务的`battle-inference.summary-exploration.v2`，默认lease120秒、heartbeat20秒，不能改成任意验收版本号。SIGTERM清理实际计算子进程，未确认租约由恢复路径处理。

`make go-compose-ps`和`make go-compose-logs`检查本项目。`make go-compose-down`只停止该项目并移除网络，不删除PG目录；没有Go自动reset目标。新启动后仍使用同一显式PG目录，图片正文一直从只读HDD快照读取，不写入PG或数据库tmpfs。

## 升级及回退边界

默认Go知识初始化仍仅接受空库或相同Go版本标记的库。原Python历史库必须使用新增的显式`pbi-db-init --csv-root <固定CSV目录> --adopt-legacy-knowledge`入口：在同一事务里按固定生成模型比较列顺序、类型、可空性及主键/唯一/CHECK/FK，再流式构造自有临时期望表，双向EXCEPT ALL比较每个字段和重复行语义。SHARE锁阻止核对后、登记前的并发写入；历史raw数据和序列不被改写。任何不一致或中断都回滚，默认入口不会隐式接管。

接管输出`legacy_adopted=true`，`inserted_rows`是已核验的规范数据行数，不表示重新插入历史表。后续普通初始化可按版本正常复用。该入口只识别当前固定PokeAPI来源；不同知识版本仍明确拒绝，尚不是任意版本迁移器。不应删除版本表或清空raw表绕过保护。

`tools/migration/accept-go-legacy-adoption.sh`在专属空PG用原Python的RawBase和CSV importer建立177表、1,051,800条来源记录及五张上游图片样本，加入原用户配置和任务后实际接管Go。全部接管前已有raw/runtime表及序列的导出，在接管前/后/再次复用三个时点逐字节一致，统一SHA-256为`e7bed0bac2e45a6cf494f6db1d6afde015d013e001859ed81e77862fc41284d8`。这里只去除pg_dump随机执行令牌，不删除业务字段。五图是历史BYTEA保留样本，不替代完整图库导入。原始证据位于`Backup/PokemonBattleInference/legacy-adoption-20261125/python-first/`。

当前小图HDD入口的导入、重复初始化、全部角色/PG重启及独立恢复已在同一轮通过，配置完整JSON、1,374条元数据清单和图片正文保持一致。旧BYTEA-only镜像不认识NULL/HDD正文，即使healthy也会返回错误图片；演练实际拒绝该候选并返回已验证HDD版本。回退目标必须支持相同存储合同并通过图片验收，不能只看健康状态。镜像回退保留数据库和HDD快照，不能用down -v或清空目录实现。

完整小图栈验收使用`PBI_STACK_RUNTIME_COMPOSE=1 bash tools/migration/validate-go-stack.sh`，额外显式提供HDD快照父目录`PBI_STACK_SPRITES_ROOT`、`PBI_STACK_EXPECTED_SPRITE_COUNT=1374`、项目SHA `PBI_SPRITES_SOURCE_COMMIT`及不存在的新`PBI_STACK_POSTGRES_DATA_ROOT`。三镜像已经统一构建器构建时，显式设置`PBI_STACK_PREBUILT_IMAGES=1`，仍记录并核验真实image ID。其他固定源码、三镜像、不兼容旧候选、已核对空闲子网和私有HDD报告变量由调用方提供。脚本确认PG正文全部NULL，独立无网络客户端逐份核验HDD正文，再执行真实重启、幂等、候选拒绝/恢复和独立库恢复，已验结果见本页开头。

本次NAS部署、域名和原库备份/恢复/保留已获授权且验证通过。数据库备份不包含HDD图片正文，恢复时还需对应版本快照或已提交图标包。最终合并及双真机验收仍待，手机安装继续暂停；供验收的长期NAS服务与知识更新源见iphone-ipad-acceptance.md。

## 初始化时限与历史大图库尝试

`pbi-db-init --timeout`必须为正duration，默认20m；独立运行Compose通过`PBI_GO_INIT_TIMEOUT`显式传入，验收覆盖变量为`PBI_STACK_INIT_TIMEOUT`。该时限覆盖CSV、所选图片校验/元数据写入和运行表初始化，不改变Core请求限制；当前20.1MB小包已经在默认时限内验收通过，不要求2小时导入。

历史28.7GB/105,947文件的BYTEA尝试触发20m截止并回滚图片事务，证据位于`runtime-full-20261125/full-a3f0ff7/`，不标PASS，也不继续重跑。该范围已由用户改为所选小图包和HDD正文。Swift除约404KiB离线SQLite外，已随包携带同一批1,374张/20.1MB小图；两端都不部署全来源大图库。
