#include "pbi/transitions.hpp"
#include "pbi/battle_graph.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param id 配置 ID；@param hp 当前 HP；@return 单招式、无特性道具的只读测试战斗方。
BattlerState GraphBattler(std::int64_t id, std::int32_t hp) {
  const PokemonSpec spec{{id, "test", {50, {PokemonType::normal}, {100, 100, 100, 100, 100, 100},
      DamageAbility::none, DamageItem::none, false, std::nullopt},
      {MoveSpec{{1, "attack", {PokemonType::normal, DamageCategory::physical, 40}, 5, 0, 100, std::nullopt}}}}};
  return BattlerState{{spec, hp, {MoveSlotState{{1, 5, 5}}}, StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @param hp 防守方当前 HP；@return 两侧状态合法的初始图节点。
BattleState GraphState(std::int32_t hp = 3) {
  return BattleState{{GraphBattler(1, 100), GraphBattler(2, hp), InferenceRules{}, 1, {}, BattlePhase::action_selection}};
}
/// @param outcome 随机结果标识；@return 单一概率一的随机事件路径。
EventSummary Summary(std::string outcome) {
  return EventSummary{{{{TransitionEvent{{TransitionEventType::damage_roll, "roll", std::move(outcome), std::nullopt}}}, Rational{1}}}};
}
/// @param state 父状态；@return 确定扣一 HP 并推进回合的实际不可变状态分布，测试只验证构图合同。
std::vector<BattleTransition> Decrement(const BattleState& state) {
  const auto& defender = state.View().defender;
  return {BattleTransition{{Rational{1}, state.WithBattler(BattleSide::defender, defender.WithCurrentHp(defender.View().current_hp - 1)).NextTurn(), EventSummary{}, "decrement"}}};
}
} // namespace

/// 不等概率历史归并必须按绝对概率重算条件权重，不能把两条历史变成等概率。
TEST(Transitions, ExactConditionalPathsAndStableMerge) {
  const auto state = GraphState();
  const std::vector<BattleTransition> inputs{
      BattleTransition{{Rational{1, 3}, state, Summary("a"), "source-a"}},
      BattleTransition{{Rational{2, 3}, state.NextTurn(), Summary("b"), "source-b"}}};
  const auto merged = MergeEquivalentTransitions(inputs);
  ASSERT_EQ(merged.size(), 1); EXPECT_EQ(merged.front().View().probability, Rational{1});
  EXPECT_FALSE(merged.front().View().source_key);
  const auto paths = merged.front().View().events.Paths();
  ASSERT_EQ(paths.size(), 2); EXPECT_EQ(paths[0].probability, (Rational{1, 3})); EXPECT_EQ(paths[1].probability, (Rational{2, 3}));
  EXPECT_EQ(std::get<TransitionEvent>(paths[0].events[0]).View().outcome_id, "a");
  EXPECT_EQ(inputs[0].View().events.Paths()[0].probability, Rational{1});
  const auto duplicated = Summary("a").MergeAlternatives(Summary("a"), Rational{1, 7}, Rational{5, 7});
  ASSERT_EQ(duplicated.Paths().size(), 1); EXPECT_EQ(duplicated.Paths()[0].probability, Rational{1});
  const auto combined = merged.front().View().events.Concatenate(Summary("child"));
  ASSERT_EQ(combined.Paths()[0].events.size(), 2); EXPECT_EQ(combined.Paths()[0].probability, (Rational{1, 3}));
}

/// 条件分支概率与事件历史按顺序相乘，验证失败不留下半套可用结果。
TEST(Transitions, BranchingNormalizationAndFailures) {
  const auto state = GraphState();
  const std::vector<BattleTransition> parents{BattleTransition{{Rational{1}, state, Summary("parent"), "parent"}}};
  const auto branched = BranchTransitions(parents, [](const BattleState& parent) {
    return std::vector<BattleTransition>{BattleTransition{{Rational{1, 4}, parent, Summary("yes"), "child"}},
        BattleTransition{{Rational{3, 4}, parent, Summary("no"), "child"}}};
  });
  ASSERT_EQ(branched.size(), 1);
  EXPECT_EQ(branched[0].View().source_key, "child");
  ASSERT_EQ(branched[0].View().events.Paths().size(), 2);
  EXPECT_EQ(branched[0].View().events.Paths()[1].probability, (Rational{3, 4}));
  EXPECT_EQ(std::get<TransitionEvent>(branched[0].View().events.Paths()[0].events[0]).View().outcome_id, "parent");
  const std::vector<BattleTransition> weights{BattleTransition{{Rational{1, 4}, state, Summary("a"), std::nullopt}},
      BattleTransition{{Rational{1, 8}, state, Summary("b"), std::nullopt}}};
  const auto normalized = NormalizeTransitionWeights(weights);
  EXPECT_EQ(normalized[0].View().events.Paths()[0].probability, (Rational{2, 3}));
  EXPECT_THROW(ValidateTransitions(weights), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(MergeEquivalentTransitions({})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(EventSummary(std::vector<WeightedEventPath>{})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(TransitionEvent(TransitionEventData{TransitionEventType::custom, "\xe3\x80\x80", "value", std::nullopt})), std::invalid_argument);
}

/// 业务事件保留明确字段与原稳定身份，任意精度差值和空值语义不丢失。
TEST(Events, StructuredFactsAndExactIdentity) {
  const Integer previous{std::string(200, '9')};
  const BattleEvent event{{BattleEventKind::hp_changed, 2, BattleSide::attacker, BattleSide::defender, 1, "move", std::nullopt, previous, Integer{0}}};
  ASSERT_TRUE(event.View().value); EXPECT_EQ(*event.View().value, -previous);
  ASSERT_TRUE(event.Delta()); EXPECT_EQ(*event.Delta(), -previous);
  const auto identity = event.Identity();
  EXPECT_EQ(identity.View().type, TransitionEventType::custom);
  EXPECT_EQ(identity.View().outcome_id, "hp-changed");
  EXPECT_TRUE(identity.View().event_id.starts_with("turn-2:hp-changed:attacker:defender:1:move:"));
  EXPECT_EQ(identity.View().numeric_value, event.View().value);
  const EventSummary summary{{{{event}, Rational{1, 2}}, {{identity}, Rational{1, 2}}}};
  EXPECT_EQ(summary.Paths().size(), 2); // 业务事件与普通 custom 事件不因身份相同而擦除类型。
  EXPECT_THROW(static_cast<void>(BattleEvent(BattleEventData{BattleEventKind::hit, 0, {}, {}, {}, {}, {}, {}, {}})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(BattleEvent(BattleEventData{BattleEventKind::hp_changed, 1, {}, {}, {}, {}, {}, Integer{1}, {}})), std::invalid_argument);
}

/// 实际 BFS 保留代表路径与回合计数，终局不再调用扩展器。
TEST(BattleGraph, ActualImmutableExpansionAndRepresentativePath) {
  const auto initial = GraphState();
  std::vector<GraphBuildProgress> progress;
  const auto graph = BuildBattleGraph(initial, Decrement, {}, [&](const GraphBuildProgress& frame) { progress.push_back(frame); }, 1);
  ASSERT_EQ(graph.Nodes().size(), 4); ASSERT_EQ(graph.Edges().size(), 3);
  EXPECT_EQ(graph.Statistics().terminal_counts.attacker_wins, 1);
  EXPECT_EQ(graph.Statistics().max_turn_number, 4);
  EXPECT_EQ(graph.RepresentativePath({3}), (std::vector<GraphNodeId>{{0}, {1}, {2}, {3}}));
  EXPECT_EQ(graph.Nodes()[3].predecessor_edge, (GraphEdgeId{2}));
  EXPECT_EQ(initial.View().defender.View().current_hp, 3);
  const auto solved = std::get<SolvedGraph>(SolveGraph(graph.Topology()));
  EXPECT_EQ(solved.win, Rational{1}); EXPECT_EQ(std::get<FiniteExpectedTurns>(solved.expected_turns).value, Rational{3});
  ASSERT_FALSE(progress.empty()); EXPECT_EQ(progress.front().expanded, 0); EXPECT_EQ(progress.back().expanded, 3);
  EXPECT_EQ(progress.back().phase, GraphBuildPhase::built);
}

/// 预算以完整节点为单位提交；未展开节点明确 unknown，回合上限不是平局。
TEST(BattleGraph, AtomicBudgetsAndUnknownTruncation) {
  const auto initial = GraphState();
  const auto limited = BuildBattleGraph(initial, Decrement, GraphLimits{1, {}, {}});
  ASSERT_EQ(limited.Nodes().size(), 1); EXPECT_TRUE(limited.Edges().empty());
  EXPECT_EQ(limited.Nodes()[0].outcome, GraphOutcome::unknown);
  EXPECT_EQ(limited.Truncations().front(), GraphTruncation::max_nodes);
  EXPECT_EQ(std::get<UnavailableGraph>(SolveGraph(limited.Topology())).status, GraphSolveStatus::incomplete_graph);
  const auto turn_limited = BuildBattleGraph(initial, Decrement, GraphLimits{{}, {}, 1});
  ASSERT_EQ(turn_limited.Nodes().size(), 2); EXPECT_EQ(turn_limited.Edges().size(), 1);
  EXPECT_EQ(turn_limited.Nodes()[1].outcome, GraphOutcome::unknown);
  EXPECT_EQ(turn_limited.Truncations().front(), GraphTruncation::max_turns);
  const auto branching = [](const BattleState& state) {
    return std::vector<BattleTransition>{BattleTransition{{Rational{1, 2}, state.NextTurn(), EventSummary{}, std::nullopt}},
        BattleTransition{{Rational{1, 2}, state.WithBattler(BattleSide::defender, state.View().defender.WithCurrentHp(0)), EventSummary{}, std::nullopt}}};
  };
  const auto edge_limited = BuildBattleGraph(initial, branching, GraphLimits{{}, 1, {}});
  EXPECT_TRUE(edge_limited.Edges().empty()); EXPECT_EQ(edge_limited.Truncations().front(), GraphTruncation::max_edges);
}

/// 语义相同的后继形成真实自环；取消在已报告一次实际展开后传入，不返回部分图。
TEST(BattleGraph, CyclesEmptyActionsAndRunningCancellation) {
  const auto initial = GraphState();
  const auto cyclic = BuildBattleGraph(initial, [](const BattleState& state) {
    return std::vector<BattleTransition>{BattleTransition{{Rational{1}, state.NextTurn(), EventSummary{}, "repeat"}}};
  });
  ASSERT_EQ(cyclic.Nodes().size(), 1); ASSERT_EQ(cyclic.Edges().size(), 1);
  EXPECT_EQ(cyclic.Nodes()[0].outcome, GraphOutcome::draw); EXPECT_EQ(cyclic.Statistics().closed_cycles, 1);
  EXPECT_TRUE(std::holds_alternative<InfiniteExpectedTurns>(std::get<SolvedGraph>(SolveGraph(cyclic.Topology())).expected_turns));
  const auto no_action = BuildBattleGraph(initial, [](const BattleState&) { return std::vector<BattleTransition>{}; });
  EXPECT_EQ(no_action.Nodes()[0].outcome, GraphOutcome::draw); EXPECT_TRUE(no_action.Edges().empty());
  pbi::CancellationSource cancellation;
  EXPECT_THROW(static_cast<void>(BuildBattleGraph(initial, Decrement, {}, [&](const GraphBuildProgress& frame) {
    if (frame.expanded == 1) cancellation.Request();
  }, 1, cancellation.Token())), GraphBuildCancelled);
}
} // namespace pbi
