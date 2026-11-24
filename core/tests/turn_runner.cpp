#include "pbi/turn.hpp"
#include "domain_json.hpp"
#include <iostream>

namespace {
using Json = nlohmann::json;
/// @param input 非负有界限额或 null；@return 当前平台可表示的显式预算，不截断为零。
std::optional<std::size_t> Limit(const Json& input) {
  if (input.is_null()) return std::nullopt;
  const auto value = pbi::contract::ReadInteger(input);
  if (value < 0) throw std::invalid_argument("turn vector limit must be nonnegative");
  return static_cast<std::size_t>(value);
}
/// @param input 稳定侧标识；@return 类型化领域侧，不接受默认回退。
pbi::BattleSide Side(const Json& input) {
  const auto value = input.get<std::string>();
  if (value == "attacker") return pbi::BattleSide::attacker;
  if (value == "defender") return pbi::BattleSide::defender;
  throw std::invalid_argument("unsupported battle side");
}
/// @param input 正式合法行动 JSON 形状；@return 已验证完整行动身份。
pbi::BattleAction Action(const Json& input) {
  const auto kind = input.at("kind").get<std::string>(); const auto side = Side(input.at("side"));
  if (kind == "use-move") return pbi::ValidateAction(pbi::UseMoveAction{side, pbi::contract::ReadInteger(input.at("move_id")),
      pbi::contract::ReadInt32(input.at("priority")), pbi::contract::ReadInteger(input.at("slot_id"))});
  if (kind == "struggle") return pbi::StruggleAction{side};
  if (kind == "pass") return pbi::PassAction{side};
  throw std::invalid_argument("unsupported battle action");
}
/// @param input 原稳定行动策略标识；@return 原生枚举，未知策略显式失败。
pbi::ActionPolicy Policy(const Json& input) {
  const auto value = input.get<std::string>();
  if (value == "uniform-random") return pbi::ActionPolicy::uniform_random;
  if (value == "first-legal-action") return pbi::ActionPolicy::first_legal_action;
  throw std::invalid_argument("unsupported action policy");
}
/// @param input 完整正式回合/固定战斗差分请求；@return 真实 Core 的全部状态/事件/图与解。
Json Run(const Json& input) {
  const auto state = pbi::contract::ReadBattleStateValue(input.at("state"));
  auto knowledge = pbi::contract::ReadTypeChart(input.at("type_chart"));
  const auto& limits = input.at("turn_limits");
  const pbi::TurnLimits turn_limits{Limit(limits.at("max_branches")), Limit(limits.at("max_event_paths"))};
  const auto mode = input.at("mode").get<std::string>();
  const auto first_policy = Policy(input.at("attacker_policy")), second_policy = Policy(input.at("defender_policy"));
  if (mode == "fixed") {
    pbi::FixedBattleOptions options;
    options.attacker_policy = first_policy; options.defender_policy = second_policy; options.observer = Side(input.at("observer"));
    options.turn_limits = turn_limits; options.max_equation_nodes = Limit(input.at("max_equation_nodes"));
    const auto& graph_limits = input.at("graph_limits");
    options.graph_limits.max_nodes = Limit(graph_limits.at("max_nodes")); options.graph_limits.max_edges = Limit(graph_limits.at("max_edges"));
    if (!graph_limits.at("max_turns").is_null()) options.graph_limits.max_turns = pbi::contract::ReadInteger(graph_limits.at("max_turns"));
    const auto result = pbi::InferFixedBattle(state, std::move(knowledge), options);
    return {{"kind", "fixed"}, {"graph", pbi::test_vectors::Graph(result.graph)},
        {"solution", pbi::test_vectors::Solution(result.solution, result.graph.Components())}};
  }
  const pbi::StandardTurnResolver resolver{std::move(knowledge)};
  std::vector<pbi::BattleTransition> result;
  if (mode == "resolve") result = resolver.Resolve(state, Action(input.at("attacker_action")), Action(input.at("defender_action")), turn_limits).transitions;
  else if (mode == "expand") result = resolver.Expand(state, first_policy, second_policy, turn_limits);
  else throw std::invalid_argument("unsupported turn vector mode");
  auto transitions = Json::array(), phases = Json::array();
  for (const auto& transition : result) transitions.push_back(pbi::test_vectors::Transition(transition));
  constexpr std::array names{"turn-start", "action-selection", "action-order", "before-move", "accuracy-check", "before-damage", "damage", "after-damage", "after-move", "faint-check", "turn-end"};
  for (const auto phase : pbi::stable_turn_phases) phases.push_back(names.at(static_cast<std::size_t>(phase)));
  return {{"kind", mode}, {"transitions", transitions}, {"phases", phases}};
}
} // namespace

/// 无参数；逐行调用真实正式回合/固定战斗，错误返回 error 并继续，不委托 Python 运行时。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << Run(Json::parse(line)).dump() << '\n'; }
    catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
