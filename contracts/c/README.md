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

C++ 的协议、参数、溢出、分配及未知异常全部在 ABI 内捕获；不通过全局/线程 last-error 传错。异常消息是固定 ASCII 或 Core 的稳定 ASCII 文本，不回显请求。SIGSEGV/abort 等进程级故障不能由 C++ catch 或 CGO 隔离；P3 的复杂推演必须由独立 Worker 进程承担，当前同步 Go 首批计算服务不是这一隔离方案的替代。

## 批次与版本

请求只有 `schema_version: 1` 和非空 `operations`，操作按数组顺序返回。任一成员错误、超限或取消，整批只返回 error，不提供部分 results。没有数据库/用户数据写入，也没有任务 ID、进度或持久化副作用。

成功/原生错误正文包括 `schema_version`、`engine_version`、`rules_version`。当前引擎为 `0.5.0`，规则集合标识为 `calculation-rules.v5`；原计算数学语义保持，新增完整性格 profile、合法行动和显式概率拓扑/SCC 求解。C ABI/schema 仍为 v1。不表示完整宝可梦规则已迁移。发布后的语义变更必须更新引擎/规则版本，不能让同一版本悄悄产生不同结果。

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

未知字段、缺失字段、bool/float 冒充整数、越界整数均拒绝。未知 kind、schema version 或性格倍率明确返回 UNSUPPORTED。KO 的重复槽位保留等概率权重，不处理回血/残余伤害；完整领域边界和极端整数行为差异见 `core/README.md`。

概率分子、分母使用任意精度整数与精确有理数，不经过 double；零规范为 `0/1`。HTTP 小数展示或 Swift UI 展示转换不能反过来作为计算输入的精确概率来源。

### 直接伤害输入与版本边界

共享八操作向量中的 damage 项是完整最小请求。`attacker`/`defender` 必填 `level`、`types`（PokeAPI 1…18）和 `stats`（hp/attack/defense/special_attack/special_defense/speed）；可选 `ability`、`item`、`can_evolve`、`grounding`。未填效果表示明确无效果；显式名称必须是以下支持项，未知名称不回退：

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

Core 在解析前、操作解码/执行之间及结果提交前检查取消。图拓扑解码、SCC 和精确消元直接检查同一令牌的 `std::stop_token`；不创建额外轮询线程。JSON 解析和单个有界 KO/直接伤害计算不会被强制中断；取消属于协作式，不能承诺瞬时抢占。取消与最后提交检查竞争时，已完成的调用允许返回 OK。独立输入/输出可并发调用，无共享可变计算状态。

Go 在每次调用内拥有令牌、C 输入副本和结果。监视 context 的 goroutine 完全退出后才 destroy，避免 use-after-free。Swift 用强引用和 withExtendedLifetime 保持令牌，calculateAsync 在 detached task 执行并传播 Task 取消，计算不占 MainActor。

## 实际验证与入口

- Linux C/C++：18 项 CTest，含直接伤害、真正的 C 编译器调用、完整共享向量、非法输入/预算、循环释放、32 并发及实际运行中取消。ASan/UBSan/leak 检查同样 18/18 通过。
- Go：3 项桥接测试加 1 项回环 HTTP 测试，`-race` 与 `go vet` 通过。外部静态库不参与 Go 缓存跟踪，所以测试/交付构建使用 `-a`。
- Swift 6 Linux：4 项 XCTest，通过实际 Core 静态库；完整结果/版本、错误/释放、32 并发、Task 运行中取消均已执行。Swift scratch 以两个原生 archive 的 SHA-256 区分，避免增量缓存链接旧库。
- 独立 NAS curl 到实际 Go 服务容器：200 完整共享向量匹配，未知操作 422 且无部分结果；临时服务和随机回环端口已清理。

本地统一入口：`make test` 或 `make test-native`。仅缺少未显式配置的 Go/Swift 工具时，pytest 会说明能力缺失并 SKIP；显式工具/库配置错误必须 FAIL。NAS 的 `validate-nas.sh bindings` 委托两个声明的 maintenance 工具环境，弥补 Python 镜像未含 Swift 的能力；不是把其跳过结果算成通过。

macOS/iOS 已由用户授权的 [GitHub Ready-PR CI 45349703813](https://github.com/mental1104/PokemonBattleInference/actions/runs/45349703813) 实际验证：macOS CTest 18/18、差分和双语言委托 9/9 无跳过；arm64 iPhoneOS/Simulator archive、Swift 模块和 C ABI XCFramework 均构建成功。下载的 ZIP 校验值、两个平台的实际 Mach-O 对象与共享头已独立核验，证据见 `docs/migration-progress.md`。Apple SDK 编译不需要登录或签名，不安装 App、不执行签名、不代表模拟器运行或 iPhone/iPad 真机验收。
