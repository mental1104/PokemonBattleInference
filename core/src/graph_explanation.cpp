#include "pbi/graph_explanation.hpp"
#include <algorithm>
#include <map>

namespace pbi {
namespace {
/// @param stop 同源令牌；取消整体失败，不输出部分桶或默认概率。
void Check(CancellationToken stop) { if (stop.Requested()) throw std::runtime_error("graph explanation cancelled"); }
/// @param history 一条原完整路径；@return 原MOVE_USED双侧ID，不能使用selected推测被阻断的动作。
std::pair<std::optional<std::int64_t>, std::optional<std::int64_t>> ActionPair(const WeightedEventPath& history) {
  std::pair<std::optional<std::int64_t>, std::optional<std::int64_t>> result;
  for (const auto& event : history.events) if (const auto* battle = std::get_if<BattleEvent>(&event)) {
    const auto& data = battle->View();
    if (data.kind != BattleEventKind::move_used || !data.actor) continue;
    auto& move = *data.actor == BattleSide::attacker ? result.first : result.second;
    if (!move) move = data.move_id;
  }
  return result;
}
} // namespace

RootActionPairExplanation ExplainRootActionPairs(const BattleGraph& graph,
    std::span<const RootActionEventSummary> root_summaries, std::size_t max_buckets, CancellationToken stop) {
  Check(stop);
  if (max_buckets == 0) throw std::invalid_argument("max_buckets must be positive");
  const auto solution = SolveGraphNodes(graph.Topology(), std::nullopt, stop);
  Check(stop);
  const auto* values = std::get_if<std::vector<GraphNodeAbsorption>>(&solution);
  if (!values) throw std::invalid_argument("root action explanation requires a completely solved graph");
  std::map<std::size_t, const EventSummary*> overrides;
  for (const auto& summary : root_summaries) {
    Check(stop);
    if (summary.target.value >= graph.Nodes().size()) throw std::invalid_argument("root event summary target is outside graph");
    overrides.insert_or_assign(summary.target.value, &summary.events);
  }
  using ActionIds = std::pair<std::optional<std::int64_t>, std::optional<std::int64_t>>;
  std::map<ActionIds, std::size_t> by_action;
  std::vector<RootActionPairBucket> buckets;
  const GraphNodeId root{0};
  for (const auto& edge : graph.Edges()) {
    Check(stop);
    if (edge.source != root) continue;
    const auto override = overrides.find(edge.target.value);
    const auto& events = override == overrides.end() ? edge.events : *override->second;
    const auto& successor = values->at(edge.target.value);
    for (const auto& history : events.Paths()) {
      Check(stop);
      const auto action = ActionPair(history);
      const auto [position, inserted] = by_action.try_emplace(action, buckets.size());
      if (inserted) {
        RootActionPairBucket bucket; bucket.attacker_move_id = action.first; bucket.defender_move_id = action.second;
        bucket.representative_target_node_id = edge.target; buckets.push_back(std::move(bucket));
      }
      auto& bucket = buckets[position->second];
      const Rational probability = edge.probability * history.probability;
      bucket.probability += probability;
      bucket.attacker_win_contribution += probability * successor.attacker_win;
      bucket.defender_win_contribution += probability * successor.defender_win;
      bucket.draw_contribution += probability * successor.draw;
      ++bucket.path_count;
    }
  }
  Rational coverage{0};
  for (auto& bucket : buckets) {
    Check(stop); coverage += bucket.probability;
    if (bucket.probability != Rational{0}) {
      bucket.conditional_attacker_win = bucket.attacker_win_contribution / bucket.probability;
      bucket.conditional_defender_win = bucket.defender_win_contribution / bucket.probability;
      bucket.conditional_draw = bucket.draw_contribution / bucket.probability;
    }
  }
  std::stable_sort(buckets.begin(), buckets.end(), [](const auto& left, const auto& right) {
    return left.attacker_win_contribution > right.attacker_win_contribution;
  });
  const auto omitted = buckets.size() > max_buckets ? buckets.size() - max_buckets : 0;
  if (omitted != 0) buckets.resize(max_buckets);
  return {coverage, root, values->at(root.value), std::move(buckets), omitted, graph.Nodes().size(), graph.Edges().size()};
}
} // namespace pbi
