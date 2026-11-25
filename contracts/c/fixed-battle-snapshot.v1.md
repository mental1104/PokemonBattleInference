# 固定配置单步快照合同

`fixed_battle_snapshot` 使用与 `battle_turn` 相同的状态、属性表、玩家策略和回合执行保护，从初始状态重放用户选过的局部边，再完整展开当前节点的一层。它不生成全局状态图或求解胜率，也不使用全图节点、边、回合预算截断当前快照。

输入包含 `kind`、完整 `state`、完整 `type_chart`、`attacker_policy`、`defender_policy`、`cursor`，可选 `turn_limits`。状态和知识字段沿用 [C ABI v1](README.md) 的正式回合合同。策略使用 `uniform-random` 或 `first-legal-action`。

`cursor` 为 `{"steps": [...]}`。每步包含 `source_node_id`、`edge_id`、`target_node_id`，采用无损十进制字符串。身份非负且允许超过 uint64；根节点为 0，步骤必须连续。每步 `edge_id` 是该步正式展开结果的局部序号，目标身份由 Core 按原快照规则产生，调用者应提交上次返回的原身份。完整图缓存的边编号不能作为快照局部边编号使用。

成功结果为 `{"kind":"fixed_battle_snapshot","value":...}`；`value` 与原 `BattleGraphExplorationResponse` 同形，包含完整当前节点、全部已展开分组、全部后继事实、游标、累计概率及逐步战报。固定 `graph_id` 为 `fixed-one-on-one-snapshot`，`calculation_revision` 为原公开的 `battle-inference.summary-exploration.v2`。该标识表示可重放快照，不是有 TTL 的完整图存储句柄。

节点和边身份、业务事件任意精度数值沿用图投影的十进制字符串编码。HTTP 适配器按显式 DTO 无损输出原 JSON 整数；分子、分母仍保持字符串。所有组身份、条件概率、累计概率和伤害档位归并均由 Core 产生。每个战报步骤保留该正式边的全部替代事件历史，各步骤之间不展开事件笛卡尔积。

可重放路径的业务拒绝编码为同 kind 的 `error`，包含 `http_status:422`、`code`、`message`。路径不连续使用原 `fixed_battle_invalid_request`；局部边不可用或目标不匹配使用原 `fixed_battle_not_completely_solved`。该完整业务结果不会包含部分节点或战报。协议错误、执行资源超限和取消仍使用 ABI 全批错误；取消不返回已经重放完的前缀。

[共享原实现样本](../../tests/vectors/fixed-battle-snapshot.v1.json) 保存单后继濒死场景、六层任意精度身份和局部边拒绝。全部期望来自原快照和原 HTTP presenter，事件没有裁剪。`test_core_fixed_battle_snapshot.py` 对照完整原回放与正式 codec，`test_go_fixed_snapshot.py` 在显式真实 PostgreSQL/Go HTTP 环境中对照原公开路由；缺集成环境时单列 SKIP。

`configuration_space` 的单侧输入另可选择 `factory`（默认 `standard`）和 `repository_mode`（默认 `raw`）。原普通推演使用 `transparent_inference` / `factory_reconciled`，由 Core 先按原 repository 装饰器对账，再执行原 provider 筛选。此流程与持久任务的严格机制准入分开：透明特性产品的缺失能力保留在覆盖事实中，工厂 PARTIAL 产品仍按原 provider 排除。Go 不据机制名称提升支持或拼接工厂理由。
