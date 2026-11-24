# 状态快照与独立状态修正（C ABI v1）

本合同从引擎 `0.3.0` / 规则集合 `calculation-rules.v3` 开始提供，使用同一 `pbi_v1_compute`、所有权、错误码和整批原子语义。完整冻结输入/输出见 `tests/vectors/abi-calculations.v1.{request,response}.json` 的 `status_modifiers` 和 `battle_state`；这些向量由 Python 参考模型产生，Go/Swift 链接同一 C++ 库实际执行，不实现第二份规则。

这是不可变节点和独立修正的计算合同。完整回合、效果分发、状态图、任务、持久化与同步仍需后续迁移。

## 完整状态与键

`battle_state` 必填 `state`、`updates`；可选 `compare_to`、`damage_query` 均允许 null。状态不写入服务端全局存储。

| 对象 | 必填字段 | 可选字段/默认值 |
| --- | --- | --- |
| state | attacker、defender、rules | turn_number=1、field=空场地、phase=action-selection |
| 一方节点 | spec、current_hp、move_slots | stages=七个 0、status=空、last_move_id=null、choice_lock_move_id=null、item_consumed=false、is_first_turn=true |
| spec | pokemon_id、name、pokemon、moves | 无 |
| pokemon | 复用直接伤害的 level/types/stats 与效果字段 | ability/item=none、can_evolve=false、grounding=null |
| moves 每项 | move_id、name、move、max_pp | priority=0、accuracy=100、effect_identifier=null |
| move | type、category、power | 无，变化招式可保存 0/负威力，但不能执行直接伤害 |
| move_slots 每项 | move_id、current_pp、max_pp | disabled=false、locked=false、slot_id=0（构造后规范为 move_id） |
| field | weather、terrain、attacker_side、defender_side | 显式提供时字段必须齐全 |

`pokemon_id`、`move_id`、`slot_id`、上一招/锁招 ID、绝对回合号为 int64。等级、能力、HP、PP、优先级与招式数值为 int32。等级 1…100，能力全正，当前 HP 在 0…最大 HP，属性为 1…2 个不重复值，配置为 1…4 个不重复招式。动态槽必须与配置招式集合/最大 PP 完全对应；保留输入槽位顺序和 slot_id，不擅自排序或重新编号。

`stages` 为按攻击、防御、特攻、特防、速度、命中、闪避顺序的七项整数，每项 -6…6。`phase` 为 action-selection/action-resolution/end-of-turn/terminal。

`rules` 可提供空对象使用原默认规则，也可显式设置 ruleset_id、version_group_id、level、battle_format、switching_policy、allow_terastallization、allow_mega_evolution、allow_dynamax、max_turns、repetition_resolution、cycle_resolution、damage_policy、move_execution_policy。输出始终展开全部字段。

- 规则 ID 必须是非空且首尾无空白的字符串；version_group_id 必须正，不在状态构造时推定伤害代际。
- battle_format 仅 one-on-one-singles，switching_policy 仅 disabled，三种形态变换必须 false。未知/启用不支持机制明确失败。
- max_turns 为 null 或正 int64；它是执行保护，`next_turn` 更新不会把上限当作循环证明。该上限作为原推演规则的一部分进入 StateKey。
- repetition_resolution 为 declare-draw/continue；cycle_resolution 为 declare-draw/solve-absorption-probability。
- damage_policy 复用完整直接伤害策略和默认值。
- move_execution_policy 默认 accuracy_denominator=100、consume_pp_on_miss=true、consume_pp_when_action_blocked=false、consume_pp_when_before_move_stops=false、struggle_power=50、struggle_recoil_fraction=1/4。前四项当前固定，挣扎威力必须正，反伤精确比例在 (0,1]。

名称保留 UTF-8/中文展示信息，宝可梦名不允许首尾 Python 空白集合中的字符。招式 effect_identifier 使用已有 ASCII strip/lower/连字符与空格转下划线规则；非 ASCII 机制标识明确返回 UNSUPPORTED。这是当前边界相对旧字符串规范化的已知限制；中文展示名称与迷恋来源可正常使用。保存标识不表示对应 effect 已迁移，实际执行仍需显式支持。

