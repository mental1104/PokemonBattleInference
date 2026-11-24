#include "pbi/battle_graph.hpp"
#include "domain_json.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <type_traits>

namespace {
using Json = nlohmann::json;
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
  return pbi::test_vectors::Graph(graph);
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
