#pragma once

#include "pbi/graph.hpp"

namespace pbi {
/// 领取配置的停止原因；已处理全部配置时最终摘要统一为completed。
enum class ConfigurationPairStopReason { completed, configuration_pair_limit, cumulative_node_limit,
                                         cumulative_edge_limit, max_failures, cancelled };
/// 配置层稳定身份；不拥有原始配置或完整状态图。
struct ConfigurationPairIdentity {
  std::string pair_id;
  std::string attacker_configuration_id;
  std::string defender_configuration_id;
  std::vector<std::int64_t> attacker_move_ids;
  std::vector<std::int64_t> defender_move_ids;
};
/// 完整成功摘要，期望有限/无限互斥；失败类型不能携带部分概率。
struct ConfigurationPairSuccess {
  Rational win;
  Rational loss;
  Rational draw;
  std::variant<FiniteExpectedTurns, InfiniteExpectedTurns> expected_turns;
};
/// 图预算截断的轻量标记，不冒充零胜率或数学平局。
struct ConfigurationPairTruncated {};
/// 明确执行失败标记，不携带貌似成功的部分概率。
struct ConfigurationPairFailed {};
/// 一个已执行配置的聚合输入；只拥有轻量身份、精确权重和必要资源统计。
struct ConfigurationPairObservation {
  ConfigurationPairIdentity identity;
  Rational configuration_weight;
  std::variant<ConfigurationPairSuccess, ConfigurationPairTruncated, ConfigurationPairFailed> outcome;
  Integer node_count;
  Integer edge_count;
};
/// Top-K只持有成功摘要，有限期望为null表示原完整解的无限期望。
struct ConfigurationPairRankingEntry {
  ConfigurationPairIdentity identity;
  Rational win;
  Rational loss;
  Rational draw;
  std::optional<Rational> expected_turns;
  Integer node_count;
  Integer edge_count;
};
/// 与原Fraction统计相同的位数复杂度，零分子为0位，分母始终正数。
struct ConfigurationFractionComplexity {
  Integer observed_fraction_count{0};
  std::size_t max_numerator_bits = 0;
  std::size_t max_denominator_bits = 0;
  std::size_t final_win_numerator_bits = 0;
  std::size_t final_win_denominator_bits = 0;
  std::size_t final_loss_numerator_bits = 0;
  std::size_t final_loss_denominator_bits = 0;
  std::size_t final_draw_numerator_bits = 0;
  std::size_t final_draw_denominator_bits = 0;
};
/// 配置数量和累计资源的双轴进度，计数不受机器整数宽度限制。
struct ConfigurationAggregateProgress {
  Integer processed_pair_count{0};
  Integer total_pair_count{0};
  Integer succeeded_count{0};
  Integer truncated_count{0};
  Integer failed_count{0};
  Rational attempted_weight{0};
  Rational completed_weight{0};
  Integer cumulative_node_count{0};
  Integer cumulative_edge_count{0};
};
/// 完整或部分聚合，胜负平之和严格等于completed_weight，不重归一化失败/截断权重。
struct ConfigurationPairAggregate {
  ConfigurationPairStopReason stop_reason;
  ConfigurationAggregateProgress progress;
  Integer unprocessed_pair_count;
  Rational weighted_win;
  Rational weighted_loss;
  Rational weighted_draw;
  std::vector<ConfigurationPairRankingEntry> top_win_probability;
  std::vector<ConfigurationPairRankingEntry> top_expected_turns;
  std::vector<ConfigurationPairRankingEntry> top_node_count;
  ConfigurationFractionComplexity fraction_complexity;
};
/// 显式可变的流式聚合器，额外内存只与Top-K相关，不缓存全部配置或图。
class ConfigurationPairAggregator {
public:
  /// @param top_k 三类成功排行各自保留的正数量；零值明确拒绝。
  explicit ConfigurationPairAggregator(std::size_t top_k);
  /// @param result 完整已执行轻量结果；校验概率/权重/计数后合入本实例。
  /// 不接收完整状态图，也不对重复pair_id做幂等去重，保持原按执行结果聚合语义。
  void Add(const ConfigurationPairObservation& result);
  /// @param total_pair_count 未被运行预算缩减的完整配置对数；@return 当前拥有值进度。
  [[nodiscard]] ConfigurationAggregateProgress Progress(const Integer& total_pair_count) const;
  /// @param reason 执行循环的实际停止原因；@param total_pair_count 完整原候选配置对数。
  /// @return 精确守恒的最终拥有值；已处理数/权重超出完整空间时明确失败。
  [[nodiscard]] ConfigurationPairAggregate Finish(ConfigurationPairStopReason reason,
                                                  const Integer& total_pair_count) const;
private:
  /// @param value 本次需要观察的原分数或中间累加值；更新复杂度计数和最大位数。
  void Observe(const Rational& value);
  /// @param result 完整成功输入；@param success 已通过校验的完整概率；更新三类有界排行。
  void Rank(const ConfigurationPairObservation& result, const ConfigurationPairSuccess& success);
  std::size_t top_k_;
  ConfigurationAggregateProgress progress_;
  Rational win_{0};
  Rational loss_{0};
  Rational draw_{0};
  ConfigurationFractionComplexity complexity_;
  std::vector<ConfigurationPairRankingEntry> win_entries_;
  std::vector<ConfigurationPairRankingEntry> expected_entries_;
  std::vector<ConfigurationPairRankingEntry> node_entries_;
};
} // namespace pbi
