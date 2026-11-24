#include "pbi/configuration_goals.hpp"
#include <algorithm>
#include <array>
#include <map>
#include <set>

namespace pbi {
namespace {
/// @param value 原不透明目标/模板文本；@return 是否非空且不含Python首尾空白。
bool NormalizedText(std::string_view value) {
  if (value.empty()) return false;
  constexpr std::array<std::string_view, 29> spaces{"\t", "\n", "\v", "\f", "\r", "\x1c", "\x1d", "\x1e", "\x1f", " ",
      "\xc2\x85", "\xc2\xa0", "\xe1\x9a\x80", "\xe2\x80\x80", "\xe2\x80\x81", "\xe2\x80\x82", "\xe2\x80\x83", "\xe2\x80\x84", "\xe2\x80\x85", "\xe2\x80\x86", "\xe2\x80\x87", "\xe2\x80\x88", "\xe2\x80\x89", "\xe2\x80\x8a", "\xe2\x80\xa8", "\xe2\x80\xa9", "\xe2\x80\xaf", "\xe2\x81\x9f", "\xe3\x80\x80"};
  return std::ranges::none_of(spaces, [value](auto space) { return value.starts_with(space) || value.ends_with(space); });
}
/// @param pokemon 原静态目标字段；@param level 原统一等级；@return 复用直接伤害的快照。
DamagePokemon StaticPokemon(const ConfigurationGoalPokemon& pokemon, std::int32_t level) {
  // 原Multiscale只实现modify_battle_damage，InnerFocus只拦畏缩；
  // 此处明确复现无battle_state的旧DamageContext，而不猜测满HP或偷偷更改通用damage入口。
  const auto ability = pokemon.ability == DamageAbility::multiscale || pokemon.ability == DamageAbility::inner_focus
      ? DamageAbility::none : pokemon.ability;
  return {level, pokemon.types, pokemon.stats, ability, pokemon.item, false, std::nullopt};
}
/// @param goal 单条已准备目标；拒绝非法方向、档口和所需回合，不自动放宽约束。
void ValidateGoal(const ConfigurationDamageGoal& goal) {
  if (!NormalizedText(goal.goal_id)) throw std::invalid_argument("goal_id must be normalized and nonempty");
  if (goal.kind != ConfigurationGoalKind::attack && goal.kind != ConfigurationGoalKind::defense) throw std::invalid_argument("unknown configuration goal kind");
  if (goal.required_turns < 1 || goal.required_turns > 10) throw std::invalid_argument("required turns must be between 1 and 10");
  if (goal.roll_policy && *goal.roll_policy != ConfigurationDamageRollPolicy::minimum && *goal.roll_policy != ConfigurationDamageRollPolicy::maximum) {
    throw std::invalid_argument("unknown configuration damage roll policy");
  }
  if (goal.move.category != DamageCategory::physical && goal.move.category != DamageCategory::special) throw UnsupportedRule("configuration goals require damaging moves");
}
} // namespace

ConfigurationGoalEvaluator::ConfigurationGoalEvaluator(DamagePolicy policy, TypeChartSnapshot knowledge,
    CancellationToken cancellation)
    : policy_(std::move(policy)), knowledge_(std::move(knowledge)), cancellation_(std::move(cancellation)) {
  ValidateDamagePolicy(policy_);
}

void ConfigurationGoalEvaluator::CheckCancellation() const {
  if (cancellation_.Requested()) throw std::runtime_error("configuration goal evaluation cancelled");
}

ConfigurationDamageGoalResult ConfigurationGoalEvaluator::Evaluate(const ConfigurationGoalPokemon& subject,
    std::int32_t level, const ConfigurationDamageGoal& goal) const {
  CheckCancellation();
  ValidateGoal(goal);
  auto attacker = StaticPokemon(goal.kind == ConfigurationGoalKind::attack ? subject : goal.target, level);
  auto defender = StaticPokemon(goal.kind == ConfigurationGoalKind::attack ? goal.target : subject, level);
  auto damage = CalculateDamage({attacker, defender, goal.move, policy_, DamageWeather::none, DamageTerrain::none, {}}, knowledge_);
  const auto policy = goal.roll_policy.value_or(goal.kind == ConfigurationGoalKind::attack
      ? ConfigurationDamageRollPolicy::minimum : ConfigurationDamageRollPolicy::maximum);
  const auto selected = policy == ConfigurationDamageRollPolicy::minimum ? std::ranges::min(damage.rolls) : std::ranges::max(damage.rolls);
  const Integer total = Integer{selected} * goal.required_turns;
  const auto hp = defender.stats.hp;
  const bool satisfied = goal.kind == ConfigurationGoalKind::attack ? total >= hp : total < hp;
  Integer remaining = Integer{hp} - total;
  if (goal.kind == ConfigurationGoalKind::attack && remaining < 0) remaining = 0;
  const auto attack = goal.move.category == DamageCategory::physical ? attacker.stats.attack : attacker.stats.special_attack;
  const auto defense = goal.move.category == DamageCategory::physical ? defender.stats.defense : defender.stats.special_defense;
  return {goal.goal_id, goal.kind, satisfied, std::move(damage), selected, goal.required_turns, total, hp, std::move(remaining), attack, defense, policy};
}

std::vector<ConfigurationSpeedGoalResult> ConfigurationGoalEvaluator::EvaluateSpeedGoals(
    const BattleStats& stats, const std::vector<ConfigurationSpeedGoal>& goals) const {
  CheckCancellation();
  std::vector<ConfigurationSpeedGoalResult> results;
  results.reserve(goals.size());
  for (const auto& goal : goals) {
    CheckCancellation();
    if (!NormalizedText(goal.goal_id)) throw std::invalid_argument("speed goal_id must be normalized and nonempty");
    results.push_back({goal.goal_id, stats.speed > goal.target_speed, stats.speed, goal.target_speed,
                       static_cast<std::int64_t>(stats.speed) - goal.target_speed});
  }
  return results;
}

ConfigurationTemplateSolution ConfigurationGoalEvaluator::SolveTemplates(const ConfigurationTemplateSolveInput& input) const {
  CheckCancellation();
  if (input.goals.empty() && input.speed_goals.empty()) throw std::invalid_argument("at least one configuration goal is required");
  if (input.max_candidates < 1 || input.max_candidates > 10) throw std::invalid_argument("max_candidates must be between 1 and 10");
  std::set<std::string> goal_ids;
  for (const auto& goal : input.goals) {
    ValidateGoal(goal);
    if (!goal_ids.insert(goal.goal_id).second) throw std::invalid_argument("configuration goal IDs must be unique");
  }
  for (const auto& goal : input.speed_goals) {
    if (!NormalizedText(goal.goal_id)) throw std::invalid_argument("speed goal_id must be normalized and nonempty");
    if (!goal_ids.insert(goal.goal_id).second) throw std::invalid_argument("configuration goal IDs must be unique across damage and speed goals");
  }
  std::map<std::string, const ConfigurationStatProfile*> profiles;
  for (const auto& choice : input.templates) {
    if (!NormalizedText(choice.preset_key) || !profiles.emplace(choice.preset_key, &choice.profile).second) {
      throw std::invalid_argument("configuration template keys must be normalized and unique");
    }
  }
  constexpr std::array<std::string_view, 10> defaults{"max_hp_def_plus", "max_hp_spdef_plus", "max_hp_def", "max_hp_spdef", "max_hp",
      "max_spatk_plus", "max_atk_plus", "max_spatk_neutral", "max_atk_neutral", "no_investment"};
  std::vector<std::string> allowed = input.allowed_stat_presets;
  if (allowed.empty()) for (const auto key : defaults) allowed.emplace_back(key);
  std::vector<std::string> keys;
  std::set<std::string> seen;
  // 原显式输入保持用户顺序并去重；不因std::map或模板知识顺序重排候选。
  for (const auto& key : allowed) {
    const bool builtin = std::ranges::find(defaults, key) != defaults.end();
    if ((!builtin && !key.starts_with("preset-snapshot:")) || !profiles.contains(key)) throw UnsupportedRule("unsupported or unresolved configuration stat preset");
    if (seen.insert(key).second) keys.push_back(key);
  }
  ConfigurationTemplateSolution result;
  for (const auto& key : keys) {
    CheckCancellation();
    const auto stats = CalculateConfigurationStats(input.subject.base, input.subject.level, *profiles.at(key));
    const ConfigurationGoalPokemon subject{input.subject.types, stats, input.subject.ability, input.subject.item};
    std::vector<ConfigurationDamageGoalResult> goals;
    bool satisfied = true;
    // 原模板用例逐项完整求值，即使前一目标失败也保留该模板全部证据。
    for (const auto& goal : input.goals) {
      goals.push_back(Evaluate(subject, input.subject.level, goal));
      satisfied = satisfied && goals.back().satisfied;
    }
    auto speed_goals = EvaluateSpeedGoals(stats, input.speed_goals);
    for (const auto& goal : speed_goals) satisfied = satisfied && goal.satisfied;
    if (satisfied) {
      result.candidates.push_back({key, stats, std::move(goals), std::move(speed_goals)});
      if (result.candidates.size() >= input.max_candidates) break;
    } else if (result.rejected_goals.empty() && result.rejected_speed_goals.empty()) {
      result.rejected_goals = std::move(goals);
      result.rejected_speed_goals = std::move(speed_goals);
    }
  }
  if (result.Reachable()) {
    result.rejected_goals.clear();
    result.rejected_speed_goals.clear();
  }
  return result;
}
} // namespace pbi
