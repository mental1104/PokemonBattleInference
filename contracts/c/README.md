# C ABI v1 与跨语言计算合同

权威 C 声明为 `pbi_core.h`，JSON 的固定成功向量为 `tests/vectors/abi-calculations.v1.{request,response}.json`。Go/Swift 读取同一头文件并链接同一 Core 源码产生的静态库，不维护第二份计算规则。

## 生命周期与错误

`pbi_v1_compute` 同步借用 request 字节；长度必须准确，返回前不得修改。调用者零初始化 `pbi_buffer_v1`，返回 JSON 由 Core 独占分配，必须用 `pbi_v1_buffer_release` 归还；不能用 Go/Swift 的 allocator 释放。release 清零且可重复调用。非空 output 不会被覆盖，避免丢失尚未释放的结果。

JSON 不是 NUL 终止字符串，必须读取完整 size。Go 使用 `C.GoBytes`、Swift 使用 `Data(bytes:count:)` 复制，再释放 C 缓冲区。错误正文同样遵守这个生命周期。内存耗尽或 output 参数错误时允许没有正文，仍返回状态码。

| C 状态码 | JSON error.code | 首批 Go HTTP 映射 |
| --- | --- | --- |
| 0 / OK | 无 error，含 results | 200 |
| 1 / INVALID_INPUT | invalid_input | 400 |
| 2 / UNSUPPORTED | unsupported | 422 |
| 3 / RESOURCE_LIMIT | resource_limit | 413 |
| 4 / CANCELLED | cancelled | 408；Go context deadline 为 504 |
| 5 / INTERNAL_ERROR | internal_error | 500 |

C++ 的协议、参数、溢出、分配及未知异常全部在 ABI 内捕获；不通过全局/线程 last-error 传错。异常消息是固定 ASCII 或 Core 的稳定 ASCII 文本，不回显请求。SIGSEGV/abort 等进程级故障不能由 C++ catch 或 CGO 隔离；Go HTTP 计算入口使用独立 Core worker 子进程，不提供进程内回退。真实 CGO SIGSEGV 的 exit=2 也不能仅凭退出码冒充正常业务拒绝，必须核对完整 ABI 错误正文。

## 批次与版本

请求只有 `schema_version: 1` 和非空 `operations`，操作按数组顺序返回。任一成员错误、超限或取消，整批只返回 error，不提供部分 results。没有数据库/用户数据写入、任务 ID 或持久化副作用。可选同步进度回调仅观察真实构图计数，不能被解释为结果已成功提交。

成功/原生错误正文包括 `schema_version`、`engine_version`、`rules_version`。当前接入版本为 `0.7.0` / `calculation-rules.v7`，新增完整候选枚举、覆盖/strict准入及独立 job-v1 具体 case 规划；回合和固定战斗仍由真实结构化管线驱动，不接受测试脚本 expander。C ABI/schema 仍为 v1。不表示完整官方宝可梦规则已迁移。发布后的语义变更必须更新引擎/规则版本，不能让同一版本悄悄产生不同结果。

