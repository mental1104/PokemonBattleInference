#include "pbi/battle_graph.hpp"
#include <algorithm>
#include <deque>
#include <limits>
#include <unordered_map>

namespace pbi {
namespace {
/// @param stop 协作取消令牌；已取消时抛出稳定领域取消错误。
void CheckBuildStop(std::stop_token stop) { if (stop.stop_requested()) throw GraphBuildCancelled{}; }
/// @param state 已验证完整节点；@return 确定终局和原因，存活普通阶段不提前判平局。
std::pair<GraphOutcome, std::optional<GraphStopReason>> Classify(const BattleState& state) {
  const auto first = state.View().attacker.View().current_hp == 0;
  const auto second = state.View().defender.View().current_hp == 0;
  if (first && second) return {GraphOutcome::draw, BattleTermination::mutual_knockout};
  if (first) return {GraphOutcome::defender_win, BattleTermination::knockout};
  if (second) return {GraphOutcome::attacker_win, BattleTermination::knockout};
  if (state.View().phase == BattlePhase::terminal) return {GraphOutcome::draw, BattleTermination::no_legal_action};
  return {GraphOutcome::non_terminal, std::nullopt};
}
/// @param nodes 完整只读节点；@param edges 完整只读边；@param truncations 保护原因。
/// @return 求解器需要的拥有拓扑，不包含状态或 JSON 依赖。
ProbabilityGraph ProjectTopology(std::span<const BattleGraphNode> nodes, std::span<const BattleGraphEdge> edges,
    std::span<const GraphTruncation> truncations) {
  std::vector<ProbabilityNode> projected_nodes;
  std::vector<ProbabilityEdge> projected_edges;
  for (const auto& node : nodes) projected_nodes.push_back({node.outcome, node.state.View().rules.View().cycle_resolution});
  for (const auto& edge : edges) projected_edges.push_back({edge.source, edge.target, edge.probability});
  return ProbabilityGraph{std::move(projected_nodes), std::move(projected_edges), {0}, {truncations.begin(), truncations.end()}};
}
/// @param nodes 最终已解析节点；@param edges 完整边；@param components 原始 SCC 分类。
/// @return 最终真实规模与胜负统计，不把截断结果自动计入平局。
GraphStatistics Statistics(std::span<const BattleGraphNode> nodes, std::span<const BattleGraphEdge> edges,
    std::span<const StrongComponent> components) {
  GraphStatistics result{nodes.size(), edges.size(), 1, {}, 0, 0};
  for (const auto& node : nodes) {
    result.max_turn_number = std::max(result.max_turn_number, node.state.View().turn_number);
    switch (node.outcome) {
      case GraphOutcome::attacker_win: ++result.terminal_counts.attacker_wins; break;
      case GraphOutcome::defender_win: ++result.terminal_counts.defender_wins; break;
      case GraphOutcome::draw: ++result.terminal_counts.draws; break;
      case GraphOutcome::non_terminal: ++result.terminal_counts.non_terminal; break;
      case GraphOutcome::unknown: ++result.terminal_counts.unknown; break;
    }
  }
  for (const auto& component : components) {
    if (component.kind == ComponentKind::closed_cycle) ++result.closed_cycles;
    if (component.kind == ComponentKind::terminal_reachable_cycle) ++result.terminal_reachable_cycles;
  }
  return result;
}
} // namespace

BattleGraph::BattleGraph(std::vector<BattleGraphNode> nodes, std::vector<BattleGraphEdge> edges,
    std::vector<StrongComponent> components, GraphStatistics statistics, std::vector<GraphTruncation> truncations)
    : nodes_(std::move(nodes)), edges_(std::move(edges)), components_(std::move(components)), statistics_(std::move(statistics)), truncations_(std::move(truncations)) {}

ProbabilityGraph BattleGraph::Topology() const { return ProjectTopology(nodes_, edges_, truncations_); }

std::vector<GraphNodeId> BattleGraph::RepresentativePath(GraphNodeId target) const {
  if (target.value >= nodes_.size()) throw std::invalid_argument("target node is outside the graph");
  std::vector<GraphNodeId> result;
  for (;;) {
    result.push_back(target);
    if (!nodes_[target.value].predecessor_node) break;
    target = *nodes_[target.value].predecessor_node;
  }
  std::reverse(result.begin(), result.end());
  return result;
}

BattleGraph BuildBattleGraph(BattleState initial, const TransitionExpander& expand, GraphLimits limits,
    const GraphProgressObserver& progress, std::size_t progress_interval, std::stop_token stop) {
  CheckBuildStop(stop);
  if (!expand) throw std::invalid_argument("battle graph requires an actual transition expander");
  if ((limits.max_nodes && *limits.max_nodes == 0) || (limits.max_edges && *limits.max_edges == 0)
      || (limits.max_turns && *limits.max_turns <= 0) || progress_interval == 0)
    throw std::invalid_argument("graph limits and progress interval must be greater than 0");
  const auto max_turns = limits.max_turns ? limits.max_turns : initial.View().rules.View().max_turns;
  const auto [root_outcome, root_reason] = Classify(initial);
  std::vector<BattleGraphNode> nodes{{{0}, initial, initial.Key(), root_outcome, root_reason, std::nullopt, std::nullopt}};
  std::vector<BattleGraphEdge> edges;
  std::unordered_map<StateKey, GraphNodeId, StateKeyHash> by_key{{initial.Key(), {0}}};
  std::deque<GraphNodeId> queue;
  if (root_outcome == GraphOutcome::non_terminal) queue.push_back({0});
  std::vector<GraphTruncation> truncations;
  std::size_t expanded = 0;
  std::size_t next_progress = progress_interval;
  if (progress) progress({GraphBuildPhase::building, nodes.size(), edges.size(), expanded, queue.size()});
  while (!queue.empty()) {
    CheckBuildStop(stop);
    const auto id = queue.front(); queue.pop_front();
    const auto state = nodes[id.value].state;
    if (nodes[id.value].outcome != GraphOutcome::non_terminal) continue;
    std::optional<GraphTruncation> truncation;
    if (max_turns && state.View().turn_number > *max_turns) truncation = GraphTruncation::max_turns;
    else {
      const auto transitions = expand(state); ++expanded; CheckBuildStop(stop);
      if (transitions.empty()) {
        nodes[id.value].outcome = GraphOutcome::draw; nodes[id.value].reason = BattleTermination::no_legal_action;
        continue;
      }
      const auto merged = MergeEquivalentTransitions(transitions);
      std::size_t new_count = 0;
      for (const auto& transition : merged) if (!by_key.contains(transition.View().state.Key())) ++new_count;
      if (limits.max_nodes && (nodes.size() > *limits.max_nodes || new_count > *limits.max_nodes - nodes.size()))
        truncation = GraphTruncation::max_nodes;
      else if (limits.max_edges && (edges.size() > *limits.max_edges || merged.size() > *limits.max_edges - edges.size()))
        truncation = GraphTruncation::max_edges;
      else {
        // 每个节点的全部出边预算检查后一次性提交，不能保留有偏的部分分布。
        for (const auto& transition : merged) {
          CheckBuildStop(stop);
          const auto& value = transition.View();
          const auto key = value.state.Key();
          const GraphEdgeId edge_id{edges.size()};
          const auto [position, inserted] = by_key.emplace(key, GraphNodeId{nodes.size()});
          const auto target = position->second;
          if (inserted) {
            const auto [outcome, reason] = Classify(value.state);
            nodes.push_back({target, value.state, key, outcome, reason, id, edge_id});
            if (outcome == GraphOutcome::non_terminal) queue.push_back(target);
          }
          edges.push_back({edge_id, id, target, value.probability, value.events, value.source_key});
        }
      }
    }
    if (truncation) {
      nodes[id.value].outcome = GraphOutcome::unknown; nodes[id.value].reason = *truncation;
      if (std::find(truncations.begin(), truncations.end(), *truncation) == truncations.end()) truncations.push_back(*truncation);
    }
    if (progress && expanded >= next_progress) {
      progress({GraphBuildPhase::building, nodes.size(), edges.size(), expanded, queue.size()});
      // 显式检查加法容量，极端进度计数不能发生无符号回绕。
      next_progress = expanded <= std::numeric_limits<std::size_t>::max() - progress_interval ? expanded + progress_interval : std::numeric_limits<std::size_t>::max();
    }
  }
  CheckBuildStop(stop);
  std::vector<StrongComponent> components;
  try { components = AnalyzeComponents(ProjectTopology(nodes, edges, truncations), stop); }
  catch (const std::runtime_error&) { CheckBuildStop(stop); throw; }
  for (const auto& component : components) if (component.kind == ComponentKind::closed_cycle)
    for (const auto id : component.nodes) {
      auto& node = nodes[id.value];
      if (node.outcome == GraphOutcome::non_terminal && node.state.View().rules.View().cycle_resolution == CycleResolution::declare_draw) {
        node.outcome = GraphOutcome::draw; node.reason = BattleTermination::cycle_guard;
      }
    }
  const auto statistics = Statistics(nodes, edges, components);
  if (progress) progress({GraphBuildPhase::built, nodes.size(), edges.size(), expanded, 0});
  CheckBuildStop(stop);
  return BattleGraph{std::move(nodes), std::move(edges), components, statistics, std::move(truncations)};
}
} // namespace pbi
