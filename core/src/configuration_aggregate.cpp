#include "pbi/configuration_aggregate.hpp"
#include <algorithm>

namespace pbi {
namespace {
/// @param value 任意精度整数；@return abs(value).bit_length()，零为0。
std::size_t BitLength(const Integer& value) {
  if (value == 0) return 0;
  const Integer magnitude = value < 0 ? -value : value;
  return static_cast<std::size_t>(boost::multiprecision::msb(magnitude)) + 1;
}
/// @param value 轻量配置观察；所有拒绝先于累加状态修改，不伪造失败概率。
void Validate(const ConfigurationPairObservation& value) {
  if (value.configuration_weight <= Rational{0} || value.configuration_weight > Rational{1}) {
    throw std::invalid_argument("configuration weight must be in (0, 1]");
  }
  if (value.node_count < 0 || value.edge_count < 0) throw std::invalid_argument("configuration graph counts must be nonnegative");
  if (const auto* success = std::get_if<ConfigurationPairSuccess>(&value.outcome)) {
    for (const auto& probability : {success->win, success->loss, success->draw}) {
      if (probability < Rational{0} || probability > Rational{1}) throw std::invalid_argument("successful pair probabilities must be in [0, 1]");
    }
    if (success->win + success->loss + success->draw != Rational{1}) throw std::invalid_argument("successful pair probabilities must sum exactly to 1");
    if (const auto* finite = std::get_if<FiniteExpectedTurns>(&success->expected_turns); finite && finite->value < Rational{0}) {
      throw std::invalid_argument("finite expected turns must be nonnegative");
    }
  }
}
/// @param reason 有限停止原因；未知枚举不可伪装为completed。
void ValidateReason(ConfigurationPairStopReason reason) {
  switch (reason) {
  case ConfigurationPairStopReason::completed:
  case ConfigurationPairStopReason::configuration_pair_limit:
  case ConfigurationPairStopReason::cumulative_node_limit:
  case ConfigurationPairStopReason::cumulative_edge_limit:
  case ConfigurationPairStopReason::max_failures:
  case ConfigurationPairStopReason::cancelled: return;
  }
  throw std::invalid_argument("unknown configuration pair stop reason");
}
} // namespace

ConfigurationPairAggregator::ConfigurationPairAggregator(std::size_t top_k) : top_k_(top_k) {
  if (top_k == 0) throw std::invalid_argument("top_k must be greater than 0");
}

void ConfigurationPairAggregator::Observe(const Rational& value) {
  ++complexity_.observed_fraction_count;
  complexity_.max_numerator_bits = std::max(complexity_.max_numerator_bits, BitLength(value.numerator()));
  complexity_.max_denominator_bits = std::max(complexity_.max_denominator_bits, BitLength(value.denominator()));
}

void ConfigurationPairAggregator::Rank(const ConfigurationPairObservation& result, const ConfigurationPairSuccess& success) {
  const auto* finite = std::get_if<FiniteExpectedTurns>(&success.expected_turns);
  ConfigurationPairRankingEntry entry{result.identity, success.win, success.loss, success.draw,
      finite ? std::optional{finite->value} : std::nullopt, result.node_count, result.edge_count};
  win_entries_.push_back(entry);
  // 原Python稳定排序相同指标和pair_id时仍保留执行顺序；不以不稳定sort改变首代表。
  std::stable_sort(win_entries_.begin(), win_entries_.end(), [](const auto& first, const auto& second) {
    if (first.win != second.win) return first.win > second.win;
    return first.identity.pair_id < second.identity.pair_id;
  });
  if (win_entries_.size() > top_k_) win_entries_.resize(top_k_);
  if (finite) {
    expected_entries_.push_back(entry);
    std::stable_sort(expected_entries_.begin(), expected_entries_.end(), [](const auto& first, const auto& second) {
      if (first.expected_turns != second.expected_turns) return *first.expected_turns > *second.expected_turns;
      return first.identity.pair_id < second.identity.pair_id;
    });
    if (expected_entries_.size() > top_k_) expected_entries_.resize(top_k_);
  }
  node_entries_.push_back(std::move(entry));
  std::stable_sort(node_entries_.begin(), node_entries_.end(), [](const auto& first, const auto& second) {
    if (first.node_count != second.node_count) return first.node_count > second.node_count;
    if (first.edge_count != second.edge_count) return first.edge_count > second.edge_count;
    return first.identity.pair_id < second.identity.pair_id;
  });
  if (node_entries_.size() > top_k_) node_entries_.resize(top_k_);
}

void ConfigurationPairAggregator::Add(const ConfigurationPairObservation& result) {
  Validate(result);
  ++progress_.processed_pair_count;
  progress_.attempted_weight += result.configuration_weight;
  progress_.cumulative_node_count += result.node_count;
  progress_.cumulative_edge_count += result.edge_count;
  Observe(result.configuration_weight);
  Observe(progress_.attempted_weight);
  const auto* success = std::get_if<ConfigurationPairSuccess>(&result.outcome);
  if (!success) {
    if (std::holds_alternative<ConfigurationPairTruncated>(result.outcome)) ++progress_.truncated_count;
    else ++progress_.failed_count;
    return;
  }
  ++progress_.succeeded_count;
  const Rational weighted_win = result.configuration_weight * success->win;
  const Rational weighted_loss = result.configuration_weight * success->loss;
  const Rational weighted_draw = result.configuration_weight * success->draw;
  progress_.completed_weight += result.configuration_weight;
  win_ += weighted_win;
  loss_ += weighted_loss;
  draw_ += weighted_draw;
  for (const auto& value : {success->win, success->loss, success->draw, weighted_win, weighted_loss, weighted_draw,
                            progress_.completed_weight, win_, loss_, draw_}) Observe(value);
  Rank(result, *success);
}

ConfigurationAggregateProgress ConfigurationPairAggregator::Progress(const Integer& total_pair_count) const {
  auto result = progress_;
  result.total_pair_count = total_pair_count;
  return result;
}

ConfigurationPairAggregate ConfigurationPairAggregator::Finish(ConfigurationPairStopReason reason,
                                                              const Integer& total_pair_count) const {
  ValidateReason(reason);
  if (total_pair_count < progress_.processed_pair_count || total_pair_count < 0) throw std::invalid_argument("pair counts must cover the full space");
  if (progress_.succeeded_count + progress_.truncated_count + progress_.failed_count != progress_.processed_pair_count) {
    throw std::logic_error("pair statuses must sum to processed pair count");
  }
  if (win_ + loss_ + draw_ != progress_.completed_weight) throw std::logic_error("weighted probabilities must sum exactly to completed weight");
  if (progress_.completed_weight < Rational{0} || progress_.completed_weight > progress_.attempted_weight || progress_.attempted_weight > Rational{1}) {
    throw std::invalid_argument("coverage weights must satisfy completed <= attempted <= 1");
  }
  auto complexity = complexity_;
  complexity.final_win_numerator_bits = BitLength(win_.numerator());
  complexity.final_win_denominator_bits = BitLength(win_.denominator());
  complexity.final_loss_numerator_bits = BitLength(loss_.numerator());
  complexity.final_loss_denominator_bits = BitLength(loss_.denominator());
  complexity.final_draw_numerator_bits = BitLength(draw_.numerator());
  complexity.final_draw_denominator_bits = BitLength(draw_.denominator());
  return {progress_.processed_pair_count == total_pair_count ? ConfigurationPairStopReason::completed : reason,
          Progress(total_pair_count), Integer{total_pair_count - progress_.processed_pair_count}, win_, loss_, draw_,
          win_entries_, expected_entries_, node_entries_, std::move(complexity)};
}
} // namespace pbi
