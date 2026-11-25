#include "pbi/graph_explanation.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param id 已验证配置ID；@param hp 动态HP；@return 最小合法一侧，不在fixture重复能力/伤害公式。
BattlerState Battler(std::int64_t id, std::int32_t hp) {
  const PokemonSpec spec{{id, "explanation", {50, {PokemonType::normal}, {100, 100, 100, 100, 100, 100}, DamageAbility::none, DamageItem::none, false, std::nullopt},
      {MoveSpec{{id, "attack", {PokemonType::normal, DamageCategory::physical, 80}, 3, 0, 100, std::nullopt}}}}};
  return BattlerState{{spec, hp, {MoveSlotState{{id, 3, 3}}}, StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @param attacker 动态HP；@param defender 动态HP；@return 已验证根/三种实际终局状态。
BattleState State(std::int32_t attacker = 100, std::int32_t defender = 100) {
  return BattleState{{Battler(1, attacker), Battler(2, defender), InferenceRules{}, 1, {}, BattlePhase::action_selection}};
}
/// @param id 真正使用的招式ID；@return 原selected/used不同事实，归因必须选择used而非winning的selected语义。
std::vector<PathEvent> History(std::int64_t id) {
  return {BattleEvent{{BattleEventKind::move_selected, 1, BattleSide::attacker, std::nullopt, 99}},
      BattleEvent{{BattleEventKind::move_used, 1, BattleSide::attacker, std::nullopt, id}},
      BattleEvent{{BattleEventKind::move_used, 1, BattleSide::defender, std::nullopt, 101}}};
}
/// @return 真正通过正式builder创建的分支图，非公开script ABI或伪造私有BattleGraph。
BattleGraph Graph() {
  return BuildBattleGraph(State(), [](const BattleState&) {
    return std::vector<BattleTransition>{
      BattleTransition{{Rational{1, 2}, State(100, 0), EventSummary{{{History(1), Rational{1, 4}}, {History(2), Rational{3, 4}}}}, std::nullopt}},
      BattleTransition{{Rational{1, 4}, State(0, 100), EventSummary{{{History(2), Rational{1}}}}, std::nullopt}},
      BattleTransition{{Rational{1, 4}, State(0, 0), EventSummary{}, std::nullopt}}};
  });
}
/// 唯一全节点求解器与旧根入口同源，保留精确概率、期望与完整不可用类别。
TEST(GraphExplanation, ExposesAllNodeAbsorptionFromTheSameSolver) {
  const auto graph = Graph();
  const auto values = SolveGraphNodes(graph.Topology());
  ASSERT_TRUE(std::holds_alternative<std::vector<GraphNodeAbsorption>>(values));
  const auto& nodes = std::get<std::vector<GraphNodeAbsorption>>(values);
  ASSERT_EQ(nodes.size(), 4); EXPECT_EQ(nodes[0].attacker_win, (Rational{1, 2}));
  EXPECT_EQ(nodes[1].attacker_win, Rational{1}); EXPECT_EQ(nodes[2].defender_win, Rational{1}); EXPECT_EQ(nodes[3].draw, Rational{1});
  EXPECT_EQ(nodes[0].expected_steps_to_boundary, Rational{1});
  const auto reverse = std::get<SolvedGraph>(SolveGraph(graph.Topology(), BattleSide::defender));
  EXPECT_EQ(reverse.win, nodes[0].defender_win); EXPECT_EQ(reverse.loss, nodes[0].attacker_win);
}
/// root正式边乘替代历史条件权重及后继全图吸收值，Top-K不能重归一覆盖或丢弃omitted统计。
TEST(GraphExplanation, UsesActualMoveUsedAndFullConditionalMass) {
  const auto explanation = ExplainRootActionPairs(Graph(), {}, 1);
  EXPECT_EQ(explanation.coverage, Rational{1}); EXPECT_EQ(explanation.root_values.attacker_win, (Rational{1, 2}));
  ASSERT_EQ(explanation.buckets.size(), 1); EXPECT_EQ(explanation.omitted_bucket_count, 2);
  const auto& bucket = explanation.buckets.front(); EXPECT_EQ(bucket.attacker_move_id, 2); EXPECT_EQ(bucket.defender_move_id, 101);
  EXPECT_EQ(bucket.probability, (Rational{5, 8})); EXPECT_EQ(bucket.attacker_win_contribution, (Rational{3, 8}));
  EXPECT_EQ(bucket.defender_win_contribution, (Rational{1, 4})); EXPECT_EQ(bucket.conditional_attacker_win, (Rational{3, 5}));
  EXPECT_EQ(bucket.conditional_defender_win, (Rational{2, 5})); EXPECT_EQ(bucket.path_count, 2);
  ASSERT_TRUE(bucket.representative_target_node_id); EXPECT_EQ(bucket.representative_target_node_id->value, 1);
}
/// 原summary根快照覆盖当前边元数据；根已终局、非法预算、未知截断和取消均保持明确语义。
TEST(GraphExplanation, PreservesSummaryOverridesAndUnavailableBoundaries) {
  const auto graph = Graph();
  const std::vector<RootActionEventSummary> overrides{{{1}, EventSummary{{{History(3), Rational{1}}}}}};
  const auto summary = ExplainRootActionPairs(graph, overrides);
  EXPECT_EQ(summary.buckets.front().attacker_move_id, 3); EXPECT_EQ(summary.buckets.front().probability, (Rational{1, 2}));
  const auto terminal = BuildBattleGraph(State(100, 0), [](const BattleState&) { return std::vector<BattleTransition>{}; });
  const auto empty = ExplainRootActionPairs(terminal); EXPECT_EQ(empty.coverage, Rational{0}); EXPECT_TRUE(empty.buckets.empty());
  EXPECT_EQ(empty.root_values.attacker_win, Rational{1});
  EXPECT_THROW((void)ExplainRootActionPairs(graph, {}, 0), std::invalid_argument);
  const auto limited = BuildBattleGraph(State(), [](const BattleState&) { return std::vector<BattleTransition>{BattleTransition{{Rational{1}, State(100, 0), EventSummary{}, std::nullopt}}}; }, {1, std::nullopt, std::nullopt});
  EXPECT_THROW((void)ExplainRootActionPairs(limited), std::invalid_argument);
  CancellationSource source; source.Request(); EXPECT_THROW((void)ExplainRootActionPairs(graph, {}, 12, source.Token()), std::runtime_error);
}
} // namespace
} // namespace pbi
