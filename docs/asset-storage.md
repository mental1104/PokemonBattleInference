# 图片正文与图标包

用户已确认：图片正文存NAS HDD，PostgreSQL仅存元数据，原图片URL保留；Swift和服务端都要全图鉴，朱紫优先，缺图用其他游戏菜单小图补齐。先前全105,947文件/28.7GB正文导入已退出当前交付范围，旧失败和来源材料保留作历史证据，不进入运行服务。

## 同一份全图鉴资源

固定清单覆盖1,350条Pokemon记录（含形态），与固定pokemon.csv逐ID比较。朱紫869、Champions140、Z-A88、阿尔宙斯39、BDSP60、剑盾132、第七世代22，全部使用相同ID的真实菜单PNG，无默认像素图替代。另有5种当前支持道具和19种朱紫属性徽标。

成品为1,374张、20,079,618字节；服务端data/assets/scarlet-violet与Swift Resources/Icons逐字节相同。PokeAPI上游c0542f7的来源路径、原尺寸和SHA在清单中保留，图片未经改图。原PNG按边界裁剪，尺寸并不统一128×128；实际均不超过256边。

## 数据库与HDD

- HDD快照父目录为`/volume1/docker/pokemon-battle-inference/sprite-snapshots`，每个子目录使用包含成品包的项目Git SHA。prepare-sprite-snapshot.sh只允许32MiB以内的明确PNG清单，逐文件验SHA/数量，已存在的相同版本只核验复用。
- PG复用sprite_assets及sprite_import_batches，保留ID、first_seen、MIME、长度、SHA、分类、版本和失效语义。只有显式文件导入入口将content改为可空；新图片行正文为SQL NULL，原文件不进入PG。批次source_commit标记包的项目Git版本，上游来源另由包清单记录。
- API显式配置只读PBI_SPRITES_ROOT，按批次版本/relative_path定位文件；路径越界、逃逸链接、缺失、长度或SHA错误返回503。不存在的资产404；真实正文验证后才处理原强/弱ETag与304。历史非NULL BYTEA保持读取兼容。
- 文件模式启用后，旧数据库正文导入入口拒绝隐式转换回BYTEA。完整批次失败会回滚DDL、元数据及批次记录，不修改HDD快照，旧资源可继续读取。

## 已验证与剩余项

`Backup/PokemonBattleInference/filesystem-assets-20261125/`保存完整证据。Go/PG初验和类型朱紫优先后的r2均通过：76 PASS、2专用SKIP，恢复重复10/10；路径、取消、损坏、三种原URL、ETag、真实NULL正文、同摘要模式转换、稳定身份及DDL/正文失败回滚均覆盖。原105,947路径元数据/MIME差分历史通过，不冒充本次新运行路径通过。

Python生成/核验工具通过Ruff、strict mypy和13项实测；逐ID覆盖、补图来源、同字节双包、预算/缺失保护均核验。Swift真实SPM复制后逐一核对1,374份PNG及SHA，2/2零失败；界面已接入图鉴、选择器、详情、双方配置与当前道具，新增iPhone/iPad实际图片断言尚待Apple CI。

当前NAS仍是已验证的a3f0ff7运行镜像，HTTPS和业务回归通过。新HDD版本须先完成小包真实运行栈、重启、元数据备份/恢复及拒绝不兼容候选后回退验证，再定向部署。不能回退到不认识NULL/HDD的历史BYTEA-only镜像；图片验收必须作为准入，API健康不能替代它。
