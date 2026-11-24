# 配置枚举与覆盖合同（.7 接入中）

本文件记录尚在接入验证的 `0.7.0` / `calculation-rules.v7` 边界。C ABI 和 JSON schema 继续为 v1；未完成真实回归前，不作为已交付能力声明。

五种操作均为 `{ "kind": "configuration_stats|configuration_moves|configuration_space|configuration_coverage|job_move_pool", "input": { ... } }`，放入原有批次 `operations`。未知字段拒绝，不接受字符串整数、布尔数值或缺省隐式候选。所有计算/过滤/组合/归并/覆盖判断由 typed Core 完成；Go/Swift 只组装快照和传输结果。

## 公共值

能力使用六字段整数对象：`hp, attack, defense, special_attack, special_defense, speed`。`StatProfile` 必须为 `{ivs: Stats, evs: Stats, nature: [atk,def,spa,spd,spe]}`；性格为五个有限 binary64 数值，保留旧单增无降快照，不转换成平衡性格枚举。

招式 `MoveSpec` 与 `state.v1` 相同：`move_id, name, move:{type,category,power}, max_pp` 必填；`priority` 默认 0、`accuracy` 默认 100（显式 null 保留必中语义）、`effect_identifier` 默认 null。category 为 `physical|special|status`，type 为原 1..18 属性 ID。

任意精度成员数使用十进制字符串，权重为 `{numerator:string,denominator:string}`。不会经过 double。仅性格倍率使用 binary64，与原实现相同。

## configuration_stats

input 必填 `base: Stats, level: integer, enumeration: Enumeration`；可选 `max_raw_profiles` 默认 4096。

- 预设：`enumeration={mode:"preset",presets:[{profile:StatProfile,label:string},...]}`。
- 受控：`enumeration={mode:"controlled",fields:["hp"|"attack"|"defense"|"special_attack"|"special_defense"|"speed",...],ev_values:[integer,...],natures:[[number,number,number,number,number],...]}`。

输出 `{kind,classes:[{representative:StatProfile,actual:Stats,label,member_count:string}],raw_profile_count:string}`。类按原首次出现顺序，保留第一代表及全部有效原始成员数。EV 值的排序、非法总 EV 组合跳过、能力归并均由 Core 完成。

## configuration_moves

input 必填 `candidates` 数组；可选 `requested_ids` 默认空（不按命令额外过滤）、`slot_counts` 默认空、`max_raw_combinations` 默认 10000。

每个候选必须含 `move_id,identifier,move:MoveSpec|null,effect_identifier:string|null,support:"supported"|"partial"|"unsupported",reason:string`。repository 基础事实与 factory 事实分开保留，外层不得先滤掉 unsupported 候选。可执行 supported 候选必须携带 ID 匹配的 MoveSpec。

空 slot_counts 沿原规范：候选不足四招只取全部，至少四招只取恰好四招的无序组合。显式 slot_counts 可选择 1..4 的不同槽数量；Core 校验唯一值。Go 不生成组合，也不按展示名重排。

输出 `{kind,classes:[{moves:[{spec:MoveSpec,effect_identifier:string|null,key:string}],member_count:string}],coverage:[Coverage,...],candidate_descriptions:[Description,...],raw_combination_count:string}`。

`Coverage={identifier,support,included,reason,factory_status:"supported"|"partial"|"unsupported"|"no_effect"|null}`，命令排除不冒充不支持。

`Description` 保留 source、原 identifier、move_id、`repository:{support,reason}`、`factory:EffectDescription`。EffectDescription 包含规范 identifier、status、reason、missing_capabilities 全量数组。

## configuration_space

input 必填 `attacker:Side,defender:Side`；可选 `weight_assumption` 默认 `uniform_raw_configuration`（另一个值 `uniform_equivalence_class`）、`max_raw_pairs` 默认 1000000。

Side 必填 `pokemon_id,name,types:[integer,...],moves:configuration_moves的input,stats:configuration_stats的input,abilities:[{identifier,support,reason},...]`。可选 `ruleset_id` 默认 `pokemon-champion`、`version_group_id` 默认 25、`can_evolve` 默认 false、`requested_abilities` 默认空、`items` 默认 `[null,"choice-band"]`、`max_raw_configurations` 默认 100000。

输出 `{kind,attacker:SideResult,defender:SideResult,pairs:[{attacker_class:integer,defender_class:integer,member_count:string,weight:Fraction},...],raw_pair_count:string,weight_assumption}`。

