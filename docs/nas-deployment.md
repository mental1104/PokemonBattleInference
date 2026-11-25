# NAS部署与回退

当前：NAS基础服务和HTTPS已部署并完成业务验收，运行a3f0ff7镜像；新HDD元数据版本及全图鉴图标已开发，等待完整运行栈验收后定向升级。用户已授权NAS部署、pokemon.mental1104.xyz反代、原库备份恢复及保留。手机安装继续暂停，双真机体验和最终合并仍HUMAN_PENDING。

## 已运行的基础服务

home项目管理pokemon-frontend、pokemon-backend和pokemon-worker，三个restart always；复用共享PG17的pokemon_battle_inference库及pokeop普通账号，不增加常驻数据库。前端只绑定127.0.0.1:41110，API和PG无宿主端口。DSM使用既有通配证书直连反代，不增加公网映射；域名当前解析为NAS局域网地址。

- Web：`https://pokemon.mental1104.xyz/`
- App服务器：`https://pokemon.mental1104.xyz/api`
- 知识清单：`https://pokemon.mental1104.xyz/knowledge/pokeapi-1567d53073a0-7e4be433ddb6/manifest.json`
- 发布工作树：`/volume2/code/worktrees/PokemonBattleInference/nas-release`
- 运行定义：发布工作树的deploy/compose.nas.yaml，经nas-manage.sh compose管理。
- 私有DSN：`/volume2/docker/pokemon-battle-inference/settings.env`，目录700/文件600，不打印或提交。

同步账户头仍按可信LAN/VPN入口合同，不是互联网登录凭据。知识URL是实际首装同版本数据，不能代表人工新版本切换验收。

## 实际备份与基础部署验收

证据根为HDD `Backup/PokemonBattleInference/nas-deployment-20261125/`。

原155MiB库已生成custom归档、无密码角色关系和版本/SHA清单，归档约7.6MiB；校验与隔离PG17完整恢复成功。181张业务表行数与完整有序行摘要逐字一致。恢复副本显式Go接管验证177 CSV表、1,051,052行通过，随后原库接管且原181张表摘要保持一致。原图片表为空，没有把28.7GB正文写入正式库。

无活动客户端时准备私有应用凭据，原角色凭据另存私有回退语句，不改角色权限或HBA。共享PG没有重建/重启。

HTTPS证书链及域名验证返回0；正常TLS下健康、42项冻结Core完整响应通过。其他DSM反代和证书绑定的规范化比较均保持一致。SQLite实测413,696字节、SHA 97077d1074f39a83e89aa3b0f7b0dff9bb6db7b89821e502e497bf924d86d44f，Range0–63为206/64字节，未知版本404。

browser-preflight通过真实HTTPS验证配置增改/重载/删除、求解、221节点576边任务完成、运行取消、图分支回访、实时快照和战报，0 JavaScript错误；当时未启用图片完整性断言。三个应用服务真实重启后，健康和配置完整列表逐字保留。首次证书同步/重载前命中DSM默认证书、创建未终态时证书分配守卫拒绝的原始失败均保留，未掩盖。

## 当前授权的图片范围

用户已改为：正文放HDD，PG只存元数据；Swift和服务端全图鉴，朱紫优先，缺图用其他游戏小图标。每个ID只取一份菜单PNG，不部署所有世代/动画/闪光/大立绘。

成品覆盖全部1,350条记录（含形态），同ID真实菜单图：朱紫869、Champions140、Z-A88、阿尔宙斯39、BDSP60、剑盾132、第七世代22。另5道具+19属性，共1,374张20,079,618字节。Swift资源与服务端包逐字相同，来源/原尺寸/SHA完整记录在data/assets/scarlet-violet/manifest.json。

prepare-sprite-snapshot.sh只发布这份32MiB预算内的小包到HDD版本目录；目录名取拥有成品包的项目Git SHA，上游c0542f7身份单独记录。API只读挂载HDD，正文不进入PG。前端知识路径仅挂载SQLite、manifest和许可三文件，不额外挂载Swift图标。

28.7GB全量源只留在Download/历史Backup，不进入运行服务；其独立旧导入在20分钟截止时失败并回滚，约15GB失败PGDATA已正常停机、核对控制文件后清理，原失败保留。该全量正文导入已撤出当前交付范围，不继续重跑。

## 新版本发布与回退准入

新镜像经build-nas-images.sh和唯一nas-shared构建器，使用固定OCI工具链上下文；源码必须干净并记录真实image ID。完整隔离栈应逐文件SHA核验1,374份HDD正文、确认PG content全部NULL、三类图片真实解码、配置/任务/取消、四角色和PG重启、元数据备份及独立恢复。

历史BYTEA-only镜像不认识HDD正文。演练须证明即使它健康也会因图片正文错误被拒绝，然后回退到已验证的HDD版本并核对图片和用户数据；不能宣称旧镜像可服务外部图片。生产只定向更新本应用，不重建共享PG或其他home服务。

不自动删除原库、凭据、快照、旧镜像或原始证据。数据库恢复只进入独立目标，不对生产执行--clean或DROP；已接收新写入时先冻结并保全差异。旧凭据回退只能在新应用停止后使用，不能打印其私有SQL。