| kind | 完整输入字段（均不含 kind 自身） | 结果 |
| --- | --- | --- |
| hp | base、iv、ev、level，均 int32 | value：int64 |
| stat | 上述字段及 nature_tenths：9/10/11 | value：int64 |
| profile | base/ivs/evs 完整六项整数、level、decreased_stat_id/increased_stat_id：2…6 | stats：完整六项 int32，性格轴由 Core 处理 |
| stage | value：int64，stage：int32 且 -6…6 | value：int64，至少 1；原 value 必须正数 |
| ko | defender_hp：正 int32，rolls：非空 int32 数组 | ohko、two_hit：精确分子/分母字符串；guaranteed_ohko、guaranteed_two_hit：布尔值 |
| damage | generation_id、attacker、defender、move、type_chart；可选策略/环境/标志详见下文 | int64 rolls、base_damage、defender_hp、完整 trace、精确 KO 和 damage_ruleset_id |
| battle_state | state、updates；可选 compare_to/damage_query | 完整新状态、键等价、原行动速度及可选真实伤害，详见 [状态合同](state.v1.md) |
| status_modifiers | status、speed、generation_id、category、base_multiplier、burn_multiplier；可选 paralysis_multiplier | 独立麻痹速度、精确灼伤修正与切换清理，详见 [状态合同](state.v1.md) |
| legal_actions | state、side、policy | 合法行动、完整 slot_id 与精确选招分布，详见 [图与行动合同](graph.v1.md) |
| graph | nodes、edges、root、observer、truncations；可选 max_equation_nodes | 全部 SCC 与精确胜负/平局/闭环概率及有限/无限/不可用期望，详见 [图与行动合同](graph.v1.md) |
| battle_turn | state、type_chart、selection；可选 turn_limits | 正式十一阶段、完整后继/状态/概率/条件事件路径，详见 [回合与固定战斗](turn.v1.md) |
| fixed_battle | state、type_chart、attacker_policy、defender_policy、observer；可选保护/完整图开关 | 真实构图/精确解/实际统计/保护未知与可选完整图，详见 [回合与固定战斗](turn.v1.md) |
| configuration_stats | input：完整base/level、preset或受控枚举与原raw预算 | 全部实际能力类、第一IV/EV/五轴性格代表和精确原始成员，详见 [配置合同](configuration.v1.md) |
| configuration_moves | input：全部合法候选、可选ID/槽数命令与原raw预算 | 原无序组合、具体招式ID/完整spec、原始成员和全覆盖，详见 [配置合同](configuration.v1.md) |
| configuration_space | input：双方完整四维命令、权重假设和原pair预算 | 原等价分区、丰富代表、全部coverage、精确配置对权重，详见 [配置合同](configuration.v1.md) |
| configuration_coverage | input：显式三来源描述列表或完整admission事实及composition | 完整factory描述/缺失能力或真实strict裁定，不提前过滤不可选候选 |
| job_move_pool | input：原完整job命令、关联准入快照、offset/limit | 整池strict后原具体case/canonical pair与sideSHA、全局分母和有界页面 |

未知字段、缺失字段、bool/float 冒充整数、越界整数均拒绝。未知 kind、schema version 或性格倍率明确返回 UNSUPPORTED。KO 的重复槽位保留等概率权重，不处理回血/残余伤害；完整领域边界和极端整数行为差异见 `core/README.md`。

概率分子、分母使用任意精度整数与精确有理数，不经过 double；零规范为 `0/1`。HTTP 小数展示或 Swift UI 展示转换不能反过来作为计算输入的精确概率来源。

### 直接伤害输入与版本边界

共享向量中的 damage 项是完整最小请求。`attacker`/`defender` 必填 `level`、`types`（PokeAPI 1…18）和 `stats`（hp/attack/defense/special_attack/special_defense/speed）；可选 `ability`、`item`、`can_evolve`、`grounding`。未填效果表示明确无效果；显式名称必须是以下支持项，未知名称不回退：

- ability：none、technician、adaptability、thick_fat、filter、solid_rock、sniper。
- item：none、life_orb、choice_band、choice_specs、expert_belt、eviolite。
- grounding：null（原最小飞行属性推断）、grounded、airborne。

`move` 必填 `type`、`category`（physical/special）和正 `power`。变化招式返回 UNSUPPORTED。`type_chart` 为 `{attacking, defending, percent}` 数组，每个实际使用的属性配对必须有一条知识；缺失为 UNSUPPORTED，重复/负倍率为 INVALID_INPUT，最多 324 项。Core 不内置第二张属性表。

`generation_id` 必须是 1…9；可选 `version_group_id` 使用原 resolver 的 1…31 映射，必须与 generation 一致。输出 `python-compatible.genN.v1` 指原 Python 已建模的部分 profile，包括会心、沙暴/雪天防御和场地倍率，**不表示完整官方历代机制**。当前注入的知识决定实际属性相克。

可选 `weather` 为 none/harsh_sunlight/rain/sandstorm/hail/snow；`terrain` 为 none/electric_terrain/psychic_terrain/grassy_terrain/misty_terrain；`defender_side` 含三个必填布尔 reflect/light_screen/aurora_veil。可选布尔 critical/spread/protect_reduced/multi_target 默认 false。原合同中会心跳过屏障、屏障和极光幕可以叠加，protect_reduced 仅表示削减钩子，不能代替完整回合守住判定。

可选 `policy` 按 `core/include/pbi/damage.hpp` 的 DamagePolicy 同名字段覆盖代际默认值；所有原策略字段均保留。倍率必须有限且非负，三个天气防御倍率允许 null 禁用；随机倍率数组非空，可重复、无序和包含零，保持槽位权重。multiscale_damage_multiplier 和 burn_physical_attack_multiplier 在原直接链也不消费，仅属于完整策略快照，不能凭它们声称执行满 HP/灼伤状态效果。multiscale/inner_focus 需要动态战斗状态，当前直接入口显式返回 UNSUPPORTED；后续状态/效果迁移接入后再扩大支持。