`StateKey` 保留原所有未来相关字段，排除宝可梦/招式展示名和绝对回合号。属性、配置招式、动态槽顺序保留；临时状态是按种类规范化的集合。C++ 内部使用有长度前缀的完整语义编码作键，相等性比较全部编码，哈希碰撞不会合并节点；编码和标准库哈希均不作为网络/同步 ID。浮点 +0/-0 生成同一键，精确分数使用规范分子/正分母。

## 状态集合

`status` 为 `{major, volatile}`，两字段显式提供时必须齐全。major 可为 null，或以下对象：

- sleep：kind 与可选 turns_asleep=0，计数非负。
- bad_poison：kind 与可选 toxic_counter=1，计数必须正。
- paralysis/burn/freeze/poison：只有 kind。

volatile 数组支持 confusion（turns_remaining=null 或非负 int64）、infatuation（source_id=null 或字符串）、flinch（只有 kind）。完全相同的项去重；同种类不同计数/来源明确 INVALID_INPUT。null/0 计数、null/空字符串来源分别保留区别。输出固定为混乱、迷恋、畏缩顺序。

## 更新与结果

每项更新有固定 kind；包含未知字段时拒绝。需要 side 的操作使用稳定 attacker/defender，不随当前攻击方向变化。

| kind | 其他必填字段 | 结果语义 |
| --- | --- | --- |
| hp | side、value | 更新当前 HP |
| pp | side、move_id、value | 更新对应剩余 PP |
| disabled | side、move_id、value | 更新禁用布尔值 |
| choice_lock | side、move_id（可 null） | 同步更新唯一锁招及所有槽位标记 |
| last_move | side、move_id（可 null） | 上一招允许未配置的正 ID |
| stages | side、value | 替换完整七等级 |
| status | side、value | 替换完整状态集合 |
| item_consumed | side、value | 设置道具消耗；不会自动修复锁招 |
| first_turn_complete | side | 清除首次回合标记 |
| slot | side、value | 替换一个完整动态槽 |
| next_turn | 无 | 回合加一、阶段回到行动选择 |
| phase/field/rules | value | 替换对应完整值 |

讲究锁招需要有效讲究头带/眼镜，ID 属于配置且恰好对应一个 locked 槽；道具已消耗时不能保留锁招。锁招耗尽 PP 可以保存，后续合法行动层据此处理挣扎。每一步重新验证，原节点与祖先不变；任一步错误导致整批没有部分 results。

返回完整 `state`、`same_key_as_input`、`same_key_as_reference`（无 reference 为 null）、`attacker_speed`、`defender_speed` 和可空 `damage`。两个速度字段保留原行动排序的能力等级后速度，尚未在该路径叠加独立麻痹 helper。

`damage_query` 必填 side、move_id、generation_id、type_chart，可选 policy。它在更新后的状态中检查 PP/禁用/锁招，按方向交换双方与屏障，禁用已消耗道具，再调用同一直接伤害 Core。策略由显式 generation_id 与覆盖值选择；不提前叠加等级/实时状态效果。查询失败同样使整批失败，不返回已经更新的状态。

## 独立状态修正与预算

`status_modifiers` 必填 status、speed（非负 int64）、generation_id（1…9）、category、base_multiplier、burn_multiplier，可选 paralysis_multiplier 覆盖。分数均为 `{numerator: "十进制整数", denominator: "非零十进制整数"}`；允许负分母并规范化，禁止浮点/布尔冒充整数。

麻痹默认倍率为 1…6 代 1/4、7…9 代 1/2；允许显式非负精确覆盖，返回速度向下取整并允许 0。灼伤只影响物理分类，burn_multiplier 必须非负；base_multiplier 保留精确代数值。输出含规范 status、speed、精确 burn_multiplier/adjusted_multiplier，以及原 `after_switch_out` 清理结果：清除混乱/迷恋，保留主状态与畏缩。

除全局 8MiB/4096 操作/深度 16 上限外，每条状态请求最多 256 更新，每个原始 volatile 数组最多 16 项，每个分数分子/分母最多 1024 十进制数字。状态、reference、规则更新及伤害查询所拥有的随机策略槽位共同计入原 1,048,576 批次预算，单策略不超过 65,536。超限为 RESOURCE_LIMIT，不截断或重新归一化。单项状态计算仍为有界协作式取消，完整计算前后检查，不承诺瞬时抢占。
