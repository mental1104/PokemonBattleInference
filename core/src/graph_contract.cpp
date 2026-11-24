#include "graph_contract.hpp"

#include <array>
#include <limits>
#include <type_traits>

namespace pbi::contract {
namespace {
constexpr std::array<std::string_view, 2> sides{"attacker", "defender"};
constexpr std::array<std::string_view, 5> outcomes{"attacker-win", "defender-win", "draw", "non-terminal", "unknown"};
constexpr std::array<std::string_view, 2> cycles{"declare-draw", "solve-absorption-probability"};
constexpr std::array<std::string_view, 3> truncations{"max-turns", "max-nodes", "max-edges"};
constexpr std::array<std::string_view, 4> components{"acyclic", "closed-cycle", "terminal-reachable-cycle", "open-unresolved-cycle"};
constexpr std::array<std::string_view, 4> statuses{"incomplete-graph", "resource-limit-exceeded", "singular-system", "cancelled"};
constexpr std::array<std::string_view, 2> policies{"uniform-random", "first-legal-action"};

/// @param stop 共享 C 令牌对应的只读状态；已取消时明确中断，不交付部分拓扑结果。
void CheckGraphCancelled(std::stop_token stop) {
  if (stop.stop_requested()) throw RequestError(PBI_CANCELLED_V1, "calculation cancelled");
}
/// @param value JSON 索引，必须为非负整数；@return 当前平台可表示的索引，bool/float 不转换。
std::size_t ReadIndex(const Json& value) {
  const auto number = ReadInteger(value);
  if (number < 0 || static_cast<std::uint64_t>(number) > std::numeric_limits<std::size_t>::max()) {
    throw RequestError(PBI_INVALID_INPUT_V1, "invalid graph index");
  }
  return static_cast<std::size_t>(number);
}
/// @param value 单个已验证领域行动；@return 类型专属的完整身份，不制造可空 move_id。
Json ActionJson(const BattleAction& value) {
  // 根据互斥行动类型构造对应字段，完整保留身份而不读取不存在的招式字段。
  return std::visit([](const auto& action) -> Json {
    const auto side = sides.at(static_cast<std::size_t>(action.side));
    using T = std::decay_t<decltype(action)>;
    if constexpr (std::is_same_v<T, UseMoveAction>) {
      return {{"kind", "use-move"}, {"side", side}, {"move_id", action.move_id}, {"priority", action.priority}, {"slot_id", action.slot_id}};
    } else if constexpr (std::is_same_v<T, StruggleAction>) {
      return {{"kind", "struggle"}, {"side", side}};
    } else {
      return {{"kind", "pass"}, {"side", side}};
    }
  }, value);
}
} // namespace

GraphRequest ReadGraphRequest(const Json& value, std::size_t available_nodes,
    std::size_t available_edges, std::stop_token stop) {
  RequireSchema(value, {"kind", "nodes", "edges", "root", "observer", "truncations"}, {"max_equation_nodes"});
  const auto& node_values = value.at("nodes");
  const auto& edge_values = value.at("edges");
  const auto& reasons = value.at("truncations");
  if (!node_values.is_array() || !edge_values.is_array() || !reasons.is_array()) {
    throw RequestError(PBI_INVALID_INPUT_V1, "graph collections must be arrays");
  }
  if (node_values.size() > available_nodes || edge_values.size() > available_edges) {
    throw RequestError(PBI_RESOURCE_LIMIT_V1, "graph topology budget exceeded");
  }
  if (reasons.size() > truncations.size()) throw RequestError(PBI_INVALID_INPUT_V1, "invalid graph truncations");
  auto equation_limit = static_cast<std::size_t>(PBI_V1_MAX_EQUATION_NODES);
  if (value.contains("max_equation_nodes")) {
    equation_limit = ReadIndex(value.at("max_equation_nodes"));
    if (equation_limit > PBI_V1_MAX_EQUATION_NODES) throw RequestError(PBI_RESOURCE_LIMIT_V1, "graph equation budget exceeded");
    if (equation_limit == 0) throw RequestError(PBI_INVALID_INPUT_V1, "graph equation budget must be positive");
  }
  std::vector<ProbabilityNode> nodes;
  std::vector<ProbabilityEdge> edges;
  std::vector<GraphTruncation> limits;
  nodes.reserve(node_values.size());
  edges.reserve(edge_values.size());
  for (const auto& node : node_values) {
    CheckGraphCancelled(stop);
    RequireFields(node, {"outcome", "cycle_resolution"});
    nodes.push_back({ReadEnum<GraphOutcome>(node.at("outcome"), outcomes), ReadEnum<CycleResolution>(node.at("cycle_resolution"), cycles)});
  }
  for (const auto& edge : edge_values) {
    CheckGraphCancelled(stop);
    RequireFields(edge, {"source", "target", "probability"});
    edges.push_back({{ReadIndex(edge.at("source"))}, {ReadIndex(edge.at("target"))}, ReadFraction(edge.at("probability"))});
  }
  for (const auto& reason : reasons) limits.push_back(ReadEnum<GraphTruncation>(reason, truncations));
  return {ProbabilityGraph{std::move(nodes), std::move(edges), {ReadIndex(value.at("root"))}, std::move(limits)},
      ReadEnum<BattleSide>(value.at("observer"), sides), equation_limit};
}

LegalActionsRequest ReadLegalActionsRequest(const Json& value, std::size_t remaining_rolls) {
  RequireFields(value, {"kind", "state", "side", "policy"});
  // 复用已有状态合同的全部验证和策略槽位记账，不复制第二份状态解码规则。
  const Json state_request{{"kind", "battle_state"}, {"state", value.at("state")}, {"updates", Json::array()}};
  auto [state, consumed] = ReadBattleStateRequest(state_request, remaining_rolls);
  static_cast<void>(consumed);
  return {std::move(state.state), ReadEnum<BattleSide>(value.at("side"), sides), ReadEnum<ActionPolicy>(value.at("policy"), policies)};
}

Json EvaluateGraph(const GraphRequest& request, std::stop_token stop) {
  auto component_values = Json::array();
  // Core 的迭代 SCC 遍历会检查同一个令牌；取消异常必须转为正式 CANCELLED 而不是 INTERNAL_ERROR。
  try {
    for (const auto& component : AnalyzeComponents(request.graph, stop)) {
      CheckGraphCancelled(stop);
      auto nodes = Json::array();
      auto outgoing = Json::array();
      for (const auto id : component.nodes) nodes.push_back(id.value);
      for (const auto id : component.outgoing) outgoing.push_back(id.value);
      component_values.push_back({{"id", component.id.value}, {"nodes", std::move(nodes)},
          {"kind", components.at(static_cast<std::size_t>(component.kind))}, {"outgoing", std::move(outgoing)},
          {"reaches_terminal", component.reaches_terminal}});
    }
  } catch (const std::runtime_error&) {
    CheckGraphCancelled(stop);
    throw;
  }
  const auto solution = SolveGraph(request.graph, request.observer, request.max_equation_nodes, stop);
  CheckGraphCancelled(stop);
  Json result{{"kind", "graph"}, {"components", std::move(component_values)}};
  if (const auto* solved = std::get_if<SolvedGraph>(&solution)) {
    result["status"] = "solved";
    result["win"] = FractionJson(solved->win);
    result["loss"] = FractionJson(solved->loss);
    result["draw"] = FractionJson(solved->draw);
    result["closed_cycle"] = FractionJson(solved->closed_cycle);
    if (const auto* finite = std::get_if<FiniteExpectedTurns>(&solved->expected_turns)) {
      result["expected_turns"] = {{"status", "finite"}, {"value", FractionJson(finite->value)}};
    } else {
      result["expected_turns"] = {{"status", "infinite"}, {"value", nullptr}};
    }
  } else {
    const auto& unavailable = std::get<UnavailableGraph>(solution);
    if (unavailable.status == GraphSolveStatus::resource_limit_exceeded) throw RequestError(PBI_RESOURCE_LIMIT_V1, "graph equation budget exceeded");
    if (unavailable.status == GraphSolveStatus::cancelled) throw RequestError(PBI_CANCELLED_V1, "calculation cancelled");
    result["status"] = statuses.at(static_cast<std::size_t>(unavailable.status));
    result["win"] = nullptr;
    result["loss"] = nullptr;
    result["draw"] = nullptr;
    result["closed_cycle"] = nullptr;
    result["expected_turns"] = {{"status", "unavailable"}, {"value", nullptr}};
    result["diagnostics"] = unavailable.diagnostics;
  }
  return result;
}

Json EvaluateLegalActions(const LegalActionsRequest& request) {
  const auto actions = GenerateLegalActions(request.state, request.side);
  const auto distribution = SelectActions(actions, request.policy);
  auto action_values = Json::array();
  auto selections = Json::array();
  for (const auto& action : actions) action_values.push_back(ActionJson(action));
  for (const auto& selection : distribution) selections.push_back({{"action", ActionJson(selection.action)}, {"probability", FractionJson(selection.probability)}});
  return {{"kind", "legal_actions"}, {"actions", std::move(action_values)}, {"selections", std::move(selections)}};
}
} // namespace pbi::contract