SideResult 为 `{pokemon:{ruleset_id,version_group_id,pokemon_id,name,types,level,can_evolve},classes:[{key,member_count,moves:MoveClass,stats:StatClass,ability,item},...],coverage:[{dimension:"move"|"ability"|"item",...Coverage}],candidate_descriptions:[Description,...],raw_configuration_count:string}`。classes 保持原 repr 行为键排序，pair 下标引用这些拥有的类。ability Description 保留 repository 原因与 factory 全字段；item Description 提供完整 factory 描述。

这是通用四维等价空间，**不表示旧 job-v1 具体 case 顺序或 canonical 身份**。不同 move_id 不因相同伤害归并；相同原始行为 projection 的乘数保留为 member_count。旧 job-v1 池的严格唯一 ID、全部候选准入、case identity 由独立纯 Core 入口接线，不从本结果的代表捏造身份。

## configuration_coverage

只读取工厂描述/准入，不执行枚举，不因候选不可选择而隐藏其他候选。

describe 模式：input 必填 `moves:[string|null,...],abilities:[string|null,...],items:[string|null,...]`；可选 `mode:"describe"`、`factory:"standard"|"transparent_inference"` 默认 standard。输出 `{kind,mode:"describe",effects:[{source:"move"|"ability"|"item",factory,identifier,status,reason,missing_capabilities},...]}`，保持三类列表及列表内部输入顺序。

admission 模式：input 必填 `mode:"admission",candidates:[{source,effect_identifier:string|null,mechanism_identifier:string,repository_reason:string,base_executable:boolean,allow_no_effect:boolean},...]`；可选 factory 默认 transparent_inference，repository_mode 为 raw（默认）或 factory_reconciled。输出 `{kind,mode:"admission",candidates:[{source,mechanism_identifier,factory,repository_mode,coverage:EffectDescription,status:"supported"|"no_effect"|"partial"|"unsupported",reason,selectable:boolean,missing_mechanism_identifiers:[string,...]},...]}`。

admission 的 repository status 不是最后准入结论。Core 根据真实基础可执行性、工厂覆盖和缺失子能力决定 selectable；transparent pressure/pickpocket 的占位缺口不能被 overall supported 隐藏。请求不得由 Go 预裁 strict 状态代替这些事实。

实际旧 HTTP composition 使用 transparent_inference + factory_reconciled。请求提供原 raw repository_reason；工厂成功 reconciliation 时 Core 先追加原 `Factory reconciliation` 说明，再执行原 strict 的 `Current factory coverage` 说明。Go 不拼接第二份规则或原因文本；raw 模式仍保留直接旧 _admission 的语义。

## job_move_pool

独立于通用等价空间的原 job-v1 具体 case 规划。input 必填 `command,admission,offset,limit`。offset/limit 是非负整数，空页允许；offset 超过完整 case_count 拒绝，等于总数返回空页。页长度不充当原始任务预算。

command 必须包含原合同的全部字段：`contract_version:"one-on-one-move-pool.v1",ruleset_id,version_group_id,calculation_revision,attacker,defender,dimensions,attacker_policy,defender_policy,weight_assumption:"uniform_configuration_pair",mechanism_admission:"supported_only"`。两侧为 `{fixed:{pokemon_id,form_id:integer|null,level,stat_profile_id,ability_identifier,item_identifier:string|null},candidate_move_ids:[integer,...]}`。dimensions 必须明确八轴：pokemon/form/level/stats/ability/item 为 fixed，moves 为 candidate_pool，special_mechanics 为 disabled。策略为 uniform-random 或 first-legal-action。

当前严格准入工厂只支持 pokemon-champion；其他 ruleset_id 明确 UNSUPPORTED，不借该工厂给另一个规则集裁定可执行性。纯 canonical 规划领域类型本身可表示其他轴，不表示该 ABI 已支持对应工厂。

admission 为 `{ruleset_id,version_group_id,calculation_revision,candidates:[Fact,...]}`，三个主轴必须和 command 完全相同。每个 Fact 必填 `side:"attacker"|"defender",source,move_id:integer|null,move:MoveSpec|null,effect_identifier:string|null,mechanism_identifier,repository_reason,base_executable:boolean,allow_no_effect:boolean`。

