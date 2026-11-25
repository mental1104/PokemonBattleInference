#include "pbi/graph_explanation.hpp"
#include "pbi/turn.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param id 固定配置身份；@param hp 动态HP；@return 最小已验证一侧。
BattlerState Battler(std::int64_t id, std::int32_t hp) {
  const PokemonSpec spec{{id, "summary", {50, {PokemonType::normal}, {100, 100, 100, 100, 100, 100}, DamageAbility::none, DamageItem::none, false, std::nullopt},
      {MoveSpec{{id, "attack", {PokemonType::normal, DamageCategory::physical, 80}, 3, 0, 100, std::nullopt}}}}};
  return BattlerState{{spec, hp, {MoveSlotState{{id, 3, 3}}}, StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @param attacker HP；@param defender HP；@return 动态状态，不改变规则或伪造StateKey。
BattleState State(std::int32_t attacker = 100, std::int32_t defender = 100) {
  return BattleState{{Battler(1, attacker), Battler(2, defender), InferenceRules{}, 1, {}, BattlePhase::action_selection}};
}
/// @param id 原事件身份；@return 一条完整可区分随机事实。
EventSummary Events(const char* id) { return EventSummary{{{{TransitionEvent{{TransitionEventType::custom, "source", id, std::nullopt}}}, Rational{1}}}}; }
/// 与已归档原summary/full实证相同，达到边预算后不许继续把queued节点变draw。
TEST(SummaryBattleGraph, StopsTheWholeFrontierWhileFullExplorationContinues) {
  const auto root = State(), first = State(99, 100), second = State(100, 99), later = State(98, 100);
  std::size_t expanded = 0;
  const auto expand = [&](const BattleState& state) {
    ++expanded;
    if (state.Key() == root.Key()) return std::vector<BattleTransition>{BattleTransition{{Rational{1, 2}, first, Events("first"), std::nullopt}}, BattleTransition{{Rational{1, 2}, second, Events("second"), std::nullopt}}};
    if (state.Key() == first.Key()) return std::vector<BattleTransition>{BattleTransition{{Rational{1}, later, Events("later"), std::nullopt}}};
    return std::vector<BattleTransition>{};
  };
  std::vector<GraphBuildProgress> progress;
  const auto summary = BuildSummaryBattleGraph(root, expand, {std::nullopt, 2, std::nullopt}, [&](const auto& frame) { progress.push_back(frame); }, 1);
  EXPECT_EQ(expanded, 2); EXPECT_EQ(summary.graph.Statistics().terminal_counts.unknown, 2);
  EXPECT_EQ(summary.graph.Statistics().terminal_counts.draws, 0); ASSERT_EQ(summary.graph.Edges().size(), 2);
  EXPECT_EQ(summary.root_summaries.size(), 2); EXPECT_EQ(summary.graph.Nodes()[2].reason, GraphStopReason{GraphTruncation::max_edges});
  ASSERT_EQ(progress.size(), 3); EXPECT_EQ(progress.back().expanded, 2); EXPECT_EQ(progress.back().frontier, 0);
  expanded = 0;
  const auto full = BuildBattleGraph(root, expand, {std::nullopt, 2, std::nullopt});
  EXPECT_EQ(expanded, 3); EXPECT_EQ(full.Statistics().terminal_counts.draws, 1); EXPECT_EQ(full.Statistics().terminal_counts.unknown, 1);
}
/// 概率同Key精确合并而不复制边事件；root独立历史完整保留，供原精确归因消费。
TEST(SummaryBattleGraph, DiscardsExplorationMetadataAndRetainsOnlyRootHistories) {
  const auto target = State(100, 0);
  const auto summary = BuildSummaryBattleGraph(State(), [&](const BattleState&) {
    return std::vector<BattleTransition>{BattleTransition{{Rational{1, 4}, target, Events("one"), "one"}}, BattleTransition{{Rational{3, 4}, target, Events("two"), "two"}}};
  });
  ASSERT_EQ(summary.graph.Edges().size(), 1); const auto& edge = summary.graph.Edges().front();
  EXPECT_EQ(edge.probability, Rational{1}); EXPECT_FALSE(edge.source_key);
  ASSERT_EQ(edge.events.Paths().size(), 1); EXPECT_TRUE(edge.events.Paths().front().events.empty());
  EXPECT_FALSE(summary.graph.Nodes()[1].predecessor_node); EXPECT_FALSE(summary.graph.Nodes()[1].predecessor_edge);
  ASSERT_EQ(summary.root_summaries.size(), 1); ASSERT_EQ(summary.root_summaries.front().events.Paths().size(), 2);
  EXPECT_EQ(summary.root_summaries.front().events.Paths()[0].probability, (Rational{1, 4}));
  const auto explanation = ExplainRootActionPairs(summary.graph, summary.root_summaries);
  EXPECT_EQ(explanation.coverage, Rational{1}); ASSERT_EQ(explanation.buckets.size(), 1); EXPECT_EQ(explanation.buckets.front().path_count, 2);
}
/// summary保留空扩展draw、原SCC封闭环、节点预算unknown和取消，不改变原概率语义。
TEST(SummaryBattleGraph, PreservesTerminalCycleAndCancellationContracts) {
  const auto empty = BuildSummaryBattleGraph(State(), [](const BattleState&) { return std::vector<BattleTransition>{}; });
  EXPECT_EQ(empty.graph.Nodes()[0].outcome, GraphOutcome::draw);
  EXPECT_EQ(empty.graph.Nodes()[0].reason, GraphStopReason{BattleTermination::no_legal_action});
  const auto cycle = BuildSummaryBattleGraph(State(), [](const BattleState& state) { return std::vector<BattleTransition>{BattleTransition{{Rational{1}, state, Events("loop"), std::nullopt}}}; });
  EXPECT_EQ(cycle.graph.Nodes()[0].reason, GraphStopReason{BattleTermination::cycle_guard});
  const auto solved = std::get<SolvedGraph>(SolveGraph(cycle.graph.Topology())); EXPECT_EQ(solved.draw, Rational{1});
  EXPECT_TRUE(std::holds_alternative<InfiniteExpectedTurns>(solved.expected_turns));
  const auto limited = BuildSummaryBattleGraph(State(), [](const BattleState&) { return std::vector<BattleTransition>{BattleTransition{{Rational{1}, State(100, 0), Events("terminal"), std::nullopt}}}; }, {1, std::nullopt, std::nullopt});
  EXPECT_EQ(limited.graph.Nodes()[0].outcome, GraphOutcome::unknown); EXPECT_TRUE(limited.root_summaries.empty());
  CancellationSource source; source.Request(); EXPECT_THROW((void)BuildSummaryBattleGraph(State(), [](const BattleState&) { return std::vector<BattleTransition>{}; }, {}, {}, 200, source.Token()), GraphBuildCancelled);
}
} // namespace
} // namespace pbi
