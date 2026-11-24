#include "pbi/battle_graph.hpp"
#include "../src/state_contract.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <type_traits>

namespace {
using Json = nlohmann::json;
/// @param value 只读精确分数；@return 完整字符串分数对象。
Json Fraction(const pbi::Rational& value) { return {{"numerator", value.numerator().str()}, {"denominator", value.denominator().str()}}; }
/// @param value 可空任意精度数；@return 十进制字符串或 null，不经浮点数。
Json Number(const std::optional<pbi::Integer>& value) { return value ? Json(value->str()) : Json(nullptr); }
/// @param value 可空领域侧；@return 稳定标识或 null。
Json Side(std::optional<pbi::BattleSide> value) { return value ? Json(*value == pbi::BattleSide::attacker ? "attacker" : "defender") : Json(nullptr); }
/// @param value 稳定类别；@return 原 Python outcome 字符串。
const char* Outcome(pbi::GraphOutcome value) {
  constexpr std::array names{"attacker-win", "defender-win", "draw", "non-terminal", "unknown"};
  return names.at(static_cast<std::size_t>(value));
}
/// @param value 稳定 SCC 类别；@return 原 Python 分量分类。
const char* Component(pbi::ComponentKind value) {
  constexpr std::array names{"acyclic", "closed-cycle", "terminal-reachable-cycle", "open-unresolved-cycle"};
  return names.at(static_cast<std::size_t>(value));
}
/// @param value 稳定保护原因；@return 原 Python 截断标识。
const char* Truncation(pbi::GraphTruncation value) {
  constexpr std::array names{"max-turns", "max-nodes", "max-edges"};
  return names.at(static_cast<std::size_t>(value));
}
/// @param value 终局或保护原因；@return 稳定字符串或 null。
Json Reason(const std::optional<pbi::GraphStopReason>& value) {
  if (!value) return nullptr;
  return std::visit([](auto reason) -> Json {
    if constexpr (std::is_same_v<decltype(reason), pbi::GraphTruncation>) return Truncation(reason);
    else {
      constexpr std::array names{"knockout", "mutual-knockout", "no-legal-action", "cycle-guard"};
      return names.at(static_cast<std::size_t>(reason));
    }
  }, *value);
}
/// @param event 普通随机或业务事件；@return 完整类型化事件投影，业务类型不擦除。
Json Event(const pbi::PathEvent& event) {
  return std::visit([](const auto& item) {
    const auto identity = [&]() {
      if constexpr (std::is_same_v<std::decay_t<decltype(item)>, pbi::TransitionEvent>) return item;
      else return item.Identity();
    }();
    const auto& data = identity.View();
    constexpr std::array types{"hit_check", "damage_roll", "speed_tie", "secondary_effect", "custom"};
    Json result{{"kind", "random"}, {"event_type", types.at(static_cast<std::size_t>(data.type))},
        {"event_id", data.event_id}, {"outcome_id", data.outcome_id}, {"numeric_value", Number(data.numeric_value)}};
    if constexpr (std::is_same_v<std::decay_t<decltype(item)>, pbi::BattleEvent>) {
      const auto& business = item.View(); result["kind"] = "battle";
      result["battle_kind"] = pbi::BattleEventName(business.kind); result["turn_number"] = business.turn_number;
      result["actor"] = Side(business.actor); result["target"] = Side(business.target);
      result["move_id"] = business.move_id ? Json(*business.move_id) : Json(nullptr);
      result["source_identifier"] = business.source_identifier ? Json(*business.source_identifier) : Json(nullptr);
      result["value"] = Number(business.value); result["before"] = Number(business.before); result["after"] = Number(business.after);
    }
    return result;
  }, event);
}
/// @param summary 只读替代历史；@return 完整路径和精确条件权重。
Json Paths(const pbi::EventSummary& summary) {
  Json result = Json::array();
  for (const auto& path : summary.Paths()) {
    auto events = Json::array(); for (const auto& event : path.events) events.push_back(Event(event));
    result.push_back({{"events", events}, {"probability", Fraction(path.probability)}});
  }
  return result;
}
/// 测试专用图扩展脚本；仅验证图构造和转移语义，不冒充完整战斗回合引擎。
enum class Expansion { decrement, binary, cycle, empty };
/// @param state 只读父状态；@param mode 固定测试脚本；@return 实际不可变领域分布。
std::vector<pbi::BattleTransition> Expand(const pbi::BattleState& state, Expansion mode) {
  if (mode == Expansion::empty) return {};
  if (mode == Expansion::cycle) return {pbi::BattleTransition{{pbi::Rational{1}, state.NextTurn(), pbi::EventSummary{}, "cycle"}}};
  const auto before = state.View().defender.View().current_hp;
  std::vector<pbi::BattleTransition> result;
  const auto count = mode == Expansion::binary ? 2 : 1;
  for (int amount = 1; amount <= count; ++amount) {
    const auto after = std::max(0, before - amount);
    const auto probability = count == 1 ? pbi::Rational{1} : pbi::Rational{amount, 3};
    const pbi::TransitionEvent random{{pbi::TransitionEventType::damage_roll, "scripted-damage", std::to_string(amount), pbi::Integer{amount}}};
    const pbi::BattleEvent business{{pbi::BattleEventKind::damage, state.View().turn_number, pbi::BattleSide::attacker,
        pbi::BattleSide::defender, 1, "move", pbi::Integer{before - after}, std::nullopt, std::nullopt}};
    result.emplace_back(pbi::BattleTransitionData{probability,
        state.WithBattler(pbi::BattleSide::defender, state.View().defender.WithCurrentHp(after)).NextTurn(),
        pbi::EventSummary{{{{random, business}, pbi::Rational{1}}}}, "hit-" + std::to_string(amount)});
  }
  return result;
}
/// @param input 完整图测试合同；@return 真实 Core 图的所有节点、边、事件和统计。
Json Run(const Json& input) {
  const auto request = pbi::contract::ReadBattleStateRequest({{"kind", "battle_state"}, {"state", input.at("initial")}, {"updates", Json::array()}}, 1048576).first;
  const auto name = input.at("mode").get<std::string>();
  Expansion mode;
  if (name == "decrement") mode = Expansion::decrement;
  else if (name == "binary") mode = Expansion::binary;
  else if (name == "cycle") mode = Expansion::cycle;
  else if (name == "empty") mode = Expansion::empty;
  else throw std::invalid_argument("unsupported test expansion");
  pbi::GraphLimits limits;
  const auto& values = input.at("limits");
  if (!values.at("max_nodes").is_null()) limits.max_nodes = values.at("max_nodes").get<std::size_t>();
  if (!values.at("max_edges").is_null()) limits.max_edges = values.at("max_edges").get<std::size_t>();
  if (!values.at("max_turns").is_null()) limits.max_turns = values.at("max_turns").get<std::int64_t>();
  const auto graph = pbi::BuildBattleGraph(request.state, [mode](const pbi::BattleState& state) { return Expand(state, mode); }, limits);
  Json nodes = Json::array(), edges = Json::array(), components = Json::array(), truncations = Json::array();
  for (const auto& node : graph.Nodes()) {
    pbi::contract::BattleStateRequest projection{node.state, {}, std::nullopt, std::nullopt};
    auto path = Json::array(); for (const auto id : graph.RepresentativePath(node.id)) path.push_back(id.value);
    nodes.push_back({{"id", node.id.value}, {"state", pbi::contract::EvaluateBattleState(projection).at("state")},
        {"outcome", Outcome(node.outcome)}, {"reason", Reason(node.reason)}, {"predecessor_node", node.predecessor_node ? Json(node.predecessor_node->value) : Json(nullptr)},
        {"predecessor_edge", node.predecessor_edge ? Json(node.predecessor_edge->value) : Json(nullptr)}, {"path", path}});
  }
  for (const auto& edge : graph.Edges()) edges.push_back({{"id", edge.id.value}, {"source", edge.source.value}, {"target", edge.target.value},
      {"probability", Fraction(edge.probability)}, {"paths", Paths(edge.events)}, {"source_key", edge.source_key ? Json(*edge.source_key) : Json(nullptr)}});
  for (const auto& component : graph.Components()) {
    auto members = Json::array(), outgoing = Json::array();
    for (const auto id : component.nodes) members.push_back(id.value);
    for (const auto id : component.outgoing) outgoing.push_back(id.value);
    components.push_back({{"id", component.id.value}, {"nodes", members}, {"kind", Component(component.kind)}, {"outgoing", outgoing}, {"reaches_terminal", component.reaches_terminal}});
  }
  for (const auto reason : graph.Truncations()) truncations.push_back(Truncation(reason));
  const auto& stats = graph.Statistics(); const auto& counts = stats.terminal_counts;
  return {{"nodes", nodes}, {"edges", edges}, {"components", components}, {"truncations", truncations}, {"statistics", {
      {"nodes", stats.nodes}, {"edges", stats.edges}, {"max_turn_number", stats.max_turn_number}, {"closed_cycles", stats.closed_cycles},
      {"terminal_reachable_cycles", stats.terminal_reachable_cycles}, {"terminal_counts", {{"attacker_wins", counts.attacker_wins},
      {"defender_wins", counts.defender_wins}, {"draws", counts.draws}, {"non_terminal", counts.non_terminal}, {"unknown", counts.unknown}}}}}};
}
} // namespace

/// 无参数；逐行调用真实构图引擎，错误显式输出并继续后续测试向量。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << Run(Json::parse(line)).dump() << '\n'; }
    catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