伤害链依原顺序使用 binary64 倍率并 floor，不把它改成另一套官方 4096 定点机制，也不添加最小 1 伤害钳制。整数除法保留 Python int/int 的 nearest/ties-to-even 舍入，中间整数任意精度。阶段能力与返回伤害的 int64 越界明确返回 RESOURCE_LIMIT；概率始终是精确有理数。trace 保留 key/stage/source/reason 以及可空 multiplier/min_multiplier/max_multiplier，随机首末值沿用原语义，并非无序数组的真实最小/最大值。

v1 资源上限声明在头文件：8 MiB 请求、4,096 操作、单操作 65,536 伤害槽位、批次合计 1,048,576 槽位；解析深度最多 16。超限失败，不截断后重新归一化。这些是当前 ABI 批次预算，不能混同后续状态图的节点/边/回合截断合同。

## 取消与并发

`pbi_v1_cancel_token_create` 创建单向原子令牌，cancel 可与 compute 并发。令牌允许多个计算只读借用，取消影响所有借用者；不能重置。所有调用返回且所有并发 cancel 结束后，创建者才可 destroy。空令牌表示本次不提供取消。

Core 在解析前、操作解码/执行之间及结果提交前检查取消。图拓扑解码、SCC 和精确消元直接检查同一 `CancellationToken` 的共享原子状态；不创建额外轮询线程或依赖平台未实现的 `std::stop_token`。空令牌永不取消，源与令牌副本共同持有状态，源销毁后令牌仍安全有效；取消只能单向请求，不能重置。JSON 解析和单个有界 KO/直接伤害计算不会被强制中断；取消属于协作式，不能承诺瞬时抢占。取消与最后提交检查竞争时，已完成的调用允许返回 OK。独立输入/输出可并发调用，无共享可变计算状态。

Go 在每次调用内拥有令牌、C 输入副本和结果。监视 context 的 goroutine 完全退出后才 destroy，避免 use-after-free。Swift 用强引用和 withExtendedLifetime 保持令牌，calculateAsync 在 detached task 执行并传播 Task 取消，计算不占 MainActor。

## 实际验证与入口

- 已冻结 `.6` 提交 76a40a0：Linux 58/58 CTest 与 ASan/UBSan/leak 均实际通过；Go桥接/独立worker 14项 `-race -count=1` 与 `go vet` 通过。
- 同一 `.6` 固定快照 Swift 6 Linux 20项中17项实际通过、3项显式SKIP（在线2/PG1缺环境）。a74d98e独立HTTP子进程快照的真实在线计算2/2通过，三配置完整在线/离线JSON一致；该轮全套20项另有1个知识更新取消测试失败、1个PG跳过，因此不称整套通过。
- `.7` 正式ABI差分已真实核对64能力案例、12招式池、32完整双侧空间、两工厂描述、全部44100具体case和192 strict组合；共享19操作向量中的新增6项由原Python独立生成，旧13项数学结果保持不变。最终原生/Go/Swift和平台批次结果见迁移进度，不把进行中的检查记成通过。
- 外部静态库不参与Go缓存跟踪，构建使用 `-a`；需要重新执行而非复用测试缓存时使用 `-count=1`。Swift scratch 以两个原生archive的SHA-256区分，避免链接旧库。

本地统一入口：`make test` 或 `make test-native`。仅缺少未显式配置的 Go/Swift 工具时，pytest 会说明能力缺失并 SKIP；显式工具/库配置错误必须 FAIL。NAS 的 `validate-nas.sh bindings` 委托两个声明的 maintenance 工具环境，弥补 Python 镜像未含 Swift 的能力；不是把其跳过结果算成通过。

macOS/iOS 使用用户授权的 Ready-PR CI。早期 [CI 45349703813](https://github.com/mental1104/PokemonBattleInference/actions/runs/45349703813) 的18原生/9差分及双SDK构建是历史基线，不能替代当前版本验证。`.7` 的Apple构建/运行状态以 `docs/migration-progress.md` 的确切提交和终态为准。SDK编译不需要登录或签名，不表示已经完成iPhone/iPad真机验收。
