#pragma once

#include "graph_contract.hpp"
#include "pbi/turn.hpp"

namespace pbi::contract {
/// 显式双方行动与策略选择互斥，边界转换后不靠可空字段判断执行模式。
struct ExplicitTurnActions { BattleAction attacker; BattleAction defender; };
/// 玩家策略是确定的有限域；展开概率由正式 Core 唯一计算。
struct PolicyTurnActions { ActionPolicy attacker; ActionPolicy defender; };
/// 完整单步回合的拥有请求，包含同一静态知识快照及调用者可选的执行保护。
struct TurnRequest {
  BattleState state;
  TypeChartSnapshot knowledge;
  std::variant<ExplicitTurnActions, PolicyTurnActions> selection;
  TurnLimits limits;
};
/// 原探索完整图与原任务summary是不同用途；默认不变，不能把stop-all-frontier塞进探索。
enum class FixedGraphPurpose { exploration, configuration_summary };
/// 真正配置构图及求解请求，不接受用户自定义脚本 expander。
struct FixedBattleRequest {
  BattleState initial;
  TypeChartSnapshot knowledge;
  FixedBattleOptions options;
  bool include_graph;
  bool include_representative_paths = false;
  bool include_root_action_explanation = false;
  FixedGraphPurpose graph_purpose = FixedGraphPurpose::exploration;
};
/// @param value 正式单步请求；@param remaining_rolls 批次策略槽位余量；@return 全部已验证拥有输入。
[[nodiscard]] TurnRequest ReadTurnRequest(const Json& value, std::size_t remaining_rolls);
/// @param value 正式固定战斗请求；@param remaining_rolls 策略槽位余量；@param available_nodes 批次节点余量。
/// @param available_edges 批次边余量；@return 完全有界请求，缺省保护不修改 state 中的规则值。
[[nodiscard]] FixedBattleRequest ReadFixedBattleRequest(const Json& value, std::size_t remaining_rolls,
    std::size_t available_nodes, std::size_t available_edges);
/// @param request 只读完整单步输入；@param stop 同一个 ABI 取消令牌。
/// @return 完整后继/精确概率/条件事件路径/阶段/机制覆盖，不返回部分分布。
[[nodiscard]] Json EvaluateTurn(const TurnRequest& request, CancellationToken stop);
/// @param request 完全有界固定输入；@param progress 同步真实构图观察者，可空；@param stop 同一取消令牌。
/// @return 精确摘要及可选完整图；构图保护为 unknown/incomplete，执行或输出超限为正式资源错误。
[[nodiscard]] Json EvaluateFixedBattle(const FixedBattleRequest& request, const GraphProgressObserver& progress, CancellationToken stop);
} // namespace pbi::contract
