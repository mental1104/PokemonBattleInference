#include "pbi/configuration_aggregate.hpp"
#include <nlohmann/json.hpp>
#include <iostream>

namespace {
using Json = nlohmann::json;
constexpr std::array<std::string_view, 6> reasons{"completed", "configuration-pair-limit", "cumulative-node-limit", "cumulative-edge-limit", "max-failures", "cancelled"};
/// @param value 字符串任意精度整数；@return 完整整数，不经过JSON浮点数。
pbi::Integer Number(const Json& value) { return pbi::Integer{value.get<std::string>()}; }
/// @param value 完整精确分数对象；@return 规范有理数。
pbi::Rational Ratio(const Json& value) { return {Number(value.at("numerator")), Number(value.at("denominator"))}; }
/// @param value 已约分有理数；@return 精确分子/分母文本。
Json Fraction(const pbi::Rational& value) { return {{"numerator", value.numerator().str()}, {"denominator", value.denominator().str()}}; }
/// @param value 有限停止原因；@return 类型化枚举，不默认completed。
pbi::ConfigurationPairStopReason Reason(const Json& value) {
  const auto found = std::ranges::find(reasons, value.get<std::string>());
  if (found == reasons.end()) throw std::invalid_argument("unknown configuration stop reason");
  return static_cast<pbi::ConfigurationPairStopReason>(found - reasons.begin());
}
/// @param value 原单case轻量字段；@return 拥有身份，不保留JSON引用。
pbi::ConfigurationPairIdentity Identity(const Json& value) {
  return {value.at("pair_id").get<std::string>(), value.at("attacker_configuration_id").get<std::string>(), value.at("defender_configuration_id").get<std::string>(),
      value.at("attacker_move_ids").get<std::vector<std::int64_t>>(), value.at("defender_move_ids").get<std::vector<std::int64_t>>()};
}
/// @param value 单case完整协议；@return 原成功/截断/失败互斥摘要，错误组合拒绝。
pbi::ConfigurationPairObservation Observation(const Json& value) {
  std::variant<pbi::ConfigurationPairSuccess, pbi::ConfigurationPairTruncated, pbi::ConfigurationPairFailed> outcome;
  const auto status = value.at("status").get<std::string>();
  if (status == "succeeded") {
    std::variant<pbi::FiniteExpectedTurns, pbi::InfiniteExpectedTurns> turns = pbi::InfiniteExpectedTurns{};
    if (value.at("expected_turns_status") == "finite") turns = pbi::FiniteExpectedTurns{Ratio(value.at("expected_turns"))};
    else if (value.at("expected_turns_status") != "infinite" || !value.at("expected_turns").is_null()) throw std::invalid_argument("invalid successful expected turns");
    outcome = pbi::ConfigurationPairSuccess{Ratio(value.at("win_probability")), Ratio(value.at("loss_probability")), Ratio(value.at("draw_probability")), std::move(turns)};
  } else {
    for (const auto key : {"win_probability", "loss_probability", "draw_probability", "expected_turns"}) {
      if (!value.at(key).is_null()) throw std::invalid_argument("unfinished results cannot carry partial probabilities");
    }
    if (value.at("expected_turns_status") != "unavailable") throw std::invalid_argument("unfinished expected turns must be unavailable");
    if (status == "truncated") outcome = pbi::ConfigurationPairTruncated{};
    else if (status == "failed") outcome = pbi::ConfigurationPairFailed{};
    else throw std::invalid_argument("unknown configuration execution status");
  }
  return {Identity(value), Ratio(value.at("configuration_weight")), std::move(outcome), Number(value.at("node_count")), Number(value.at("edge_count"))};
}
/// @param value 完整当前进度；@return 与原逐case进度相同的全部计数/权重/资源。
Json Progress(const pbi::ConfigurationAggregateProgress& value) {
  return {{"processed_pair_count", value.processed_pair_count.str()}, {"total_pair_count", value.total_pair_count.str()},
      {"succeeded_count", value.succeeded_count.str()}, {"truncated_count", value.truncated_count.str()}, {"failed_count", value.failed_count.str()},
      {"attempted_weight", Fraction(value.attempted_weight)}, {"completed_weight", Fraction(value.completed_weight)},
      {"cumulative_node_count", value.cumulative_node_count.str()}, {"cumulative_edge_count", value.cumulative_edge_count.str()}};
}
/// @param values 有界成功排行；@return 完整轻量身份及所有排行指标，不只比较pairID。
Json Rankings(const std::vector<pbi::ConfigurationPairRankingEntry>& values) {
  auto result = Json::array();
  for (const auto& value : values) result.push_back({{"pair_id", value.identity.pair_id},
      {"attacker_configuration_id", value.identity.attacker_configuration_id}, {"defender_configuration_id", value.identity.defender_configuration_id},
      {"attacker_move_ids", value.identity.attacker_move_ids}, {"defender_move_ids", value.identity.defender_move_ids},
      {"win_probability", Fraction(value.win)}, {"loss_probability", Fraction(value.loss)}, {"draw_probability", Fraction(value.draw)},
      {"expected_turns", value.expected_turns ? Fraction(*value.expected_turns) : Json(nullptr)},
      {"node_count", value.node_count.str()}, {"edge_count", value.edge_count.str()}});
  return result;
}
/// @param request 完整执行结果流；@return 真实Core每步进度和最终完整聚合。
Json Run(const Json& request) {
  pbi::ConfigurationPairAggregator aggregator{request.at("top_k").get<std::size_t>()};
  const auto total = Number(request.at("total_pair_count"));
  auto progresses = Json::array();
  for (const auto& value : request.at("results")) {
    aggregator.Add(Observation(value));
    progresses.push_back(Progress(aggregator.Progress(total)));
  }
  const auto value = aggregator.Finish(Reason(request.at("stop_reason")), total);
  auto result = Progress(value.progress);
  const auto& bits = value.fraction_complexity;
  result.update(Json{{"stop_reason", reasons.at(static_cast<std::size_t>(value.stop_reason))}, {"unprocessed_pair_count", value.unprocessed_pair_count.str()},
      {"weighted_win_probability", Fraction(value.weighted_win)}, {"weighted_loss_probability", Fraction(value.weighted_loss)}, {"weighted_draw_probability", Fraction(value.weighted_draw)},
      {"top_win_probability", Rankings(value.top_win_probability)}, {"top_expected_turns", Rankings(value.top_expected_turns)}, {"top_node_count", Rankings(value.top_node_count)},
      {"fraction_complexity", {{"observed_fraction_count", bits.observed_fraction_count.str()}, {"max_numerator_bits", bits.max_numerator_bits}, {"max_denominator_bits", bits.max_denominator_bits},
      {"final_win_numerator_bits", bits.final_win_numerator_bits}, {"final_win_denominator_bits", bits.final_win_denominator_bits},
      {"final_loss_numerator_bits", bits.final_loss_numerator_bits}, {"final_loss_denominator_bits", bits.final_loss_denominator_bits},
      {"final_draw_numerator_bits", bits.final_draw_numerator_bits}, {"final_draw_denominator_bits", bits.final_draw_denominator_bits}}}});
  return {{"progresses", std::move(progresses)}, {"aggregate", std::move(result)}};
}
} // namespace
/// 无参数；逐行聚合真实输入，异常整体返回，不模拟Python业务运行。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << Run(Json::parse(line)).dump() << '\n'; }
    catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
