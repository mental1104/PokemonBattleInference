#include "configuration_goals_contract.hpp"

namespace pbi::contract {
namespace {
/// @param stop 同源令牌；取消时整次失败，不发布部分模板结果。
void CheckStop(CancellationToken stop) {
  if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "configuration target solve cancelled");
}
/// @param value 明确JSON数组；禁止用对象值隐式替代原顺序列表。
void RequireArray(const Json& value) {
  if (!value.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "configuration goal field must be an array");
}
/// @param value 完整共享Pokemon快照；@param level 原统一等级；@return 原静态上下文实际消费字段。
ConfigurationGoalPokemon ReadGoalPokemon(const Json& value, std::int32_t level) {
  const auto pokemon = ReadPokemon(value);
  if (pokemon.level != level || pokemon.can_evolve || pokemon.grounding) {
    throw RequestError(PBI_INVALID_INPUT_V1, "configuration goals require a shared level and reference static Pokemon context");
  }
  return {pokemon.types, pokemon.stats, pokemon.ability, pokemon.item};
}
/// @param value 固定六项数组；@return 完整投入数据，不计算能力或推测缺省值。
BattleStats ReadSpread(const Json& value) {
  RequireArray(value);
  if (value.size() != 6) throw RequestError(PBI_INVALID_INPUT_V1, "configuration spread must contain six values");
  return {ReadInt32(value[0]), ReadInt32(value[1]), ReadInt32(value[2]), ReadInt32(value[3]), ReadInt32(value[4]), ReadInt32(value[5])};
}
/// @param value 完整原目标；@param level 统一等级；@return 不含预先满足性/伤害的类型化目标。
ConfigurationDamageGoal ReadGoal(const Json& value, std::int32_t level) {
  RequireSchema(value, {"goal_id", "kind", "target", "move"}, {"required_turns", "roll_policy"});
  const auto kind = ReadEnum<ConfigurationGoalKind>(value.at("kind"), std::array<std::string_view, 2>{"attack", "defense"});
  const auto& move = value.at("move");
  RequireFields(move, {"type", "category", "power"});
  const auto category = ReadEnum<DamageCategory>(move.at("category"), std::array<std::string_view, 3>{"physical", "special", "status"});
  std::optional<ConfigurationDamageRollPolicy> policy;
  if (value.contains("roll_policy") && !value.at("roll_policy").is_null()) policy = ReadEnum<ConfigurationDamageRollPolicy>(
      value.at("roll_policy"), std::array<std::string_view, 2>{"min", "max"});
  return {value.at("goal_id").get<std::string>(), kind, ReadGoalPokemon(value.at("target"), level),
      {static_cast<PokemonType>(ReadInt32(move.at("type"))), category, ReadInt32(move.at("power"))},
      value.contains("required_turns") ? ReadInt32(value.at("required_turns")) : 1, policy};
}
/// @param goals 原全部速度证据；@return 不在codec重算比较/margin的完整投影。
Json SpeedGoalsJson(const std::vector<ConfigurationSpeedGoalResult>& goals) {
  auto result = Json::array();
  for (const auto& goal : goals) result.push_back({{"goal_id", goal.goal_id}, {"satisfied", goal.satisfied},
      {"subject_speed", goal.subject_speed}, {"target_speed", goal.target_speed}, {"speed_margin", goal.speed_margin}});
  return result;
}
/// @param goals 原全部伤害目标证据；@param generation 原固定代际；@return 目标与完整伤害投影。
Json GoalsJson(const std::vector<ConfigurationDamageGoalResult>& goals, std::int32_t generation) {
  auto result = Json::array();
  for (const auto& goal : goals) result.push_back({{"goal_id", goal.goal_id}, {"kind", goal.kind == ConfigurationGoalKind::attack ? "attack" : "defense"},
      {"subject_role", goal.kind == ConfigurationGoalKind::attack ? "attacker" : "defender"}, {"satisfied", goal.satisfied},
      {"damage", DamageJson(goal.damage, generation)}, {"selected_damage", goal.selected_damage}, {"repetitions", goal.repetitions},
      {"total_damage", goal.total_damage.str()}, {"hp_threshold", goal.hp_threshold}, {"remaining_hp", goal.remaining_hp.str()},
      {"effective_attack", goal.effective_attack}, {"effective_defense", goal.effective_defense},
      {"roll_policy", goal.roll_policy == ConfigurationDamageRollPolicy::minimum ? "min" : "max"}});
  return result;
}
/// @param stats 原能力输出；@return 与其他Core操作一致的六字段值。
Json StatsJson(const BattleStats& stats) {
  return {{"hp", stats.hp}, {"attack", stats.attack}, {"defense", stats.defense}, {"special_attack", stats.special_attack}, {"special_defense", stats.special_defense}, {"speed", stats.speed}};
}
} // namespace

