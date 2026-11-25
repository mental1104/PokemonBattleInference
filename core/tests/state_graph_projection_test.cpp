#include "pbi/state_graph_projection.hpp"
#include "pbi/turn.hpp"
#include <gtest/gtest.h>
#include <thread>

namespace pbi {
namespace {
/// @param id 正配置ID；@return 一个拥有完整规则事实的简单真实单招式战斗方。
BattlerState ProjectionBattler(std::int64_t id) {
  const PokemonSpec spec{{id, "test", {50, {PokemonType::normal}, {100, 100, 100, 100, 100, 100}, DamageAbility::none, DamageItem::none, false, std::nullopt},
      {MoveSpec{{1, "attack", {PokemonType::normal, DamageCategory::physical, 40}, 3, 0, 100, std::nullopt}}}}};
  return BattlerState{{spec, 100, {MoveSlotState{{1, 3, 3}}}, StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @return 完整合法source节点，构造不执行随机伤害或产生预制解。
StateGraphProjectionNode ProjectionNode() {
  BattleState state{{ProjectionBattler(1), ProjectionBattler(2), InferenceRules{}, 1, {}, BattlePhase::action_selection}};
  return {{0}, state, GraphOutcome::non_terminal, std::nullopt};
}
/// @param payload 可空原metadata编码；@param selected 是否包含双方真实MOVE_SELECTED事实。
/// @return 单条完整历史，不把测试随机假转移当作生产回合入口。
std::vector<PathEvent> ProjectionHistory(std::optional<std::string> payload, bool selected = true) {
  std::vector<PathEvent> events;
  if (selected) for (const auto side : {BattleSide::attacker, BattleSide::defender}) {
    events.emplace_back(BattleEvent{{BattleEventKind::move_selected, 1, side, std::nullopt, 1, "move"}});
  }
  if (payload) events.emplace_back(TransitionEvent{{TransitionEventType::custom, "application.joint-action-probability", *payload}});
  return events;
}
/// @param paths 完整拥有路径；@param probability 正式边概率；@return 原事件类型验证后的正式边记录。
StateGraphProjectionEdge ProjectionEdge(std::vector<WeightedEventPath> paths, Rational probability = Rational{1}) {
  return {{0}, {0}, {1}, probability, EventSummary{std::move(paths)}, std::nullopt};
}
} // namespace

/// 真实回合→图→按需展开；输出保留Core生成的正式边身份和精确累计概率。
TEST(StateGraphProjection, RealTurnGraphAndExactCumulativeProbability) {
  const auto source = ProjectionNode();
  const StandardTurnResolver resolver{TypeChartSnapshot{{{PokemonType::normal, PokemonType::normal, 100}}}};
  const auto graph = BuildBattleGraph(source.state, [&](const BattleState& state) {
    return resolver.Expand(state, ActionPolicy::uniform_random, ActionPolicy::uniform_random);
  }, {512, 2048, 2});
  std::vector<StateGraphProjectionEdge> edges;
  for (const auto& edge : graph.Edges()) if (edge.source.value == 0) edges.push_back(ProjectionRecord(edge));
  const Rational cumulative{3, 7};
  const auto collapsed = ProjectBattleGraphNode(ProjectionRecord(graph.Nodes().front()), edges, cumulative);
  ASSERT_EQ(collapsed.transition_groups.size(), 1);
  EXPECT_EQ(collapsed.transition_groups.front().selection_probability, Rational{1});
  EXPECT_TRUE(collapsed.transition_groups.front().outcomes.empty());
  const std::vector ids{collapsed.transition_groups.front().group_id};
  const auto expanded = ProjectBattleGraphNode(ProjectionRecord(graph.Nodes().front()), edges, cumulative, ids);
  Rational total{0};
  for (const auto& outcome : expanded.transition_groups.front().outcomes) {
    total += outcome.probability;
    EXPECT_EQ(outcome.cumulative_probability, cumulative * outcome.joint_probability);
    EXPECT_FALSE(outcome.event_paths.empty());
  }
  EXPECT_EQ(total, Rational{1});
}

/// 元数据必须完整、唯一且精确还原正式边；拒绝后不能返回部分归一化结果。
TEST(StateGraphProjection, RejectsConflictingIncompleteAndInvalidMetadata) {
  const auto node = ProjectionNode();
  for (const auto& payload : {"1/0|1/1", "2/1|1/1", "1/1|0/1", "bad", "1/1|1/2"}) {
    const std::vector edges{ProjectionEdge({{ProjectionHistory(payload), Rational{1}}})};
    EXPECT_THROW(static_cast<void>(ProjectBattleGraphNode(node, edges)), std::invalid_argument);
  }
  auto duplicate = ProjectionHistory("1/1|1/1");
  duplicate.emplace_back(TransitionEvent{{TransitionEventType::custom, "application.joint-action-probability", "1/1|1/1"}});
  const std::vector duplicate_edges{ProjectionEdge({{std::move(duplicate), Rational{1}}})};
  EXPECT_THROW(static_cast<void>(ProjectBattleGraphNode(node, duplicate_edges)), std::invalid_argument);
  const std::vector mixed{ProjectionEdge({{ProjectionHistory("1/1|1/1"), Rational{1, 2}}, {ProjectionHistory(std::nullopt, false), Rational{1, 2}}})};
  EXPECT_THROW(static_cast<void>(ProjectBattleGraphNode(node, mixed)), std::invalid_argument);
}

/// 空图节点保持合法；非法累计值/跨节点出边拒绝，不从客户端补造概率。
TEST(StateGraphProjection, ValidatesInputOwnershipAndBounds) {
  const auto node = ProjectionNode();
  EXPECT_TRUE(ProjectBattleGraphNode(node, {}).transition_groups.empty());
  EXPECT_THROW(static_cast<void>(ProjectBattleGraphNode(node, {}, Rational{-1})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(ProjectBattleGraphNode(node, {}, Rational{2})), std::invalid_argument);
  auto foreign = ProjectionEdge({{{}, Rational{1}}});
  foreign.source = {2};
  const std::vector edges{foreign};
  EXPECT_THROW(static_cast<void>(ProjectBattleGraphNode(node, edges)), std::invalid_argument);
  const std::vector<std::string> invalid{" "};
  EXPECT_THROW(static_cast<void>(ProjectBattleGraphNode(node, {}, Rational{1}, invalid)), std::invalid_argument);
}

/// 运行中取消在逐路径/贡献循环中传播，源和输入由本线程拥有直到执行与取消线程均结束。
TEST(StateGraphProjection, CooperativeCancellationDoesNotReturnPartialGroups) {
  const auto node = ProjectionNode();
  std::vector<StateGraphProjectionEdge> edges;
  const auto event = ProjectionEdge({{{}, Rational{1}}});
  for (std::size_t index = 0; index < 100000; ++index) { edges.push_back(event); edges.back().id = {index}; }
  CancellationSource source;
  std::thread cancel([&]() { std::this_thread::sleep_for(std::chrono::milliseconds{1}); static_cast<void>(source.Request()); });
  EXPECT_THROW(static_cast<void>(ProjectBattleGraphNode(node, edges, Rational{1}, {}, source.Token())), std::runtime_error);
  cancel.join();
  EXPECT_TRUE(source.Requested());
}
} // namespace pbi

namespace pbi {
/// 战报累乘正式边概率并保留所有替代历史，不误用其中一个联合行动的条件概率。
TEST(StateGraphProjection, ReportStepPreservesFormalProbabilityAndAlternativePaths) {
  const auto node = ProjectionNode();
  const auto edge = ProjectionEdge({{ProjectionHistory("1/1|1/1"), Rational{1, 4}},
      {ProjectionHistory(std::nullopt), Rational{3, 4}}}, Rational{1, 2});
  const auto result = ProjectBattleGraphStep(node, edge, Rational{3, 5}, 7);
  EXPECT_EQ(result.depth, 7);
  EXPECT_EQ(result.edge_probability, (Rational{1, 2}));
  EXPECT_EQ(result.cumulative_probability, (Rational{3, 10}));
  EXPECT_EQ(result.event_paths.size(), 2);
  EXPECT_THROW(static_cast<void>(ProjectBattleGraphStep(node, edge, Rational{1}, 0)), std::invalid_argument);
  CancellationSource stop;
  static_cast<void>(stop.Request());
  EXPECT_THROW(static_cast<void>(ProjectBattleGraphStep(node, edge, Rational{1}, 1, stop.Token())), std::runtime_error);
}
} // namespace pbi
