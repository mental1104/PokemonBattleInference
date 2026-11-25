#pragma once
#include "pbi/battle_graph.hpp"

namespace pbi {
/// 原完成页的一组实际执行招式归因；blocked/struggle缺少move ID时保持null。
struct RootActionPairBucket {
  std::optional<std::int64_t> attacker_move_id;
  std::optional<std::int64_t> defender_move_id;
  Rational probability{0};
  Rational attacker_win_contribution{0};
  Rational defender_win_contribution{0};
  Rational draw_contribution{0};
  Rational conditional_attacker_win{0};
  Rational conditional_defender_win{0};
  Rational conditional_draw{0};
  std::optional<GraphNodeId> representative_target_node_id;
  std::size_t path_count = 0;
};
/// 原root-action-pair-attribution完整领域结果，不用版本metadata替代业务归因。
struct RootActionPairExplanation {
  Rational coverage;
  GraphNodeId root;
  GraphNodeAbsorption root_values;
  std::vector<RootActionPairBucket> buckets;
  std::size_t omitted_bucket_count;
  std::size_t node_count;
  std::size_t edge_count;
};
/// @param graph 原正式/summary图，所有节点必须可完整求解；借用至调用结束。
/// @param root_summaries 原summary端保留的target历史，空时直接借用正式root边历史，不复制事件。
/// @param max_buckets 原默认12，必须正数；@param stop 同源取消。
/// @return 按攻击方胜贡献稳定降序的原完整归因，覆盖率包含未显示桶，不重归一。
/// @throws std::invalid_argument 非法上限/target/不可用图；std::runtime_error 取消。
[[nodiscard]] RootActionPairExplanation ExplainRootActionPairs(const BattleGraph& graph,
    std::span<const RootActionEventSummary> root_summaries = {}, std::size_t max_buckets = 12, CancellationToken stop = {});
} // namespace pbi
