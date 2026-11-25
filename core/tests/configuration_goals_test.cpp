#include "pbi/configuration_goals.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @return 只包含原静态普通属性100%所需条目的完整知识。
TypeChartSnapshot Chart() { return TypeChartSnapshot{{{PokemonType::normal, PokemonType::normal, 100}}}; }
/// @return 单一伤害档策略，便于独立检查目标边界，随机全档由Python差分覆盖。
DamagePolicy Policy() { auto policy = DamagePolicyForGeneration(9); policy.random_damage_multipliers = {1.0}; return policy; }
/// @param hp 固定HP；@return 原静态目标使用的正常能力快照。
ConfigurationGoalPokemon Pokemon(std::int32_t hp) { return {{PokemonType::normal}, {hp, 100, 100, 100, 100, 100}}; }
/// @param kind 原攻/防方向；@return 完整固定威力两次攻击目标。
ConfigurationDamageGoal Goal(ConfigurationGoalKind kind) {
  return {"goal-1", kind, Pokemon(80), {PokemonType::normal, DamageCategory::physical, 80}, 2, std::nullopt};
}
/// 攻击允许刚好击倒，防守要求严格存活；失败防守保留负剩余HP，不被错误clamp。
TEST(ConfigurationGoals, PreservesAttackAndDefenseThresholdSemantics) {
  ConfigurationGoalEvaluator evaluator{Policy(), Chart()};
  const auto attack = evaluator.Evaluate(Pokemon(100), 50, Goal(ConfigurationGoalKind::attack));
  EXPECT_EQ(attack.selected_damage, 55);
  EXPECT_TRUE(attack.satisfied);
  EXPECT_EQ(attack.remaining_hp, 0);
  const auto defense = evaluator.Evaluate(Pokemon(100), 50, Goal(ConfigurationGoalKind::defense));
  EXPECT_FALSE(defense.satisfied);
  EXPECT_EQ(defense.remaining_hp, -10);
  auto exact = Goal(ConfigurationGoalKind::attack);
  exact.target.stats.hp = 110;
  EXPECT_TRUE(evaluator.Evaluate(Pokemon(100), 50, exact).satisfied);
  EXPECT_FALSE(evaluator.Evaluate(Pokemon(110), 50, Goal(ConfigurationGoalKind::defense)).satisfied);
}
/// 原静态上下文没有动态多重鳞片/精神力钩子；真实回合与已有damage入口不改。
TEST(ConfigurationGoals, UsesExplicitReferenceStaticAbilityContext) {
  ConfigurationGoalEvaluator evaluator{Policy(), Chart()};
  auto goal = Goal(ConfigurationGoalKind::attack);
  goal.target.ability = DamageAbility::multiscale;
  auto subject = Pokemon(100);
  subject.ability = DamageAbility::inner_focus;
  EXPECT_EQ(evaluator.Evaluate(subject, 50, goal).selected_damage, 55);
}
/// 用户模板顺序去重且max_candidates真实提前停止；无解只保留第一失败模板证据。
TEST(ConfigurationGoals, SearchesTemplatesInOriginalOrderAndKeepsRejectedEvidence) {
  ConfigurationTemplateSolveInput input;
  input.subject = {{100, 100, 100, 100, 100, 100}, {PokemonType::normal}};
  input.templates = {{"max_hp", {}}, {"no_investment", {}}};
  input.allowed_stat_presets = {"max_hp", "max_hp", "no_investment"};
  auto goal = Goal(ConfigurationGoalKind::attack);
  goal.target.stats.hp = 1;
  input.goals = {goal};
  input.max_candidates = 1;
  // 第二模板故意无效；首个成功达到max_candidates后必须停止，不能多算后再截列表。
  input.templates[1].profile.evs.hp = 253;
  ConfigurationGoalEvaluator evaluator{Policy(), Chart()};
  const auto solved = evaluator.SolveTemplates(input);
  ASSERT_EQ(solved.candidates.size(), 1);
  EXPECT_EQ(solved.candidates[0].preset_key, "max_hp");
  EXPECT_TRUE(solved.rejected_goals.empty());
  input.templates[1].profile.evs.hp = 0;
  input.goals[0].target.stats.hp = 100000;
  ConfigurationGoalEvaluator impossible{Policy(), Chart()};
  const auto rejected = impossible.SolveTemplates(input);
  EXPECT_FALSE(rejected.Reachable());
  ASSERT_EQ(rejected.rejected_goals.size(), 1);
}
/// 原十模板默认优先级属于搜索语义，不依赖传入知识的排序。
TEST(ConfigurationGoals, PreservesDefaultTemplatePriority) {
  ConfigurationTemplateSolveInput input;
  input.subject = {{100, 100, 100, 100, 100, 100}, {PokemonType::normal}};
  for (const auto key : {"no_investment", "max_hp_def_plus", "max_hp_spdef_plus", "max_hp_def", "max_hp_spdef", "max_hp", "max_spatk_plus", "max_atk_plus", "max_spatk_neutral", "max_atk_neutral"}) {
    input.templates.push_back({key, {}});
  }
  auto goal = Goal(ConfigurationGoalKind::attack);
  goal.target.stats.hp = 1;
  input.goals = {goal};
  input.max_candidates = 2;
  ConfigurationGoalEvaluator evaluator{Policy(), Chart()};
  const auto result = evaluator.SolveTemplates(input);
  ASSERT_EQ(result.candidates.size(), 2);
  EXPECT_EQ(result.candidates[0].preset_key, "max_hp_def_plus");
  EXPECT_EQ(result.candidates[1].preset_key, "max_hp_spdef_plus");
}
/// 实际HTTP的WithSpeed链允许纯速度目标；同速失败，首失败证据不能被后续模板覆盖。
TEST(ConfigurationGoals, SupportsSpeedOnlyAndMixedGoalsWithStrictComparison) {
  ConfigurationTemplateSolveInput input;
  input.subject = {{100, 100, 100, 100, 100, 100}, {PokemonType::normal}};
  input.templates = {{"no_investment", {}}, {"max_hp", {}}};
  input.templates[1].profile.evs.speed = 252;
  input.allowed_stat_presets = {"no_investment", "max_hp"};
  input.speed_goals = {{"speed", 200}};
  ConfigurationGoalEvaluator evaluator{Policy(), Chart()};
  const auto failed = evaluator.SolveTemplates(input);
  EXPECT_FALSE(failed.Reachable());
  EXPECT_TRUE(failed.rejected_goals.empty());
  ASSERT_EQ(failed.rejected_speed_goals.size(), 1);
  EXPECT_EQ(failed.rejected_speed_goals[0].subject_speed, 120);
  input.speed_goals[0].target_speed = 120;
  const auto solved = evaluator.SolveTemplates(input);
  ASSERT_EQ(solved.candidates.size(), 1);
  EXPECT_EQ(solved.candidates[0].preset_key, "max_hp");
  EXPECT_TRUE(solved.candidates[0].speed_goals[0].satisfied);
  auto duplicate = Goal(ConfigurationGoalKind::attack);
  duplicate.goal_id = "speed";
  input.goals = {duplicate};
  EXPECT_THROW((void)evaluator.SolveTemplates(input), std::invalid_argument);
}
/// 取消/空目标/重复ID与状态招式明确失败，不回传局部候选或新增原需求外预算。
TEST(ConfigurationGoals, HonorsCancellationAndInputBoundaries) {
  CancellationSource source;
  EXPECT_TRUE(source.Request());
  ConfigurationGoalEvaluator cancelled{Policy(), Chart(), source.Token()};
  EXPECT_THROW((void)cancelled.Evaluate(Pokemon(100), 50, Goal(ConfigurationGoalKind::attack)), std::runtime_error);
  ConfigurationGoalEvaluator evaluator{Policy(), Chart()};
  EXPECT_THROW((void)evaluator.SolveTemplates({}), std::invalid_argument);
  ConfigurationTemplateSolveInput duplicate;
  duplicate.goals = {Goal(ConfigurationGoalKind::attack), Goal(ConfigurationGoalKind::attack)};
  EXPECT_THROW((void)evaluator.SolveTemplates(duplicate), std::invalid_argument);
  auto status = Goal(ConfigurationGoalKind::attack);
  status.move.category = DamageCategory::status;
  EXPECT_THROW((void)evaluator.Evaluate(Pokemon(100), 50, status), UnsupportedRule);
}
} // namespace
} // namespace pbi
