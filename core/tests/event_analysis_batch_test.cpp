#include "pbi/event_analysis_batch.hpp"
#include "pbi/turn.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param id 配置身份；@param speed 行动顺序；@return 只有一个可用真实伤害招式的完整战斗侧。
BattlerState Battler(std::int64_t id, std::int32_t speed) {
  const PokemonSpec spec{{id, "event-fixture", {50, {PokemonType::normal}, {100, 100, 100, 100, 100, speed}, DamageAbility::none, DamageItem::none, false, std::nullopt},
      {MoveSpec{{1, "attack", {PokemonType::normal, DamageCategory::physical, 200}, 1, 0, 100, std::nullopt}}}}};
  return BattlerState{{spec, 1, {MoveSlotState{{1, 1, 1, false, false, id * 1000 + 1}}}, StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @return 匹配真实攻击方damage业务事实的原完整查询。
EventQuery Query() {
  EventQuery query;
  query.predicate.battle_event_kinds = {BattleEventKind::damage};
  query.predicate.side = BattleSide::attacker;
  query.predicate.side_role = EventSideRole::actor;
  query.distribution_count_limit = 2;
  query.distribution_turn_limit = 2;
  return query;
}
/// @param request 原独立revision/覆盖；@return 每次真正重跑标准回合、BFS、精确图并带独立运行ID。
EventAnalysisArtifact InferArtifact(const EventInferenceRequest& request) {
  auto rules = InferenceRules{}.View();
  rules.damage_policy.random_damage_multipliers = {1};
  auto initial = BattleState{{Battler(1, 100), Battler(2, 90), InferenceRules{std::move(rules)}, 1, {}, BattlePhase::action_selection}};
  if (!request.rule_overrides.empty()) initial = initial.WithBattler(BattleSide::attacker, initial.View().attacker.WithCurrentHp(0));
  const auto computation = InferFixedBattle(std::move(initial), TypeChartSnapshot{{{PokemonType::normal, PokemonType::normal, 100}}});
  return {request.calculation_revision, "run-" + request.calculation_revision, ProjectEventAnalysisGraph(computation.graph)};
}
/// 反事实端口必须真实执行两次独立固定战斗，事件和胜率差值由两套真实图推导。
TEST(EventAnalysisBatch, RebuildsTwoActualFixedBattlesForCounterfactual) {
  std::size_t runs = 0;
  const CounterfactualEventRequest request{"baseline", "override", {{"attacker-hp", "0"}}, Query()};
  const auto result = AnalyzeCounterfactualEvents(request, [&](const EventInferenceRequest& call) {
    ++runs;
    return InferArtifact(call);
  });
  EXPECT_EQ(runs, 2);
  EXPECT_EQ(result.baseline.baseline_win, Rational{1});
  EXPECT_EQ(result.baseline.event_probability, Rational{1});
  EXPECT_EQ(result.counterfactual.baseline_win, Rational{0});
  EXPECT_EQ(result.win_probability_delta, Rational{-1});
  EXPECT_EQ(result.event_probability_delta, Rational{-1});
  EXPECT_EQ(result.event_win_joint_probability_delta, Rational{-1});
  EXPECT_TRUE(result.independent_revisions_verified);
  EXPECT_EQ(result.cost.inference_runs, 2);
  EXPECT_EQ(result.cost.graph_builds, 2);
}
/// 失败/截断配置保留原完整分母，概率和可能配置权重是不同指标。
TEST(EventAnalysisBatch, PreservesOriginalConfigurationWeightsAndCoverage) {
  auto first = AnalyzeBattleEvents(InferArtifact({"first", {}}), Query());
  auto second = AnalyzeBattleEvents(InferArtifact({"second", {{"attacker-hp", "0"}}}), Query());
  const auto result = AggregateConfigurationEvents({{"first", Rational{1, 4}, first}, {"second", Rational{1, 2}, second}}, Integer{3}, Rational{1, 4});
  EXPECT_EQ(result.coverage.analyzed_configuration_count, 2);
  EXPECT_EQ(result.coverage.event_possible_configuration_count, 1);
  EXPECT_EQ(result.coverage.analyzed_configuration_weight, (Rational{3, 4}));
  EXPECT_EQ(result.coverage.event_possible_configuration_weight, (Rational{1, 4}));
  EXPECT_EQ(result.event_probability, (Rational{1, 4}));
  EXPECT_EQ(result.event_win_joint_probability, (Rational{1, 4}));
  EXPECT_EQ(result.groups[1].configuration_id, "second");
  const auto empty = AggregateConfigurationEvents({}, Integer{10}, Rational{1});
  EXPECT_EQ(empty.coverage.analyzed_configuration_count, 0);
  EXPECT_EQ(empty.event_probability, Rational{0});
}
/// 重复身份、缺失原分母权重和非独立运行均整体拒绝。
TEST(EventAnalysisBatch, RejectsInvalidAggregationAndSharedRunIdentity) {
  const auto analysis = AnalyzeBattleEvents(InferArtifact({"first", {}}), Query());
  EXPECT_THROW((void)AggregateConfigurationEvents({{"same", Rational{1, 2}, analysis}, {"same", Rational{1, 2}, analysis}}, Integer{2}), std::invalid_argument);
  EXPECT_THROW((void)AggregateConfigurationEvents({{"one", Rational{1, 2}, analysis}}, Integer{2}), std::invalid_argument);
  const CounterfactualEventRequest request{"first", "second", {{"attacker-hp", "0"}}, Query()};
  EXPECT_THROW((void)AnalyzeCounterfactualEvents(request, [](const EventInferenceRequest& call) {
    auto artifact = InferArtifact(call);
    artifact.inference_run_id = "same-run";
    return artifact;
  }), std::invalid_argument);
}
} // namespace
} // namespace pbi
