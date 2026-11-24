#pragma once

#include "pbi/battle_graph.hpp"
#include "../src/state_contract.hpp"
#include <array>
#include <type_traits>

namespace pbi::test_vectors {
using Json = nlohmann::json;
/// @param value 只读精确分数；@return 任意长度分子/分母字符串，不经过浮点。
inline Json Fraction(const Rational& value) { return {{"numerator", value.numerator().str()}, {"denominator", value.denominator().str()}}; }
/// @param value 可空精确整数；@return 十进制字符串或 null。
inline Json Number(const std::optional<Integer>& value) { return value ? Json(value->str()) : Json(nullptr); }
/// @param value 可空固定侧；@return 稳定标识或 null。
inline Json Side(std::optional<BattleSide> value) { return value ? Json(*value == BattleSide::attacker ? "attacker" : "defender") : Json(nullptr); }
/// @param value 已验证节点类别；@return 原 Python 领域标识。
inline const char* Outcome(GraphOutcome value) {
  constexpr std::array names{"attacker-win", "defender-win", "draw", "non-terminal", "unknown"};
  return names.at(static_cast<std::size_t>(value));
}
/// @param value 已验证 SCC 类别；@return 原 Python 分量分类。
inline const char* Component(ComponentKind value) {
  constexpr std::array names{"acyclic", "closed-cycle", "terminal-reachable-cycle", "open-unresolved-cycle"};
  return names.at(static_cast<std::size_t>(value));
}
/// @param value 已验证预算原因；@return 原 Python 截断标识。
inline const char* Truncation(GraphTruncation value) {
  constexpr std::array names{"max-turns", "max-nodes", "max-edges"};
  return names.at(static_cast<std::size_t>(value));
}
/// @param value 节点确定终止或保护原因；@return 稳定标识/null，不把 unknown 映射为平局。
inline Json Reason(const std::optional<GraphStopReason>& value) {
  if (!value) return nullptr;
  return std::visit([](auto reason) -> Json {
    if constexpr (std::is_same_v<decltype(reason), GraphTruncation>) return Truncation(reason);
    else {
      constexpr std::array names{"knockout", "mutual-knockout", "no-legal-action", "cycle-guard"};
      return names.at(static_cast<std::size_t>(reason));
    }
  }, *value);
}
/// @param event 已验证随机/业务事件；@return 完整固定投影，保留不同的 variant 类型。
inline Json Event(const PathEvent& event) {
  return std::visit([](const auto& item) {
    const auto identity = [&]() {
      if constexpr (std::is_same_v<std::decay_t<decltype(item)>, TransitionEvent>) return item;
      else return item.Identity();
    }();
    const auto& data = identity.View();
    constexpr std::array types{"hit_check", "damage_roll", "speed_tie", "secondary_effect", "custom"};
    Json result{{"kind", "random"}, {"event_type", types.at(static_cast<std::size_t>(data.type))},
        {"event_id", data.event_id}, {"outcome_id", data.outcome_id}, {"numeric_value", Number(data.numeric_value)}};
    if constexpr (std::is_same_v<std::decay_t<decltype(item)>, BattleEvent>) {
      const auto& business = item.View(); result["kind"] = "battle";
      result["battle_kind"] = BattleEventName(business.kind); result["turn_number"] = business.turn_number;
      result["actor"] = Side(business.actor); result["target"] = Side(business.target);
      result["move_id"] = business.move_id ? Json(*business.move_id) : Json(nullptr);
      result["source_identifier"] = business.source_identifier ? Json(*business.source_identifier) : Json(nullptr);
      result["value"] = Number(business.value); result["before"] = Number(business.before); result["after"] = Number(business.after);
    }
    return result;
  }, event);
}
/// @param summary 只读条件历史；@return 所有完整历史与精确条件权重。
inline Json Paths(const EventSummary& summary) {
  Json result = Json::array();
  for (const auto& path : summary.Paths()) {
    auto events = Json::array(); for (const auto& event : path.events) events.push_back(Event(event));
    result.push_back({{"events", events}, {"probability", Fraction(path.probability)}});
  }
  return result;
}
/// @param state 已验证完整状态；@return 复用唯一 ABI 状态编码，不另写第二套字段投影。
inline Json State(const BattleState& state) {
  return contract::StateJson(state);
}
/// @param transition 已验证精确分支；@return 完整状态/概率/事件/来源，供差分而非生产 C ABI。
inline Json Transition(const BattleTransition& transition) {
  const auto& value = transition.View();
  return {{"probability", Fraction(value.probability)}, {"state", State(value.state)}, {"paths", Paths(value.events)},
      {"source_key", value.source_key ? Json(*value.source_key) : Json(nullptr)}};
}
/// @param components 已验证 SCC 列表；@return 全部分量编号/成员/出边/终局可达性。
inline Json Components(std::span<const StrongComponent> components) {
  auto result = Json::array();
  for (const auto& component : components) {
    auto members = Json::array(), outgoing = Json::array();
    for (const auto id : component.nodes) members.push_back(id.value);
    for (const auto id : component.outgoing) outgoing.push_back(id.value);
    result.push_back({{"id", component.id.value}, {"nodes", members}, {"kind", Component(component.kind)}, {"outgoing", outgoing}, {"reaches_terminal", component.reaches_terminal}});
  }
  return result;
}
/// @param graph 真实构图引擎结果；@return 所有状态/路径/事件/统计，不仅检查规模。
inline Json Graph(const BattleGraph& graph) {
  Json nodes = Json::array(), edges = Json::array(), truncations = Json::array();
  for (const auto& node : graph.Nodes()) {
    auto path = Json::array(); for (const auto id : graph.RepresentativePath(node.id)) path.push_back(id.value);
    nodes.push_back({{"id", node.id.value}, {"state", State(node.state)}, {"outcome", Outcome(node.outcome)}, {"reason", Reason(node.reason)},
        {"predecessor_node", node.predecessor_node ? Json(node.predecessor_node->value) : Json(nullptr)},
        {"predecessor_edge", node.predecessor_edge ? Json(node.predecessor_edge->value) : Json(nullptr)}, {"path", path}});
  }
  for (const auto& edge : graph.Edges()) edges.push_back({{"id", edge.id.value}, {"source", edge.source.value}, {"target", edge.target.value},
      {"probability", Fraction(edge.probability)}, {"paths", Paths(edge.events)}, {"source_key", edge.source_key ? Json(*edge.source_key) : Json(nullptr)}});
  for (const auto reason : graph.Truncations()) truncations.push_back(Truncation(reason));
  const auto& stats = graph.Statistics(); const auto& counts = stats.terminal_counts;
  return {{"nodes", nodes}, {"edges", edges}, {"components", Components(graph.Components())}, {"truncations", truncations}, {"statistics", {
      {"nodes", stats.nodes}, {"edges", stats.edges}, {"max_turn_number", stats.max_turn_number}, {"closed_cycles", stats.closed_cycles},
      {"terminal_reachable_cycles", stats.terminal_reachable_cycles}, {"terminal_counts", {{"attacker_wins", counts.attacker_wins},
      {"defender_wins", counts.defender_wins}, {"draws", counts.draws}, {"non_terminal", counts.non_terminal}, {"unknown", counts.unknown}}}}}};
}
/// @param solution 真实精确求解；@param components 同一图 SCC；@return 全部数值及不可用/无限语义。
inline Json Solution(const GraphSolution& solution, std::span<const StrongComponent> components) {
  Json result{{"components", Components(components)}};
  if (const auto* solved = std::get_if<SolvedGraph>(&solution)) {
    result["status"] = "solved"; result["win"] = Fraction(solved->win); result["loss"] = Fraction(solved->loss);
    result["draw"] = Fraction(solved->draw); result["closed_cycle"] = Fraction(solved->closed_cycle);
    if (const auto* finite = std::get_if<FiniteExpectedTurns>(&solved->expected_turns)) result["expected_turns"] = {{"status", "finite"}, {"value", Fraction(finite->value)}};
    else result["expected_turns"] = {{"status", "infinite"}, {"value", nullptr}};
  } else {
    const auto& unavailable = std::get<UnavailableGraph>(solution);
    constexpr std::array statuses{"incomplete-graph", "resource-limit-exceeded", "singular-system", "cancelled"};
    result["status"] = statuses.at(static_cast<std::size_t>(unavailable.status));
    result["win"] = nullptr; result["loss"] = nullptr; result["draw"] = nullptr; result["closed_cycle"] = nullptr;
    result["expected_turns"] = {{"status", "unavailable"}, {"value", nullptr}};
  }
  return result;
}
} // namespace pbi::test_vectors
