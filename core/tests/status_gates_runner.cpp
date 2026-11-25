#include "pbi/status_gates.hpp"
#include "../src/state_contract.hpp"
#include <iostream>

namespace {
using namespace pbi;
using namespace pbi::contract;
constexpr std::array<std::string_view, 5> gate_names{"sleep", "freeze", "paralysis", "infatuation", "confusion"};
constexpr std::array<std::string_view, 3> decisions{"allow", "block", "replace_with_self_hit"};
/// @param input 原明确策略JSON；@return 完整typed策略，复用唯一精确分数reader。
StatusGateRules ReadRules(const Json& input) {
  RequireFields(input, {"sleep_wake_chances", "freeze_thaw_chance", "allow_thaw_move_override", "paralysis_speed_multiplier",
      "full_paralysis_chance", "burn_physical_multiplier", "burn_residual_fraction", "poison_residual_fraction",
      "bad_poison_base_fraction", "confusion_self_hit_chance", "infatuation_immobilize_chance"});
  StatusGateRules rules;
  rules.sleep_wake_chances.clear();
  for (const auto& probability : input.at("sleep_wake_chances")) rules.sleep_wake_chances.push_back(ReadFraction(probability));
  rules.freeze_thaw_chance = ReadFraction(input.at("freeze_thaw_chance"));
  rules.allow_thaw_move_override = ReadBool(input.at("allow_thaw_move_override"));
  rules.paralysis_speed_multiplier = ReadFraction(input.at("paralysis_speed_multiplier"));
  rules.full_paralysis_chance = ReadFraction(input.at("full_paralysis_chance"));
  rules.burn_physical_multiplier = ReadFraction(input.at("burn_physical_multiplier"));
  rules.burn_residual_fraction = ReadFraction(input.at("burn_residual_fraction"));
  rules.poison_residual_fraction = ReadFraction(input.at("poison_residual_fraction"));
  rules.bad_poison_base_fraction = ReadFraction(input.at("bad_poison_base_fraction"));
  rules.confusion_self_hit_chance = ReadFraction(input.at("confusion_self_hit_chance"));
  rules.infatuation_immobilize_chance = ReadFraction(input.at("infatuation_immobilize_chance"));
  ValidateStatusGateRules(rules); return rules;
}
/// @param rules 已验证原策略；@return 完整无损策略，检查generation默认事实亦非只测一个chance。
Json RulesJson(const StatusGateRules& rules) {
  auto sleep = Json::array();
  for (const auto& probability : rules.sleep_wake_chances) sleep.push_back(FractionJson(probability));
  return {{"sleep_wake_chances", std::move(sleep)}, {"freeze_thaw_chance", FractionJson(rules.freeze_thaw_chance)},
      {"allow_thaw_move_override", rules.allow_thaw_move_override}, {"paralysis_speed_multiplier", FractionJson(rules.paralysis_speed_multiplier)},
      {"full_paralysis_chance", FractionJson(rules.full_paralysis_chance)}, {"burn_physical_multiplier", FractionJson(rules.burn_physical_multiplier)},
      {"burn_residual_fraction", FractionJson(rules.burn_residual_fraction)}, {"poison_residual_fraction", FractionJson(rules.poison_residual_fraction)},
      {"bad_poison_base_fraction", FractionJson(rules.bad_poison_base_fraction)}, {"confusion_self_hit_chance", FractionJson(rules.confusion_self_hit_chance)},
      {"infatuation_immobilize_chance", FractionJson(rules.infatuation_immobilize_chance)}};
}
/// @param request 原状态、明确门禁/顺序、真实策略和测试RNG队列；@return 原完整结果和全部随机调用。
Json Run(const Json& request) {
  RequireSchema(request, {"status", "mode", "thaws_user_when_frozen", "chance_results"}, {"generation", "rules", "gate", "gates"});
  const auto status = ReadStatusValue(request.at("status"));
  const auto rules = request.contains("rules") ? ReadRules(request.at("rules"))
      : StatusGateRulesForGeneration(request.contains("generation") ? ReadInt32(request.at("generation")) : 9);
  const auto thaw = ReadBool(request.at("thaws_user_when_frozen"));
  std::vector<bool> outcomes;
  for (const auto& value : request.at("chance_results")) outcomes.push_back(ReadBool(value));
  std::size_t consumed = 0;
  auto probabilities = Json::array();
  const StatusChance chance = [&](const Rational& probability) {
    probabilities.push_back(FractionJson(probability));
    if (consumed >= outcomes.size()) throw std::invalid_argument("unexpected random chance call");
    return outcomes[consumed++];
  };
  const auto result = [&] {
    if (request.at("mode") == "single") return CheckStatusActionGate(ReadEnum<StatusActionGate>(request.at("gate"), gate_names), status, thaw, rules, chance);
    if (request.at("mode") == "default") return CheckDefaultStatusActionGates(status, thaw, rules, chance);
    if (request.at("mode") != "pipeline") throw std::invalid_argument("unknown status gate diagnostic mode");
    std::vector<StatusActionGate> gates;
    for (const auto& gate : request.at("gates")) gates.push_back(ReadEnum<StatusActionGate>(gate, gate_names));
    return CheckStatusActionGatePipeline(gates, status, thaw, rules, chance);
  }();
  return {{"decision", decisions.at(static_cast<std::size_t>(result.decision))}, {"updated_status", StatusJson(result.updated_status)},
      {"reason", result.reason ? Json(*result.reason) : Json(nullptr)}, {"events", result.events}, {"probabilities", std::move(probabilities)},
      {"consumed", consumed}, {"remaining", outcomes.size() - consumed}, {"rules", RulesJson(rules)}};
}
} // namespace
/// 无参数；仅诊断原独立BattleRandom端口，不注册公开随机操作或注入默认回合。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << Run(Json::parse(line)).dump() << '\n'; }
    catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
