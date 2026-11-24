#include "pbi/event_analysis.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param outcome 真实随机结果；@return 一个完整普通命中检查事件。
PathEvent Hit(std::string outcome = "hit") {
  return TransitionEvent{{TransitionEventType::hit_check, "accuracy", std::move(outcome), std::nullopt}};
}
/// @return 只匹配hit结果的原结构化过滤器，使用较小分布上限以验证所有精确桶。
EventQuery Query() {
  EventQuery query;
  query.predicate.outcome_id = "hit";
  query.distribution_count_limit = 2;
  query.distribution_turn_limit = 3;
  return query;
}
/// 同一后继的多条替代事件历史必须按条件权重展开，不可只检查首条路径。
TEST(EventAnalysis, PreservesAlternativeHistoryWeightsAndJointProbability) {
  const EventSummary histories{{{{Hit()}, Rational{1, 4}}, {{Hit("miss")}, Rational{3, 4}}}};
  const EventAnalysisArtifact artifact{"rules-v1", "run-1", {ProbabilityGraph{{{GraphOutcome::non_terminal}, {GraphOutcome::attacker_win}},
      {{{0}, {1}, Rational{1}}}}, {histories}, 1}};
  const auto result = AnalyzeBattleEvents(artifact, Query());
  EXPECT_EQ(result.baseline_win, Rational{1});
  EXPECT_EQ(result.event_probability, (Rational{1, 4}));
  EXPECT_EQ(result.event_win_joint_probability, (Rational{1, 4}));
  ASSERT_TRUE(result.win_given_event.value);
  EXPECT_EQ(*result.win_given_event.value, Rational{1});
  EXPECT_EQ(result.path_group_coverage.total_edges, 1);
  EXPECT_EQ(result.path_group_coverage.total_path_groups, 2);
  EXPECT_EQ(result.path_group_coverage.matching_path_groups, 1);
  ASSERT_EQ(result.key_events.size(), 1);
  EXPECT_EQ(result.key_events[0].event_id, "accuracy");
  EXPECT_EQ(result.cost.exact_solver_runs, 13);
}
/// 有出口循环的完整历史事件不是边概率之和；次数分布保留精确几何尾部。
TEST(EventAnalysis, SolvesRecurrentHistoryAndExactCountTail) {
  const EventAnalysisArtifact artifact{"rules-v1", "run-2", {ProbabilityGraph{{{GraphOutcome::non_terminal}, {GraphOutcome::attacker_win}},
      {{{0}, {0}, Rational{1, 2}}, {{0}, {1}, Rational{1, 2}}}}, {EventSummary{{{{Hit()}, Rational{1}}}}, EventSummary{}}, 1}};
  const auto result = AnalyzeBattleEvents(artifact, Query());
  EXPECT_EQ(result.event_probability, (Rational{1, 2}));
  EXPECT_EQ(result.event_win_joint_probability, (Rational{1, 2}));
  ASSERT_EQ(result.occurrence_count_distribution.size(), 4);
  EXPECT_EQ(result.occurrence_count_distribution[0].probability, (Rational{1, 2}));
  EXPECT_EQ(result.occurrence_count_distribution[1].probability, (Rational{1, 4}));
  EXPECT_EQ(result.occurrence_count_distribution[2].probability, (Rational{1, 8}));
  EXPECT_EQ(result.occurrence_count_distribution[3].probability, (Rational{1, 8}));
}
/// 封闭循环按饱和次数求事件，不抛弃无限历史；零条件质量必须显式不可定义。
TEST(EventAnalysis, HandlesClosedHistoryAndUndefinedZeroCondition) {
  const EventAnalysisArtifact artifact{"rules-v1", "run-3", {ProbabilityGraph{{{GraphOutcome::non_terminal}}, {{{0}, {0}, Rational{1}}}},
      {EventSummary{{{{Hit()}, Rational{1}}}}}, 1}};
  auto query = Query();
  query.min_occurrences = 2;
  const auto result = AnalyzeBattleEvents(artifact, query);
  EXPECT_EQ(result.baseline_draw, Rational{1});
  EXPECT_EQ(result.event_probability, Rational{1});
  EXPECT_EQ(result.event_win_joint_probability, Rational{0});
  EXPECT_FALSE(result.win_given_not_event.value);
  EXPECT_EQ(result.win_given_not_event.condition_probability, Rational{0});
}
/// 业务字段只匹配真实业务事件，回合范围消费完整回合边而非事件展示中的turn字段。
TEST(EventAnalysis, UsesStructuredBusinessFilterAndActualEdgeTurn) {
  const PathEvent event = BattleEvent{{BattleEventKind::hit, 99, BattleSide::attacker, BattleSide::defender, 42}};
  EventQuery query = Query();
  query.predicate = {};
  query.predicate.battle_event_kinds = {BattleEventKind::hit};
  query.predicate.side = BattleSide::defender;
  query.predicate.side_role = EventSideRole::target;
  query.predicate.move_id = 42;
  EXPECT_TRUE(query.predicate.Matches(event));
  EXPECT_FALSE(query.predicate.Matches(Hit()));
  query.turn_range = EventTurnRange{5, 5};
  query.occurrence_mode = EventOccurrenceMode::first;
  const EventAnalysisArtifact artifact{"rules-v1", "run-4", {ProbabilityGraph{{{GraphOutcome::non_terminal}, {GraphOutcome::defender_win}},
      {{{0}, {1}, Rational{1}}}}, {EventSummary{{{{event}, Rational{1}}}}}, 5}};
  EXPECT_EQ(AnalyzeBattleEvents(artifact, query, BattleSide::defender).event_probability, Rational{1});
  query.turn_range = EventTurnRange{99, 99};
  EXPECT_EQ(AnalyzeBattleEvents(artifact, query).event_probability, Rational{0});
}
/// 原覆盖先按完整事件去重，再按摘要身份计数；数值不同的同身份事件不能被提前合并。
TEST(EventAnalysis, PreservesFullEventDedupBeforeSummaryIdentityCounting) {
  const PathEvent first = TransitionEvent{{TransitionEventType::hit_check, "accuracy", "hit", Integer{1}}};
  const PathEvent second = TransitionEvent{{TransitionEventType::hit_check, "accuracy", "hit", Integer{2}}};
  const EventAnalysisArtifact artifact{"rules-v1", "run-distinct-values", {ProbabilityGraph{{{GraphOutcome::non_terminal}, {GraphOutcome::attacker_win}},
      {{{0}, {1}, Rational{1}}}}, {EventSummary{{{{first, second, first}, Rational{1}}}}}, 1}};
  auto query = Query();
  query.min_occurrences = 3;
  query.max_occurrences = 3;
  const auto result = AnalyzeBattleEvents(artifact, query);
  EXPECT_EQ(result.event_probability, Rational{1});
  ASSERT_EQ(result.key_events.size(), 1);
  EXPECT_EQ(result.key_events[0].path_group_count, 2);
  EXPECT_EQ(result.path_group_coverage.matching_path_groups, 1);
  EXPECT_EQ(result.occurrence_count_distribution.back().probability, Rational{1});
}
/// 截断、残缺元数据、无效查询和取消均整体拒绝，不返回部分概率。
TEST(EventAnalysis, RejectsIncompleteInputsAndCancellation) {
  const EventAnalysisArtifact incomplete{"rules-v1", "run-5", {ProbabilityGraph{{{GraphOutcome::unknown}}, {}, {0}, {GraphTruncation::max_nodes}}, {}, 1}};
  EXPECT_THROW((void)AnalyzeBattleEvents(incomplete, Query()), std::invalid_argument);
  const EventAnalysisArtifact missing{"rules-v1", "run-6", {ProbabilityGraph{{{GraphOutcome::non_terminal}, {GraphOutcome::draw}}, {{{0}, {1}, Rational{1}}}}, {}, 1}};
  EXPECT_THROW((void)AnalyzeBattleEvents(missing, Query()), std::invalid_argument);
  auto query = Query();
  query.min_occurrences = -1;
  EXPECT_THROW((void)AnalyzeBattleEvents(missing, query), std::invalid_argument);
  CancellationSource stop;
  EXPECT_TRUE(stop.Request());
  EXPECT_THROW((void)AnalyzeBattleEvents(missing, Query(), BattleSide::attacker, stop.Token()), std::runtime_error);
}
} // namespace
} // namespace pbi
