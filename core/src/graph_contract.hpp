#pragma once

#include "state_contract.hpp"
#include "pbi/actions.hpp"
#include "pbi/graph.hpp"

namespace pbi::contract {
/// 已拥有拓扑及求解预算的正式边界输入；不以 JSON 作为 Core 内部数据。
struct GraphRequest {
  ProbabilityGraph graph;
  BattleSide observer;
  std::size_t max_equation_nodes;
};
/// 合法行动查询拥有一个不可变节点，策略只选择行动而不执行回合。
struct LegalActionsRequest {
  BattleState state;
  BattleSide side;
  ActionPolicy policy;
};
/// @param value 完整图操作；@param available_nodes 本批余下节点预算。
/// @param available_edges 本批余下边预算；@param stop 协作取消，解析期间也检查。
/// @return 已验证且独占拓扑的请求；字段/数值/资源错误按正式 ABI 错误码抛出。
[[nodiscard]] GraphRequest ReadGraphRequest(const Json& value, std::size_t available_nodes,
    std::size_t available_edges, std::stop_token stop);
/// @param value 合法行动完整请求；@param remaining_rolls 同批余下的状态策略随机槽位预算。
/// @return 独占不可变战斗状态的请求，不执行任何招式或消耗 PP。
[[nodiscard]] LegalActionsRequest ReadLegalActionsRequest(const Json& value, std::size_t remaining_rolls);
/// @param request 已验证只读拓扑；@param stop 由 C 令牌直接传下的协作取消。
/// @return 完整 SCC 和精确解，截断图明确无概率，资源超限/取消撤销整批。
[[nodiscard]] Json EvaluateGraph(const GraphRequest& request, std::stop_token stop);
/// @param request 已验证只读状态和策略；@return 全部合法行动和精确选招概率，不含回合随机概率。
[[nodiscard]] Json EvaluateLegalActions(const LegalActionsRequest& request);
} // namespace pbi::contract
