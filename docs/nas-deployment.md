# NAS 部署与回退

状态：IN_PROGRESS。NAS三服务与HTTPS已部署，完整图库运行验证仍在进行。用户已明确授权部署、反代，以及现有库备份、恢复验证和保留。手机安装仍暂停，最终合并和双真机验收仍为HUMAN_PENDING。

## 固定部署对象

| 对象 | 约定 |
| --- | --- |
| 管理入口 | `homelab-services/tools/nas-management/nas-manage.sh compose`，现有`home`项目 |
| 发布源码 | 注册工作树`/volume2/code/worktrees/PokemonBattleInference/nas-release`，固定提交后部署 |
| 服务 | `pokemon-frontend`、`pokemon-backend`、`pokemon-worker`；一次性`pokemon-db-init` |
| 数据库 | 共享PG17的`pokemon_battle_inference`与原普通账号`pokeop`，不新建常驻PG |
| 私有连接 | `/volume2/docker/pokemon-battle-inference/settings.env`，目录700、文件600，不入Git |
| 入口 | DSM HTTPS → `127.0.0.1:41110` → Nginx → Go API；API与数据库无宿主发布端口 |
| DNS/证书 | 现有域名解析为NAS局域网地址，复用DSM通配证书；不增加公网映射 |
| App服务器 | `https://pokemon.mental1104.xyz/api`；Web自动使用同源`/api/` |
| 知识清单 | `/knowledge/pokeapi-1567d53073a0-7e4be433ddb6/manifest.json`，同目录`knowledge.sqlite` |

同步账户头沿用可信局域网/VPN入口合同，不是互联网身份验证。本部署不对外新增公网入口。清单对应真实捆绑数据，发布同版本包不宣称人工新版本切换已验收。

## 已执行的备份与兼容验证

证据根：`/volume1/homes/mental1104/Backup/PokemonBattleInference/nas-deployment-20261125/`。

1. 共享数据库维护脚本生成一致性custom归档、无密码角色关系、版本和SHA清单；归档约7.6MiB，原库约155MiB，文件校验全部通过。
2. `compose.nas-recovery.yaml`启动独占、无宿主端口的PG17维护实例，完整`pg_restore --exit-on-error --no-owner --no-privileges`退出0。
3. `nas-legacy-fingerprints.sql`在源库与恢复库的只读事务中核对181张业务表：行数和完整有序行摘要逐字一致。原库没有运行时用户表，图片表为空。
4. 固定`pokemon-go-data:p6-a3f0ff7`在恢复副本显式接管成功，逐表核对177个CSV表、1,051,052行；来源为`1567d53073a069b6c96e1c393c5c490f602e3ab5`。维护实例和网络已回收。
5. 确认无活动应用连接、原角色为受限普通账号后，准备私有连接凭据。原凭据回退语句保存在私有HDD文件，不打印或提交，不改角色权限/HBA。

## 发布与验证顺序

恢复副本接管通过后，已对原库显式接管并核对原181张表全部数据摘要不变；三应用服务已定向启动。105,947素材的独立运行、重启、备份、不同镜像回退和恢复继续进行，原库完整图片待该验证后导入。`compose.nas.yaml`归应用仓库维护，不重建共享PG或其他home服务。

DSM维护入口调用固定`tools/deploy/nas-proxy.sh`，只接受snapshot/create/assign/sync/test/reload/final。先保存全部反代及证书绑定，再通过官方本地API创建固定域名/回环端口规则、绑定既有证书、检查Nginx配置并重载；最终核对其他规则未变。

实际HTTPS已通过证书链及域名核验（OpenSSL Verify return code 0）；NAS curl未跳过证书校验，API健康与42项冻结Core完整响应通过。DSM最终核对只有本应用规则新增、其他规则未变。重载前曾命中DSM默认Synology证书而失败，完成明确证书同步和重载后成功，原始失败留档；证书分配首试发生在create未结束时，被UUID守卫拒绝，未产生写入，create终态成功后重试通过。

版本化SQLite下载413,696字节，SHA为`97077d1074f39a83e89aa3b0f7b0dff9bb6db7b89821e502e497bf924d86d44f`；Range0–63真实206/64字节，未知版本404。浏览器维护服务通过真实HTTPS访问现有服务，报告目录必须显式提供；完整图片模式还须`PBI_NAS_REQUIRE_SPRITES=1`。

剩余通过标准：完整浏览器业务、任务完成/取消和完整图片。健康与HTTP202不能代替业务终态。

## 回退边界

不自动删除原库、归档、素材、旧镜像或用户数据。首次发布失败时停本应用服务并保留数据库与日志；只撤回本应用新增域名，不能覆盖其他DSM规则。

镜像回退仍复用向后兼容库。数据库恢复进入独立目标，不能对生产执行`--clean`或DROP；接收新写入后先冻结并保存差异，不能直接用旧归档覆盖。私有`role-credential-rollback.sql`只供停止新应用后恢复原凭据，不能打印到终端。

## 浏览器与应用重启实测

`browser-preflight/browser/acceptance.json`为PASS：真实HTTPS上的配置管理、求解、221节点/576边任务完成、运行取消、图分支回访、实时快照与战报均通过，0 JavaScript错误。此轮未开启完整图片断言。三个应用容器重启后，健康通过且配置列表前后逐字一致；共享PG未重启。其他DSM证书绑定的规范化比较也一致。

28.7GB是服务端完整上游图片源，不是Swift安装包。Swift首装知识SQLite为413,696字节。图片正文尚未导入正式NAS库：独立全量验证首次触发20分钟截止，已保留失败证据并回滚。初始化CLI现可显式增加总时限，默认仍20m；完整重跑需选择2h，不能将超时算成图片验收成功。失败独占PGDATA正常停机后通过固定维护入口清理，释放约15GB，HDD源与归档保留。
