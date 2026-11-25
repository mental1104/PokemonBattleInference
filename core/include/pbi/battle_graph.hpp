#pragma once

#include "pbi/graph.hpp"
#include "pbi/transitions.hpp"
#include <stdexcept>

namespace pbi {
/// 原战斗分支的确定终止原因，与构图预算截断分开。
enum class BattleTermination { knockout, mutual_knockout, no_legal_action, cycle_guard };
/// 图节点可能是数学终局或运行保护未知，不能用同一平局值代替。
using GraphStopReason = std::variant<BattleTermination, GraphTruncation>;
/// 完整图的独立边索引，不得误作节点或 SCC 索引。
struct GraphEdgeId {
  std::size_t value;
  /// @param other 同图内边索引；@return 索引全序。
  auto operator<=>(const GraphEdgeId& other) const = default;
};
/// BFS 首次发现的不可变状态及其稳定代表路径。
struct BattleGraphNode {
  GraphNodeId id;
  BattleState state;
  StateKey key;
  GraphOutcome outcome;
  std::optional<GraphStopReason> reason;
  std::optional<GraphNodeId> predecessor_node;
  std::optional<GraphEdgeId> predecessor_edge;
};
/// 完整回合随机边，保留同状态下替代事件路径和条件权重。
struct BattleGraphEdge {
  GraphEdgeId id;
  GraphNodeId source;
  GraphNodeId target;
  Rational probability;
  EventSummary events;
  std::optional<std::string> source_key;
};
/// 原summary执行端仅额外保存root后继的完整历史，其他深层边不保留探索元数据。
struct RootActionEventSummary { GraphNodeId target; EventSummary events; };
/// 构图限额；null 节点/边不限，null max_turns 继承初始状态的规则值。
struct GraphLimits {
  std::optional<std::size_t> max_nodes;
  std::optional<std::size_t> max_edges;
  std::optional<std::int64_t> max_turns;
};
/// 各类节点数量，不把未决与未知计入确定胜负。
struct GraphTerminalCounts { std::size_t attacker_wins = 0, defender_wins = 0, draws = 0, non_terminal = 0, unknown = 0; };
/// 完成构图后的真实规模与 SCC 分类统计。
struct GraphStatistics {
  std::size_t nodes;
  std::size_t edges;
  std::int64_t max_turn_number;
  GraphTerminalCounts terminal_counts;
  std::size_t closed_cycles;
  std::size_t terminal_reachable_cycles;
};
/// 进度帧的两个稳定阶段。
enum class GraphBuildPhase { building, built };
/// 不含完整状态的轻量进度，Worker 可以直接持久化实际计数。
struct GraphBuildProgress {
  GraphBuildPhase phase;
  std::size_t nodes;
  std::size_t edges;
  std::size_t expanded;
  std::size_t frontier;
};
/// 同步观察进度的借用回调；只在本次 Build 调用中执行，异常自然传播。
using GraphProgressObserver = std::function<void(const GraphBuildProgress&)>;
/// 构图取消不返回不完整结果冒充完成，由适配层映射显式取消。
class GraphBuildCancelled final : public std::runtime_error {
public:
  /// 无参数；稳定 ASCII 取消原因，不持有图或跨进程状态。
  GraphBuildCancelled() : std::runtime_error("battle graph build cancelled") {}
};
class BattleGraph;
struct SummaryBattleGraph;
/// 按 StateKey 的实际完整字节相等性 BFS 去重，不使用递归或裸哈希作为节点身份。
/// @param initial 拥有的初始不可变状态；@param expand 实际完整回合扩展器，不得修改父节点。
/// @param limits 节点/边/回合保护；@param progress 可空同步进度回调。
/// @param progress_interval 每多少个已展开节点报告一次，必须正数；@param stop 协作取消。
/// @return 原子完成的图；每节点超预算时整体保留为 unknown，不添加半套出边。
/// @throws GraphBuildCancelled 已请求取消；其他异常包括非法分布和扩展器自身错误。
[[nodiscard]] BattleGraph BuildBattleGraph(BattleState initial, const TransitionExpander& expand, GraphLimits limits = {},
    const GraphProgressObserver& progress = {}, std::size_t progress_interval = 100, pbi::CancellationToken stop = {});
/// 原任务轻量构图：预算命中后停止全部frontier，保留unknown质量，不继续扩展或伪造draw。
/// @param initial 拥有初态；@param expand 原完整回合扩展器；@param limits 原图预算。
/// @param progress 原进度端口；@param progress_interval 原默认200；@param stop 同源取消。
/// @return 不含探索边历史/前驱的图与独立root历史，用于同源精确求解和原行动归因。
[[nodiscard]] SummaryBattleGraph BuildSummaryBattleGraph(BattleState initial, const TransitionExpander& expand, GraphLimits limits = {},
    const GraphProgressObserver& progress = {}, std::size_t progress_interval = 200, CancellationToken stop = {});

/// 完整拥有 BFS 图/路径/事件，只有正式构建器能创建，不泄露可写图视图。
class BattleGraph {
public:
  /// @return 全部只读节点，借用受本图生命周期约束。
  [[nodiscard]] std::span<const BattleGraphNode> Nodes() const noexcept { return nodes_; }
  /// @return 全部只读随机边，借用受本图生命周期约束。
  [[nodiscard]] std::span<const BattleGraphEdge> Edges() const noexcept { return edges_; }
  /// @return 完整 SCC 元数据，编号保留首次迭代遍历顺序。
  [[nodiscard]] std::span<const StrongComponent> Components() const noexcept { return components_; }
  /// @return 最终真实统计只读视图，不统计推测的未来节点。
  [[nodiscard]] const GraphStatistics& Statistics() const noexcept { return statistics_; }
  /// @return 首次出现顺序的构图保护原因，空列表表示未截断。
  [[nodiscard]] std::span<const GraphTruncation> Truncations() const noexcept { return truncations_; }
  /// @return 可交给同一精确 SolveGraph 的拥有拓扑投影，事件仍保留在本图中。
  [[nodiscard]] ProbabilityGraph Topology() const;
  /// @param target 合法目标节点；@return 首次发现的根到目标路径；越界抛 invalid_argument。
  [[nodiscard]] std::vector<GraphNodeId> RepresentativePath(GraphNodeId target) const;
private:
  friend BattleGraph BuildBattleGraph(BattleState, const TransitionExpander&, GraphLimits, const GraphProgressObserver&, std::size_t, pbi::CancellationToken);
  friend SummaryBattleGraph BuildSummaryBattleGraph(BattleState, const TransitionExpander&, GraphLimits, const GraphProgressObserver&, std::size_t, CancellationToken);
  /// @param nodes 完整拥有节点；@param edges 完整拥有边；@param components SCC 元数据。
  /// @param statistics 真实统计；@param truncations 有序去重保护原因，仅构建器创建。
  BattleGraph(std::vector<BattleGraphNode> nodes, std::vector<BattleGraphEdge> edges, std::vector<StrongComponent> components,
      GraphStatistics statistics, std::vector<GraphTruncation> truncations);
  std::vector<BattleGraphNode> nodes_;
  std::vector<BattleGraphEdge> edges_;
  std::vector<StrongComponent> components_;
  GraphStatistics statistics_;
  std::vector<GraphTruncation> truncations_;
};
/// 轻量任务图与root归因事实分别拥有，完整探索图的布局与默认行为不变。
struct SummaryBattleGraph { BattleGraph graph; std::vector<RootActionEventSummary> root_summaries; };
} // namespace pbi
