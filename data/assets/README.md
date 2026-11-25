# 全图鉴小图标包

服务端和Swift使用同一清单，覆盖固定CSV内全部1,350条记录（含形态），每个ID一张真实游戏菜单PNG。首选朱紫869条，其余由Champions140、Legends Z-A88、Legends Arceus39、BDSP60、剑盾132、第七世代22补齐，ID逐项一致，没有物种替代或缺图。

另有当前计算器支持的5项道具标准图、19种朱紫属性徽标。共1,374张、20,079,618字节，约19.2MiB；不包含动画、背面、闪光或大立绘。`scarlet-violet-selection.json`明确全量ID和补图优先级，`scarlet-violet/manifest.json`记录每张的真实来源、服务端路径、Swift资源名、SHA和尺寸。

宝可梦服务端路径统一为pokemon/<id>.png，保留原API的默认槽位和跨规则集读取；真实朱紫/其他游戏来源仍在source_path中保留。Vue原有背面缺图时回退正面图的行为不变，不用正面图伪造背面资源。类型接口优先朱紫徽标并兼容历史剑盾资源。

Swift资源位于PokemonAppSupport/Resources/Icons，与这里逐字节相同；Git按内容寻址，不因两条路径存储两份相同blob。正常构建和部署只需要这份小包，不需要28.7GB全量下载源。

重新构建使用tools/data/build_icon_pack.py和声明的compose.icon-validation.yaml，只读取明确目录/编号。先生成到新的构建目录，完成来源/预算/覆盖验证后再更新受控资源；已有输出拒绝覆盖。HDD发布使用prepare-sprite-snapshot.sh，版本取包含本包的项目Git提交，上游PokeAPI版本在manifest中独立记录。
