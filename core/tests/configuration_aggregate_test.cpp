#include "pbi/configuration_aggregate.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param id 稳定caseID；@param weight 原完整空间权重；@param win 精确胜率。
/// @param expected 有限期望或null表示无限；@return 一个合法成功轻量结果。
ConfigurationPairObservation Success(std::string id, Rational weight, Rational win,
                                     std::optional<Rational> expected = Rational{1}) {
  std::variant<FiniteExpectedTurns, InfiniteExpectedTurns> turns = InfiniteExpectedTurns{};
  if (expected) turns = FiniteExpectedTurns{*expected};
  return {{std::move(id), "attacker", "defender", {1}, {2}}, std::move(weight),
      ConfigurationPairSuccess{win, Rational{1} - win, Rational{0}, std::move(turns)}, Integer{3}, Integer{2}};
}
/// 失败、截断和未执行权重均不重新归一化，资源统计包含全部已尝试配置。
TEST(ConfigurationAggregate, KeepsFullSpaceWeightsAndAllStatusBuckets) {
  ConfigurationPairAggregator aggregate{2};
  aggregate.Add(Success("success", Rational{1, 5}, Rational{3, 4}));
  aggregate.Add({{"truncated", "a", "b", {}, {}}, Rational{1, 3}, ConfigurationPairTruncated{}, Integer{10}, Integer{9}});
  aggregate.Add({{"failed", "a", "b", {}, {}}, Rational{1, 6}, ConfigurationPairFailed{}, Integer{7}, Integer{4}});
  const auto result = aggregate.Finish(ConfigurationPairStopReason::configuration_pair_limit, Integer{10});
  EXPECT_EQ(result.progress.processed_pair_count, 3);
  EXPECT_EQ(result.unprocessed_pair_count, 7);
  EXPECT_EQ(result.progress.attempted_weight, (Rational{7, 10}));
  EXPECT_EQ(result.progress.completed_weight, (Rational{1, 5}));
  EXPECT_EQ(result.weighted_win, (Rational{3, 20}));
  EXPECT_EQ(result.weighted_loss, (Rational{1, 20}));
  EXPECT_EQ(result.progress.cumulative_node_count, 20);
  EXPECT_EQ(result.fraction_complexity.observed_fraction_count, 16);
}
/// 每类只保留K；无限期望不进有限期望排行，胜率及节点/边tie使用原pairID顺序。
TEST(ConfigurationAggregate, PreservesBoundedRankingsAndFiniteExpectedTurns) {
  ConfigurationPairAggregator aggregate{2};
  auto first = Success("z", Rational{1, 4}, Rational{1, 2}, Rational{7});
  first.node_count = 9;
  first.edge_count = 3;
  auto second = Success("a", Rational{1, 4}, Rational{1, 2}, std::nullopt);
  second.node_count = 9;
  second.edge_count = 5;
  aggregate.Add(first);
  aggregate.Add(second);
  aggregate.Add(Success("m", Rational{1, 4}, Rational{1}, Rational{2}));
  const auto result = aggregate.Finish(ConfigurationPairStopReason::cancelled, Integer{3});
  EXPECT_EQ(result.stop_reason, ConfigurationPairStopReason::completed);
  ASSERT_EQ(result.top_win_probability.size(), 2);
  EXPECT_EQ(result.top_win_probability[0].identity.pair_id, "m");
  EXPECT_EQ(result.top_win_probability[1].identity.pair_id, "a");
  ASSERT_EQ(result.top_expected_turns.size(), 2);
  EXPECT_EQ(result.top_expected_turns[0].identity.pair_id, "z");
  EXPECT_EQ(result.top_node_count[0].identity.pair_id, "a");
}
/// 同pairID/指标仍按执行先后稳定保留，聚合器不擅自把重复观察当幂等重试去重。
TEST(ConfigurationAggregate, KeepsStableTieOrderWithoutImplicitDeduplication) {
  ConfigurationPairAggregator aggregate{1};
  auto first = Success("same", Rational{1, 2}, Rational{1});
  auto second = first;
  first.identity.attacker_configuration_id = "first";
  second.identity.attacker_configuration_id = "second";
  aggregate.Add(first);
  aggregate.Add(second);
  const auto result = aggregate.Finish(ConfigurationPairStopReason::completed, Integer{2});
  EXPECT_EQ(result.progress.succeeded_count, 2);
  EXPECT_EQ(result.top_win_probability.front().identity.attacker_configuration_id, "first");
}
/// 任意精度分母和累计资源保持精确，位数统计不是浮点日志近似。
TEST(ConfigurationAggregate, TracksArbitraryPrecisionResourcesAndFractionBits) {
  ConfigurationPairAggregator aggregate{1};
  const Integer huge{"100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000007"};
  auto observation = Success("large", Rational{Integer{1}, huge}, Rational{1});
  observation.node_count = huge;
  aggregate.Add(observation);
  const auto result = aggregate.Finish(ConfigurationPairStopReason::cumulative_node_limit, Integer{2});
  EXPECT_EQ(result.progress.cumulative_node_count, huge);
  EXPECT_EQ(result.weighted_win.denominator(), huge);
  EXPECT_GT(result.fraction_complexity.max_denominator_bits, 600);
  EXPECT_EQ(result.fraction_complexity.final_draw_numerator_bits, 0);
  EXPECT_EQ(result.fraction_complexity.final_draw_denominator_bits, 1);
}
/// 无效观察在累加前拒绝，最终完整空间校验不会掩盖过量权重或错误配置数。
TEST(ConfigurationAggregate, RejectsInvalidObservationsAndInvalidFullSpace) {
  EXPECT_THROW((void)ConfigurationPairAggregator{0}, std::invalid_argument);
  ConfigurationPairAggregator aggregate{1};
  EXPECT_THROW(aggregate.Add(Success("bad", Rational{0}, Rational{1})), std::invalid_argument);
  EXPECT_EQ(aggregate.Progress(Integer{1}).processed_pair_count, 0);
  aggregate.Add(Success("first", Rational{3, 4}, Rational{1}));
  aggregate.Add(Success("second", Rational{3, 4}, Rational{1}));
  EXPECT_THROW((void)aggregate.Finish(ConfigurationPairStopReason::completed, Integer{2}), std::invalid_argument);
  EXPECT_THROW((void)aggregate.Finish(ConfigurationPairStopReason::completed, Integer{1}), std::invalid_argument);
}
} // namespace
} // namespace pbi
