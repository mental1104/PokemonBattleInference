#include "pbi/configuration_goals.hpp"
#include "../src/configuration_goals_contract.hpp"
#include <iostream>

namespace {
using Json = nlohmann::json;
/// @param value 完整正式伤害快照；@return 原目标上下文实际消费的字段。
pbi::ConfigurationGoalPokemon Pokemon(const Json& value) {
  const auto pokemon = pbi::contract::ReadPokemon(value);
  return {pokemon.types, pokemon.stats, pokemon.ability, pokemon.item};
}
/// @param value 完整目标；@return 只做类型转换，不计算伤害或选择候选。
pbi::ConfigurationDamageGoal Goal(const Json& value) {
  pbi::ConfigurationGoalKind kind;
  if (value.at("kind") == "attack") kind = pbi::ConfigurationGoalKind::attack;
  else if (value.at("kind") == "defense") kind = pbi::ConfigurationGoalKind::defense;
  else throw std::invalid_argument("unknown configuration goal kind");
  std::optional<pbi::ConfigurationDamageRollPolicy> policy;
  if (value.at("roll_policy") == "min") policy = pbi::ConfigurationDamageRollPolicy::minimum;
  else if (value.at("roll_policy") == "max") policy = pbi::ConfigurationDamageRollPolicy::maximum;
  else if (!value.at("roll_policy").is_null()) throw std::invalid_argument("unknown configuration goal roll policy");
  const auto& move = value.at("move");
  const auto category = pbi::contract::ReadEnum<pbi::DamageCategory>(move.at("category"), std::array<std::string_view, 3>{"physical", "special", "status"});
  return {value.at("goal_id").get<std::string>(), kind, Pokemon(value.at("target")),
      {static_cast<pbi::PokemonType>(pbi::contract::ReadInt32(move.at("type"))), category, pbi::contract::ReadInt32(move.at("power"))},
      pbi::contract::ReadInt32(value.at("required_turns")), policy};
}
/// @param goals 真实Core逐项目标结果；@param generation 原规则代际；@return 完整目标/伤害证据。
Json Goals(const std::vector<pbi::ConfigurationDamageGoalResult>& goals, std::int32_t generation) {
  auto output = Json::array();
  for (const auto& value : goals) output.push_back({{"goal_id", value.goal_id}, {"kind", value.kind == pbi::ConfigurationGoalKind::attack ? "attack" : "defense"},
      {"subject_role", value.kind == pbi::ConfigurationGoalKind::attack ? "attacker" : "defender"},
      {"satisfied", value.satisfied}, {"damage", pbi::contract::DamageJson(value.damage, generation)}, {"selected_damage", value.selected_damage},
      {"repetitions", value.repetitions}, {"total_damage", value.total_damage.str()}, {"hp_threshold", value.hp_threshold},
      {"remaining_hp", value.remaining_hp.str()}, {"effective_attack", value.effective_attack}, {"effective_defense", value.effective_defense},
      {"roll_policy", value.roll_policy == pbi::ConfigurationDamageRollPolicy::minimum ? "min" : "max"}});
  return output;
}
/// @param request 原准备数据；@return 真正目标求值或模板搜索，不运行Python。
Json Run(const Json& request) {
  const auto generation = pbi::contract::ReadInt32(request.at("generation_id"));
  pbi::ConfigurationGoalEvaluator evaluator{pbi::contract::ReadPolicy(request.at("policy"), pbi::DamagePolicyForGeneration(generation)),
      pbi::contract::ReadTypeChart(request.at("type_chart"))};
  if (request.at("mode") == "evaluate") {
    const auto pokemon = pbi::contract::ReadPokemon(request.at("subject"));
    return {{"goals", Goals({evaluator.Evaluate(Pokemon(request.at("subject")), pokemon.level, Goal(request.at("goal")))}, generation)}};
  }
  if (request.at("mode") != "templates") throw std::invalid_argument("unknown configuration goal vector mode");
  auto operation = request;
  operation.erase("mode");
  operation["kind"] = "configuration_templates";
  return pbi::contract::EvaluateConfigurationTemplates(pbi::contract::ReadConfigurationTemplatesRequest(operation, {}), {});
}
} // namespace
/// 无参数；逐行执行真实原目标/模板算法，错误整体返回，不生成部分候选。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << Run(Json::parse(line)).dump() << '\n'; }
    catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
