#include "pbi/winning_paths.hpp"
#include "pbi/turn.hpp"
#include <gtest/gtest.h>
#include <future>
#include <thread>

namespace pbi {
namespace {
/// @param id 稳定配置；@return 最小合法机械UNKNOWN，避免测试另算伤害或状态公式。
BattlerState Battler(std::int64_t id) {
  const PokemonSpec spec{{id, "winning-fixture", {50, {PokemonType::normal}, {100, 100, 100, 100, 100, 100}, DamageAbility::none, DamageItem::none, false, std::nullopt},
      {MoveSpec{{1, "attack", {PokemonType::normal, DamageCategory::physical, 80}, 3, 0, 100, std::nullopt}}}}};
  return BattlerState{{spec, 100, {MoveSlotState{{1, 3, 3}}}, StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @param turn 原实际回合；@return 不依赖运行时知识/数据库的已验证完整状态。
BattleState State(std::int64_t turn = 1) { return BattleState{{Battler(1), Battler(2), InferenceRules{}, turn, {}, BattlePhase::action_selection}}; }
/// @param move 原行动事实；@param damage 替代随机结果；@return 两侧行动与伤害，供归并而非模拟执行。
EventSummary Events(std::int64_t move, Integer damage) {
  return EventSummary{{{{BattleEvent{{BattleEventKind::move_selected, 1, BattleSide::attacker, std::nullopt, move, "policy"}},
      BattleEvent{{BattleEventKind::move_selected, 1, BattleSide::defender, std::nullopt, 1, "policy"}},
      BattleEvent{{BattleEventKind::damage, 1, BattleSide::attacker, BattleSide::defender, move, "damage", damage}}}, Rational{1}}}};
}
/// 原多随机边同一行动归并；代表路径保留最大原walk，页概率不重归一，cursor偏移任意精度。
TEST(WinningPaths, GroupsRandomWalksKeepsRepresentativeAndPageProbability) {
  WinningPathGraph graph{{{{0}, State(), GraphOutcome::non_terminal, std::nullopt},
      {{1}, State(2), GraphOutcome::attacker_win, BattleTermination::knockout},
      {{2}, State(2), GraphOutcome::attacker_win, BattleTermination::knockout},
      {{3}, State(2), GraphOutcome::attacker_win, BattleTermination::knockout}},
      {{{0}, {0}, {1}, Rational{1, 8}, Events(1, 10), std::nullopt},
       {{1}, {0}, {2}, Rational{3, 8}, Events(1, 11), std::nullopt},
       {{2}, {0}, {3}, Rational{1, 2}, Events(2, 12), std::nullopt}}};
  WinningPathQuery query{"graph", "revision", BattleSide::attacker, 1};
  const auto first = ListWinningPathGroups(graph, query);
  ASSERT_EQ(first.path_groups.size(), 1); EXPECT_EQ(first.returned_probability, (Rational{1, 2}));
  EXPECT_EQ(first.winner_probability, Rational{1}); EXPECT_TRUE(first.query_complete); EXPECT_TRUE(first.has_more);
  EXPECT_EQ(first.next_offset, Integer{1}); EXPECT_EQ(first.prefix_tree.probability, first.returned_probability);
  query.limit = 100; query.offset = 0;
  const auto result = ListWinningPathGroups(graph, query);
  ASSERT_EQ(result.path_groups.size(), 2);
  const auto group = std::ranges::find_if(result.path_groups, [](const auto& value) { return value.raw_path_count == 2; });
  ASSERT_NE(group, result.path_groups.end()); EXPECT_EQ(group->damage_values, (std::vector<Integer>{10, 11}));
  ASSERT_EQ(group->representative_path.size(), 1); EXPECT_EQ(group->representative_path.front().edge.value, 1);
  EXPECT_EQ(group->raw_history_count_estimate, 2);
  query.offset = Integer{"10000000000000000000000000000000000000000000000000"};
  const auto empty = ListWinningPathGroups(graph, query); EXPECT_TRUE(empty.path_groups.empty()); EXPECT_FALSE(empty.has_more);
}
/// 原有限无重复walk只覆盖1/2，完整有出口循环的吸收胜率仍为1，cycle原缺SCC保持null。
TEST(WinningPaths, SolvesFullCycleButPreservesFiniteWalkCoverageAndBudget) {
  WinningPathGraph graph{{{{0}, State(), GraphOutcome::non_terminal, std::nullopt}, {{1}, State(2), GraphOutcome::non_terminal, std::nullopt},
      {{2}, State(3), GraphOutcome::attacker_win, BattleTermination::knockout}},
      {{{0}, {0}, {1}, Rational{1}, Events(1, 1), std::nullopt},
       {{1}, {1}, {0}, Rational{1, 2}, Events(1, 2), std::nullopt},
       {{2}, {1}, {2}, Rational{1, 2}, Events(1, 3), std::nullopt}}};
  WinningPathQuery query{"graph", "revision", BattleSide::attacker};
  const auto result = ListWinningPathGroups(graph, query);
  EXPECT_EQ(result.winner_probability, Rational{1}); EXPECT_EQ(result.returned_probability, (Rational{1, 2}));
  EXPECT_EQ(result.returned_coverage, (Rational{1, 2})); EXPECT_FALSE(result.query_complete); EXPECT_FALSE(result.traversal_truncated);
  ASSERT_EQ(result.cycle_references.size(), 1); EXPECT_FALSE(result.cycle_references.front().component);
  graph.components.push_back({{17}, {{0}, {1}}});
  const auto tagged = ListWinningPathGroups(graph, query); EXPECT_EQ(tagged.cycle_references.front().component->value, 17);
  query.max_traversed_walks = 1;
  const auto limited = ListWinningPathGroups(graph, query); EXPECT_TRUE(limited.traversal_truncated); EXPECT_TRUE(limited.path_groups.empty());
  EXPECT_EQ(limited.winner_probability, Rational{1});
}
/// 根已终局仍有空行动胜利walk；unknown/截断保留不可用概率，不伪造零胜率。
TEST(WinningPaths, HandlesTerminalRootIncompleteAndCancellation) {
  WinningPathGraph graph{{{{0}, State(), GraphOutcome::attacker_win, BattleTermination::knockout}}, {}};
  WinningPathQuery query{"graph", "revision", BattleSide::attacker};
  const auto terminal = ListWinningPathGroups(graph, query);
  ASSERT_EQ(terminal.path_groups.size(), 1); EXPECT_EQ(terminal.path_groups.front().raw_history_count_estimate, 1);
  EXPECT_TRUE(terminal.path_groups.front().actions.empty()); EXPECT_EQ(terminal.prefix_tree.terminal_path_keys.size(), 1);
  graph.nodes.front().outcome = GraphOutcome::unknown; graph.truncations = {GraphTruncation::max_nodes};
  const auto incomplete = ListWinningPathGroups(graph, query); EXPECT_FALSE(incomplete.winner_probability); EXPECT_FALSE(incomplete.query_complete);
  CancellationSource source; source.Request(); EXPECT_THROW((void)ListWinningPathGroups(graph, query, source.Token()), std::runtime_error);
  query.limit = 0; EXPECT_THROW((void)ListWinningPathGroups(graph, query), std::invalid_argument);
}
/// 原solver依赖传入SCC吸收边界；空分类的封闭环为奇异，不擅自推断成已有完整零胜率。
TEST(WinningPaths, PreservesOriginalMissingClosedComponentUnavailability) {
  WinningPathGraph graph{{{{0}, State(), GraphOutcome::non_terminal, std::nullopt}},
      {{{0}, {0}, {0}, Rational{1}, EventSummary{}, std::nullopt}}};
  const WinningPathQuery query{"graph", "revision", BattleSide::attacker};
  EXPECT_FALSE(ListWinningPathGroups(graph, query).winner_probability);
  graph.components = {{{0}, {{0}}, ComponentKind::closed_cycle}};
  const auto classified = ListWinningPathGroups(graph, query);
  EXPECT_EQ(classified.winner_probability, Rational{0}); EXPECT_FALSE(classified.returned_coverage);
  EXPECT_FALSE(classified.query_complete); EXPECT_EQ(classified.cycle_references.front().component->value, 0);
}
/// 已实际运行的指数walk查询中途取消必须撤销全部局部结果，而非返回truncated或零覆盖。
TEST(WinningPaths, CancelsAnActuallyRunningTraversalAtomically) {
  WinningPathGraph graph;
  for (std::size_t index = 0; index < 60; ++index) graph.nodes.push_back({{Integer{index}}, State(1 + index / 2),
      index >= 58 ? GraphOutcome::attacker_win : GraphOutcome::non_terminal, std::nullopt});
  for (std::size_t index = 0; index < 58; ++index) {
    const auto target = (index / 2 + 1) * 2;
    for (std::size_t offset = 0; offset < 2; ++offset) graph.edges.push_back({{Integer{graph.edges.size()}}, {Integer{index}},
        {Integer{target + offset}}, Rational{1, 2}, EventSummary{}, std::nullopt});
  }
  WinningPathQuery query{"graph", "revision", BattleSide::attacker}; query.max_traversed_walks = 1000000000;
  CancellationSource source;
  auto running = std::async(std::launch::async, [&] { return ListWinningPathGroups(graph, query, source.Token()); });
  EXPECT_EQ(running.wait_for(std::chrono::milliseconds{30}), std::future_status::timeout);
  source.Request(); EXPECT_THROW((void)running.get(), std::runtime_error);
}
/// 同一次真实构图直接借用和原record输入必须给同一身份/概率/分组；正式边事件地址不变。
TEST(WinningPaths, QueriesTheActualTypedBattleGraphWithoutAnEventCopyAdapter) {
  auto data = State().View(); auto rules = data.rules.View(); rules.damage_policy.random_damage_multipliers = {1};
  data.rules = InferenceRules{std::move(rules)};
  FixedBattleOptions options; options.attacker_policy = ActionPolicy::first_legal_action; options.defender_policy = ActionPolicy::first_legal_action;
  const auto computation = InferFixedBattle(BattleState{std::move(data)}, TypeChartSnapshot{{{PokemonType::normal, PokemonType::normal, 100}}}, options);
  const auto& graph = computation.graph; ASSERT_FALSE(graph.Edges().empty());
  const auto* first_history = &graph.Edges().front().events.Paths().front();
  const WinningPathQuery query{"actual-graph", "revision", BattleSide::attacker};
  const auto actual = ListWinningPathGroups(graph, query);
  WinningPathGraph records;
  // 仅测试用小图复制为既有record输入，生产路径直接调用上面的只读正式图重载。
  for (const auto& node : graph.Nodes()) records.nodes.push_back({{Integer{node.id.value}}, node.state, node.outcome, node.reason});
  for (const auto& edge : graph.Edges()) records.edges.push_back({{Integer{edge.id.value}}, {Integer{edge.source.value}}, {Integer{edge.target.value}}, edge.probability, edge.events, edge.source_key});
  for (const auto& component : graph.Components()) {
    WinningPathComponent entry{component.id, {}, component.kind};
    for (const auto id : component.nodes) entry.nodes.push_back({Integer{id.value}});
    records.components.push_back(std::move(entry));
  }
  records.truncations.assign(graph.Truncations().begin(), graph.Truncations().end());
  const auto expected = ListWinningPathGroups(records, query);
  EXPECT_EQ(actual.configuration.configuration_key, DescribeWinningPathConfiguration(graph).configuration_key);
  EXPECT_EQ(actual.configuration.configuration_key, expected.configuration.configuration_key);
  EXPECT_EQ(actual.winner_probability, expected.winner_probability); EXPECT_EQ(actual.returned_probability, expected.returned_probability);
  EXPECT_EQ(actual.returned_coverage, expected.returned_coverage); EXPECT_EQ(actual.query_complete, expected.query_complete);
  ASSERT_EQ(actual.path_groups.size(), expected.path_groups.size());
  for (std::size_t index = 0; index < actual.path_groups.size(); ++index) {
    const auto& left = actual.path_groups[index]; const auto& right = expected.path_groups[index];
    EXPECT_EQ(left.path_key, right.path_key); EXPECT_EQ(left.probability, right.probability); EXPECT_EQ(left.terminal_node_ids, right.terminal_node_ids);
    EXPECT_EQ(left.raw_history_count_estimate, right.raw_history_count_estimate); EXPECT_EQ(left.damage_values, right.damage_values);
    EXPECT_EQ(left.actions.size(), right.actions.size()); EXPECT_EQ(left.representative_path.size(), right.representative_path.size());
  }
  EXPECT_EQ(&graph.Edges().front().events.Paths().front(), first_history);
}
} // namespace
} // namespace pbi
