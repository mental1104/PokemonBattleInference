#include "pbi/battle_graph.hpp"
#include <algorithm>
#include <deque>
#include <limits>
#include <unordered_map>

namespace pbi {
namespace {
/// @param stop 协作取消令牌；已取消时抛出稳定领域取消错误。
void CheckBuildStop(pbi::CancellationToken stop) { if (stop.Requested()) throw GraphBuildCancelled{}; }
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

namespace {
/// 两种原构图用途耦合各自预算/元数据语义，不通过零散bool改变正式探索行为。
enum class GraphPurpose { exploration, configuration_summary };
/// 同一BFS的完整拥有构建材料，仅两个正式friend入口可以封装为不可变BattleGraph。
struct BuildData {
  std::vector<BattleGraphNode> nodes;
  std::vector<BattleGraphEdge> edges;
  std::vector<StrongComponent> components;
  GraphStatistics statistics;
  std::vector<GraphTruncation> truncations;
  std::vector<RootActionEventSummary> root_summaries;
};
/// @param transitions 原完整归一分布；@param stop 取消；@return 原首次StateKey顺序的概率归并，不复制事件。
std::vector<BattleTransition> MergeSummary(std::span<const BattleTransition> transitions, CancellationToken stop) {
  ValidateTransitions(transitions);
  /// 仅保留首次状态及精确概率，不持有原路径，归并辅助内存与唯一状态数相关。
  struct Accumulator { BattleState state; Rational probability; };
  std::vector<Accumulator> states;
  std::unordered_map<StateKey, std::size_t, StateKeyHash> by_key;
  for (const auto& transition : transitions) {
    CheckBuildStop(stop); const auto& value = transition.View();
    const auto [position, inserted] = by_key.emplace(value.state.Key(), states.size());
    if (inserted) states.push_back({value.state, value.probability});
    else states[position->second].probability += value.probability;
  }
  std::vector<BattleTransition> result;
  for (auto& state : states) result.emplace_back(BattleTransitionData{state.probability, std::move(state.state), EventSummary{}, std::nullopt});
  return result;
}
/// @param initial 原初态；@param expand 原回合；@param limits 原预算；@param progress 原进度端口。
/// @param progress_interval 原间隔；@param purpose 明确两种原用途；@param stop 同源取消。
/// @return 同一分类/SCC/统计链产生的材料，summary和full只在原已不同的停止/元数据分支分开。
BuildData Build(BattleState initial, const TransitionExpander& expand, GraphLimits limits,
    const GraphProgressObserver& progress, std::size_t progress_interval, GraphPurpose purpose, CancellationToken stop) {
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
  std::vector<RootActionEventSummary> root_summaries;
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
      const auto merged = purpose == GraphPurpose::exploration ? MergeEquivalentTransitions(transitions) : MergeSummary(transitions, stop);
      std::size_t new_count = 0;
      for (const auto& transition : merged) if (!by_key.contains(transition.View().state.Key())) ++new_count;
      if (limits.max_nodes && (nodes.size() > *limits.max_nodes || new_count > *limits.max_nodes - nodes.size()))
        truncation = GraphTruncation::max_nodes;
      else if (limits.max_edges && (edges.size() > *limits.max_edges || merged.size() > *limits.max_edges - edges.size()))
        truncation = GraphTruncation::max_edges;
      else {
        // 原summary执行端单独保留root完整历史；其他边不持有任何探索历史/来源/前驱。
        const auto root_transitions = purpose == GraphPurpose::configuration_summary && id.value == 0
            ? MergeEquivalentTransitions(transitions) : std::vector<BattleTransition>{};
        std::unordered_map<StateKey, const EventSummary*, StateKeyHash> root_events;
        for (const auto& transition : root_transitions) root_events.emplace(transition.View().state.Key(), &transition.View().events);
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
            nodes.push_back({target, value.state, key, outcome, reason,
                purpose == GraphPurpose::exploration ? std::optional{id} : std::nullopt,
                purpose == GraphPurpose::exploration ? std::optional{edge_id} : std::nullopt});
            if (outcome == GraphOutcome::non_terminal) queue.push_back(target);
          }
          edges.push_back({edge_id, id, target, value.probability, value.events, value.source_key});
          if (const auto original = root_events.find(key); original != root_events.end()) root_summaries.push_back({target, *original->second});
        }
      }
    }
    if (truncation) {
      nodes[id.value].outcome = GraphOutcome::unknown; nodes[id.value].reason = *truncation;
      if (std::find(truncations.begin(), truncations.end(), *truncation) == truncations.end()) truncations.push_back(*truncation);
      if (purpose == GraphPurpose::configuration_summary && *truncation != GraphTruncation::max_turns) {
        // 原SummaryStateGraphBuilder到节点/边预算时把全部尚未展开frontier标unknown并立即停止。
        for (const auto pending : queue) if (nodes[pending.value].outcome == GraphOutcome::non_terminal) {
          nodes[pending.value].outcome = GraphOutcome::unknown; nodes[pending.value].reason = *truncation;
        }
        queue.clear(); break;
      }
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
  return {std::move(nodes), std::move(edges), std::move(components), statistics, std::move(truncations), std::move(root_summaries)};
}
} // namespace
BattleGraph BuildBattleGraph(BattleState initial, const TransitionExpander& expand, GraphLimits limits,
    const GraphProgressObserver& progress, std::size_t progress_interval, CancellationToken stop) {
  auto data = Build(std::move(initial), expand, limits, progress, progress_interval, GraphPurpose::exploration, stop);
  return BattleGraph{std::move(data.nodes), std::move(data.edges), std::move(data.components), data.statistics, std::move(data.truncations)};
}
SummaryBattleGraph BuildSummaryBattleGraph(BattleState initial, const TransitionExpander& expand, GraphLimits limits,
    const GraphProgressObserver& progress, std::size_t progress_interval, CancellationToken stop) {
  auto data = Build(std::move(initial), expand, limits, progress, progress_interval, GraphPurpose::configuration_summary, stop);
  return {BattleGraph{std::move(data.nodes), std::move(data.edges), std::move(data.components), data.statistics, std::move(data.truncations)}, std::move(data.root_summaries)};
}
} // namespace pbi
