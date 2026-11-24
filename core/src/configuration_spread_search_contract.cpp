#include "configuration_spread_search_contract.hpp"

namespace pbi::contract {
namespace {
/// @param stop 同源令牌；取消时整次失败，不发布部分候选。
void CheckStop(CancellationToken stop) {
  if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "configuration spread search cancelled");
}
/// @param value 明确JSON顺序数组；非数组直接失败，禁止对象隐式迭代。
void RequireArray(const Json& value) {
  if (!value.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "configuration search field must be an array");
}
/// @param value 原单行性格完整事实；@return 不按目标选择或改写倍率的拥有知识。
ConfigurationSearchNature ReadNature(const Json& value) {
  RequireFields(value, {"identifier", "label", "modifier"});
  const auto& modifiers = value.at("modifier");
  RequireArray(modifiers);
  if (modifiers.size() != 5) throw RequestError(PBI_INVALID_INPUT_V1, "configuration nature must contain five multipliers");
  ConfigurationNature nature;
  for (std::size_t index = 0; index < nature.multipliers.size(); ++index) {
    if (!modifiers[index].is_number()) throw RequestError(PBI_INVALID_INPUT_V1, "nature multiplier must be numeric");
    nature.multipliers[index] = modifiers[index].get<double>();
    if (!std::isfinite(nature.multipliers[index])) throw RequestError(PBI_INVALID_INPUT_V1, "nature multiplier must be finite");
  }
  return {value.at("identifier").get<std::string>(), value.at("label").get<std::string>(), nature};
}
/// @param ranges Core计算的六个独立范围；@return HP/Atk/Def/SpAtk/SpDef/Speed稳定顺序。
Json RangesJson(const ConfigurationSpreadRanges& ranges) {
  auto result = Json::array();
  for (const auto& range : ranges) result.push_back({{"minimum", range.minimum}, {"maximum", range.maximum}});
  return result;
}
} // namespace

ConfigurationSpreadSearchRequest ReadConfigurationSpreadSearchRequest(const Json& value, CancellationToken stop) {
  CheckStop(stop);
  RequireSchema(value, {"kind", "generation_id", "subject_base", "natures", "type_chart"}, {"policy", "max_candidates", "goals", "speed_goals"});
  if (value.at("kind") != "configuration_spread_search") throw RequestError(PBI_INVALID_INPUT_V1, "invalid configuration spread operation kind");
  const auto generation = ReadInt32(value.at("generation_id"));
  auto policy = DamagePolicyForGeneration(generation);
  if (value.contains("policy")) policy = ReadPolicy(value.at("policy"), std::move(policy));
  const auto base = ReadPokemon(value.at("subject_base"));
  static_cast<void>(ReadConfigurationGoalPokemon(value.at("subject_base"), base.level));
  ConfigurationSpreadSearchInput input;
  input.subject = {base.stats, base.types, base.level, base.ability, base.item};
  if (value.contains("max_candidates")) {
    const auto maximum = ReadInteger(value.at("max_candidates"));
    if (maximum < 1 || maximum > 10) throw RequestError(PBI_INVALID_INPUT_V1, "max_candidates must be between 1 and 10");
    input.max_candidates = static_cast<std::size_t>(maximum);
  }
  RequireArray(value.at("natures"));
  for (const auto& nature : value.at("natures")) { CheckStop(stop); input.natures.push_back(ReadNature(nature)); }
  if (value.contains("goals")) {
    RequireArray(value.at("goals"));
    for (const auto& goal : value.at("goals")) { CheckStop(stop); input.goals.push_back(ReadConfigurationDamageGoal(goal, base.level)); }
  }
  if (value.contains("speed_goals")) {
    RequireArray(value.at("speed_goals"));
    for (const auto& goal : value.at("speed_goals")) {
      CheckStop(stop);
      RequireFields(goal, {"goal_id", "target_speed"});
      input.speed_goals.push_back({goal.at("goal_id").get<std::string>(), ReadInt32(goal.at("target_speed"))});
    }
  }
  return {std::move(input), std::move(policy), ReadTypeChart(value.at("type_chart")), generation};
}

Json EvaluateConfigurationSpreadSearch(const ConfigurationSpreadSearchRequest& request, CancellationToken stop) {
  CheckStop(stop);
  const ConfigurationGoalEvaluator evaluator{request.policy, request.knowledge, stop};
  const auto solved = SearchConfigurationSpreads(request.input, evaluator, stop);
  auto candidates = Json::array();
  for (const auto& candidate : solved.candidates) {
    CheckStop(stop);
    auto options = Json::array();
    for (const auto& nature : candidate.nature_options) options.push_back({{"identifier", nature.identifier}, {"label", nature.label}});
    candidates.push_back({{"candidate_id", candidate.candidate_id}, {"nature_id", candidate.nature_id}, {"nature_label", candidate.nature_label},
        {"nature_options", std::move(options)}, {"evs", ConfigurationStatsJson(candidate.evs)}, {"ivs", ConfigurationStatsJson(candidate.ivs)},
        {"ev_ranges", RangesJson(candidate.ev_ranges)}, {"iv_ranges", RangesJson(candidate.iv_ranges)}, {"stats", ConfigurationStatsJson(candidate.stats)},
        {"goals", ConfigurationGoalResultsJson(candidate.goals, request.generation)}, {"speed_goals", ConfigurationSpeedGoalResultsJson(candidate.speed_goals)}});
  }
  return {{"kind", "configuration_spread_search"}, {"reachable", solved.Reachable()}, {"candidates", std::move(candidates)},
      {"rejected_goals", ConfigurationGoalResultsJson(solved.rejected_goals, request.generation)},
      {"rejected_speed_goals", ConfigurationSpeedGoalResultsJson(solved.rejected_speed_goals)}};
}
} // namespace pbi::contract