事实必须恰好覆盖两侧全部候选 move_id，以及各一条固定 ability 和 item，不允许缺项、重复、其他侧/ID、给非招式来源伪装 move。招式必须有匹配的完整 MoveSpec，效果必须与已有 spec 一致；只有无效果的伤害招式可允许 no_effect。ability 不允许此路径；item 仅在固定道具确实为 null 时允许。固定 ability/item 的规范效果及机制身份必须与命令一致。ABI 检查关联完整性，事实的数据库真实性由外层同一次不可变知识快照负责。

本操作固定使用 transparent_inference + factory_reconciled，先对整个池复用同一 Core strict 判断。任一不可选择则整体 UNSUPPORTED；不会过滤候选并返回更小池。HTTP 可在此之前调用 coverage 收齐全部失败事实与原因，再把同一快照交给本操作重复核对。

输出 `{kind:"job_move_pool",case_count,attacker_move_set_count,defender_move_set_count,offset,next_offset,has_more,cases:[{ordinal,configuration_pair_id,attacker_configuration_id,defender_configuration_id,attacker_move_ids,defender_move_ids,configuration_weight:Fraction},...]}`。每侧 1..10 个唯一 ID、双方总数最多 20；少于四招取全部，至少四招按原自然 ID 顺序生成恰好四招的组合，10+10 全局 44100 个 case。所有原可读 canonical pair JSON、两侧 SHA-256 身份和精确 1/全局总数均由纯 Core 生成，不从等价类代表或页面长度推测。

分页逐条调用原 CaseAt 并检查取消/字节预算，避免先缓存整个笛卡尔空间。输出超限明确 RESOURCE_LIMIT，不把已生成页前缀当成成功页面，也不改变全局 case_count。

固定道具允许原受控标识精确字符串 `"none"`：其关联事实必须使用 `effect_identifier:null`、`mechanism_identifier:"none"` 和原允许无效果路径。原 canonical 命令仍保留该字符串，因此其身份与 `item_identifier:null` 不同；ABI 不将两者改写成同一任务，也不扩大为空白或大小写别名。

## 预算、错误与取消

raw 预算均作用于归并前合法原始成员，而不是归并后的类数；保持上述原默认，显式正整数允许调用方提高预算（限平台 size_t/int64 范围）。不引入额外任意固定类数上限。超预算整次 `RESOURCE_LIMIT`，不裁剪后重新归一化权重。空可执行维度是 `INVALID_INPUT`，不会返回假成功的部分空间；先用 coverage 操作收集准入事实。

沿用整个请求 8 MiB、最多 4096 operations、整个结果 32 MiB。结果投影逐条计费并检查同源取消；输出字节预算失败明确 RESOURCE_LIMIT，与数学枚举预算分开。批次先完成全部解码，执行失败、输出超限或取消均只返回完整错误 envelope，不交付前面已计算的部分 results。

无效字段/值为 INVALID_INPUT，未知规则/机制字符集为 UNSUPPORTED，能力 int32 溢出与分配失败为 RESOURCE_LIMIT，真实取消为 CANCELLED。计算复用同一 portable CancellationToken，捕获普通 runtime_error 时仅在令牌真实已请求取消才映射 CANCELLED；其他内部错误不冒充取消。

这五种操作不伪造构图进度。原 compute_with_progress 仍只在真实 fixed_battle 构图时产生已有 building/built 帧。

## 0.8 模板目标与完整 EV 搜索

`configuration_templates` 和 `configuration_spread_search` 均接收 `kind` 与完整 `input` 快照，不读取数据库或在Go/Swift计算能力值。完整请求/结果的权威示例分别为 `tests/vectors/configuration-templates.v1.json`、`configuration-spread-search.v1.json`，其 expected 由原公开 WithSpeed 用例与完整伤害链逐例生成，再追加到三语言共享向量；既有19项输入/数学结果保持不变。

模板操作保留原模板顺序、显式模板去重、原 max_candidates 提前停止及首个失败的完整伤害/速度证据。速度目标使用原严格大于，同速不满足；伤害和速度目标共用原ID空间，支持单类与混合目标，不擅自添加状态或道具速度修正。

EV操作保留原4EV网格、25种性格等价分组、四种攻防目标与可选速度目标、510总量剪枝、候选排序，以及每项EV/IV独立安全区间。独立范围不表示它们的任意笛卡尔组合都安全。无解返回原基线及双类失败证据，不构造胜率或默认可达状态。

两个操作仍遵守整体8MiB输入、32MiB输出、整批原子失败及同源取消。没有为提高通过率新增原接口不存在的默认搜索截断预算。
