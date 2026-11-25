#include "graph_explanation_contract.hpp"

namespace pbi::contract {
namespace {
/// @param stop 同源令牌；取消不交付半份解释。
void Check(CancellationToken stop) { if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "graph explanation cancelled"); }
/// @param value 原精确分数；@return 复用唯一ties-even展示，移除原归因协议不存在的percent。
Json Probability(const Rational& value) { auto result = ExactProbabilityJson(value); result.erase("percent"); return result; }
} // namespace
Json RootActionPairExplanationJson(const RootActionPairExplanation& value, CancellationToken stop) {
  auto buckets = Json::array();
  for (const auto& bucket : value.buckets) {
    Check(stop);
    buckets.push_back({{"attacker_move_id", bucket.attacker_move_id ? Json(*bucket.attacker_move_id) : Json(nullptr)},
        {"defender_move_id", bucket.defender_move_id ? Json(*bucket.defender_move_id) : Json(nullptr)},
        {"probability", Probability(bucket.probability)}, {"attacker_win_contribution", Probability(bucket.attacker_win_contribution)},
        {"defender_win_contribution", Probability(bucket.defender_win_contribution)}, {"draw_contribution", Probability(bucket.draw_contribution)},
        {"conditional_attacker_win", Probability(bucket.conditional_attacker_win)}, {"conditional_defender_win", Probability(bucket.conditional_defender_win)},
        {"conditional_draw", Probability(bucket.conditional_draw)},
        {"representative_target_node_id", bucket.representative_target_node_id ? Json(bucket.representative_target_node_id->value) : Json(nullptr)},
        {"path_count", bucket.path_count}});
  }
  Check(stop);
  return {{"version", "battle-inference.explanation.v1"}, {"basis", "root-action-pair-attribution"}, {"coverage", Probability(value.coverage)},
      {"root", {{"node_id", value.root.value}, {"attacker_win", Probability(value.root_values.attacker_win)},
          {"defender_win", Probability(value.root_values.defender_win)}, {"draw", Probability(value.root_values.draw)}}},
      {"buckets", std::move(buckets)}, {"omitted_bucket_count", value.omitted_bucket_count}, {"graph", {{"nodes", value.node_count}, {"edges", value.edge_count}}}};
}
} // namespace pbi::contract