ConfigurationTemplatesRequest ReadConfigurationTemplatesRequest(const Json& value, CancellationToken stop) {
  CheckStop(stop);
  RequireSchema(value, {"kind", "generation_id", "subject_base", "templates", "type_chart"},
      {"policy", "allowed_stat_presets", "max_candidates", "goals", "speed_goals"});
  if (value.at("kind") != "configuration_templates") throw RequestError(PBI_INVALID_INPUT_V1, "invalid configuration template operation kind");
  const auto generation = ReadInt32(value.at("generation_id"));
  auto policy = DamagePolicyForGeneration(generation);
  if (value.contains("policy")) policy = ReadPolicy(value.at("policy"), std::move(policy));
  const auto base = ReadPokemon(value.at("subject_base"));
  static_cast<void>(ReadGoalPokemon(value.at("subject_base"), base.level));
  ConfigurationTemplateSolveInput input;
  input.subject = {base.stats, base.types, base.level, base.ability, base.item};
  if (value.contains("allowed_stat_presets")) {
    RequireArray(value.at("allowed_stat_presets"));
    input.allowed_stat_presets = value.at("allowed_stat_presets").get<std::vector<std::string>>();
  }
  if (value.contains("max_candidates")) {
    const auto maximum = ReadInteger(value.at("max_candidates"));
    if (maximum < 1 || maximum > 10) throw RequestError(PBI_INVALID_INPUT_V1, "max_candidates must be between 1 and 10");
    input.max_candidates = static_cast<std::size_t>(maximum);
  }
  RequireArray(value.at("templates"));
  for (const auto& choice : value.at("templates")) {
    CheckStop(stop);
    RequireFields(choice, {"preset_key", "ivs", "evs", "nature"});
    RequireArray(choice.at("nature"));
    if (choice.at("nature").size() != 5) throw RequestError(PBI_INVALID_INPUT_V1, "configuration nature must contain five multipliers");
    ConfigurationNature nature;
    for (std::size_t index = 0; index < nature.multipliers.size(); ++index) {
      const auto& multiplier = choice.at("nature")[index];
      if (!multiplier.is_number()) throw RequestError(PBI_INVALID_INPUT_V1, "nature multiplier must be numeric");
      nature.multipliers[index] = multiplier.get<double>();
      if (!std::isfinite(nature.multipliers[index])) throw RequestError(PBI_INVALID_INPUT_V1, "nature multiplier must be finite");
    }
    input.templates.push_back({choice.at("preset_key").get<std::string>(), {ReadSpread(choice.at("ivs")), ReadSpread(choice.at("evs")), nature}});
  }
  if (value.contains("goals")) {
    RequireArray(value.at("goals"));
    for (const auto& goal : value.at("goals")) { CheckStop(stop); input.goals.push_back(ReadGoal(goal, base.level)); }
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

Json EvaluateConfigurationTemplates(const ConfigurationTemplatesRequest& request, CancellationToken stop) {
  CheckStop(stop);
  const ConfigurationGoalEvaluator evaluator{request.policy, request.knowledge, stop};
  const auto solved = evaluator.SolveTemplates(request.input);
  CheckStop(stop);
  auto candidates = Json::array();
  for (const auto& candidate : solved.candidates) candidates.push_back({{"preset_key", candidate.preset_key}, {"stats", StatsJson(candidate.stats)},
      {"goals", GoalsJson(candidate.goals, request.generation)}, {"speed_goals", SpeedGoalsJson(candidate.speed_goals)}});
  return {{"kind", "configuration_templates"}, {"reachable", solved.Reachable()}, {"candidates", std::move(candidates)},
      {"rejected_goals", GoalsJson(solved.rejected_goals, request.generation)}, {"rejected_speed_goals", SpeedGoalsJson(solved.rejected_speed_goals)}};
}
} // namespace pbi::contract
