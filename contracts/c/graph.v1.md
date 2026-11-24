# C ABI v1：合法行动与显式概率图

引擎 `0.5.0` / `calculation-rules.v5`，继续使用 `pbi_v1_compute` 和原 v1 版本信封、所有权、整批原子失败及取消合同。固定成功样本在 `tests/vectors/abi-calculations.v1.*.json`，包含旧九操作及新增两操作。

## 合法行动

`kind: "legal_actions"` 必填 `state`、`side`、`policy`。`state` 与 [状态合同](state.v1.md) 完全相同；`side` 为 attacker/defender；`policy` 为 uniform-random/first-legal-action。生成只读合法行动，不消耗 PP、不执行招式。

结果 `actions` 包含完整合法集合，`selections` 为 `{action, probability}` 数组。概率使用规范分数字符串，仅代表策略选招，不包含命中、伤害等回合随机概率。

- use-move：kind/side/move_id/priority/slot_id；运行时 slot_id 独立于招式 ID。
- struggle：kind/side；没有可用普通招式或讲究锁招无可用槽时的正式行动。
- pass：kind/side；濒死方内部占位。

槽位顺序、禁用、剩余 PP 和讲究锁招由 Core 处理；选择策略不能改变合法集合或绕过锁招。

## 图输入

`kind: "graph"` 必填 nodes/edges/root/observer/truncations，可选正整数 max_equation_nodes。图必须由调用方提供完整数学拓扑；本入口没有从宝可梦配置自动生成回合图的功能。

| 字段 | 合同 |
| --- | --- |
| nodes | 非空 `{outcome, cycle_resolution}` 数组，索引即节点 ID |
| outcome | attacker-win、defender-win、draw、non-terminal、unknown |
| cycle_resolution | declare-draw、solve-absorption-probability |
| edges | `{source, target, probability}` 数组；端点为非负有效索引；正概率，非终局出边精确和为一 |
| root | 有效节点索引 |
| observer | attacker 或 defender，决定 win/loss 视角 |
| truncations | max-turns/max-nodes/max-edges 数组，空数组允许；unknown 仍使图不完整 |
| max_equation_nodes | 默认为 128，只允许 1…128；省略使用 ABI 预算，null 不是取消预算 |

分数字符串沿用原合同：任意精度、每分子/分母最多 1024 位，负分母规范化，零分母拒绝。零概率、未知拓扑字段、非法索引或出边不守恒明确失败，不默默重新归一化。

ABI 每批总共至多 65,536 节点、262,144 边，另受 8 MiB 请求和 4,096 操作限制；预算跨多个 graph 累计。方程预算只限制精确消元的瞬态节点，DAG 递推不受此限。任何显式/实际超限返回 RESOURCE_LIMIT，整批不返回部分 results；此传输边界不改变纯 Core 可显式配置的领域上限。

## 完整结果与未完成

`components` 给出所有 SCC 的 id、nodes、kind、outgoing、reaches_terminal。kind 为 acyclic、closed-cycle、terminal-reachable-cycle 或 open-unresolved-cycle，编号和成员顺序由同一 Core 保证。

成功 `status: "solved"` 包含精确 win/loss/draw/closed_cycle，`expected_turns` 是 `{status: "finite", value: fraction}` 或 `{status: "infinite", value: null}`。正概率进入封闭循环的无限期望不被转换为大整数或零。

不完整图为 `status: "incomplete-graph"`，概率全部 null，期望 `{status: "unavailable", value: null}`，并有 diagnostics。截断不能变成平局或零胜率。原生奇异系统同样明确 `singular-system`，不伪造概率。取消为整批 CANCELLED，不返回部分 SCC/概率；同一 C 令牌直接驱动图解析、SCC 和消元。

合法行动和显式图求解是可调用切片。完整动态效果、回合解析、配置搜索和由配置生成固定战斗图仍需后续迁移，不由本接口或绿色测试代替。
