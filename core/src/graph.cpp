#include "pbi/graph.hpp"
#include <algorithm>
#include <array>
#include <deque>
#include <stdexcept>

namespace pbi {
namespace {
/// 内部取消信号；公开求解入口将它转换为无部分概率的取消结果。
class CancelledSignal final : public std::runtime_error {
public:
  /// 无输入；稳定 ASCII 诊断供直接 SCC 调用方识别取消。
  CancelledSignal() : std::runtime_error("graph computation cancelled") {}
};
/// 精确方程找不到非零主元；不把奇异结果近似成浮点解。
struct SingularSignal {};
/// @param stop 借用取消令牌；请求取消时抛出内部信号，不修改任何调用方数据。
void CheckStop(std::stop_token stop) { if (stop.stop_requested()) throw CancelledSignal{}; }
/// @param outcome 稳定节点类别；@return 是否为确定胜负或显式平局。
bool IsTerminal(GraphOutcome outcome) {
  return outcome == GraphOutcome::attacker_win || outcome == GraphOutcome::defender_win || outcome == GraphOutcome::draw;
}
/// 按节点索引的完整正/反向边列表，拥有自己的索引，不保存悬空图视图。
struct GraphIndex {
  std::vector<std::vector<std::size_t>> outgoing;
  std::vector<std::vector<std::size_t>> incoming;
  /// @param graph 只读合法图；@param stop 取消令牌；只创建辅助索引。
  GraphIndex(const ProbabilityGraph& graph, std::stop_token stop)
      : outgoing(graph.Nodes().size()), incoming(graph.Nodes().size()) {
    for (std::size_t id = 0; id < graph.Edges().size(); ++id) {
      CheckStop(stop);
      const auto& edge = graph.Edges()[id];
      outgoing[edge.source.value].push_back(id);
      incoming[edge.target.value].push_back(id);
    }
  }
};
/// @param graph 只读图；@param index 边索引；@param stop 取消令牌。
/// @return Kosaraju 第一遍显式 DFS 完成顺序；深链不会使用递归栈。
std::vector<std::size_t> FinishOrder(const ProbabilityGraph& graph, const GraphIndex& index, std::stop_token stop) {
  std::vector<bool> visited(graph.Nodes().size());
  std::vector<std::size_t> result;
  for (std::size_t start = 0; start < visited.size(); ++start) {
    CheckStop(stop);
    if (visited[start]) continue;
    visited[start] = true;
    std::vector<std::pair<std::size_t, std::size_t>> stack{{start, 0}};
    while (!stack.empty()) {
      CheckStop(stop);
      auto& [node, next] = stack.back();
      if (next == index.outgoing[node].size()) {
        result.push_back(node); stack.pop_back(); continue;
      }
      const auto child = graph.Edges()[index.outgoing[node][next++]].target.value;
      if (!visited[child]) { visited[child] = true; stack.emplace_back(child, 0); }
    }
  }
  return result;
}
/// 节点吸收值按攻击胜、防守胜、平局、封闭循环、到边界期望步数固定排列。
using NodeValues = std::array<Rational, 5>;
/// @param graph 只读图；@param components 已分类 SCC；@return 所有数学吸收边界，其余为 null。
std::vector<std::optional<NodeValues>> BoundaryValues(const ProbabilityGraph& graph, std::span<const StrongComponent> components) {
  std::vector<bool> closed(graph.Nodes().size());
  for (const auto& component : components) if (component.kind == ComponentKind::closed_cycle)
    for (const auto id : component.nodes) closed[id.value] = true;
  std::vector<std::optional<NodeValues>> result(graph.Nodes().size());
  for (std::size_t id = 0; id < result.size(); ++id) {
    switch (graph.Nodes()[id].outcome) {
      case GraphOutcome::attacker_win: result[id] = NodeValues{Rational{1}, Rational{0}, Rational{0}, Rational{0}, Rational{0}}; break;
      case GraphOutcome::defender_win: result[id] = NodeValues{Rational{0}, Rational{1}, Rational{0}, Rational{0}, Rational{0}}; break;
      case GraphOutcome::draw: result[id] = NodeValues{Rational{0}, Rational{0}, Rational{1}, Rational{closed[id] ? 1 : 0}, Rational{0}}; break;
      default:
        // 无出口循环在两种 cycle_resolution 下均为数学平局，且有无限期望。
        if (closed[id]) result[id] = NodeValues{Rational{0}, Rational{0}, Rational{1}, Rational{1}, Rational{0}};
        break;
    }
  }
  return result;
}
/// @param graph 只读图；@param index 出边索引；@param values 已知吸收边界；@param stop 取消令牌。
/// @return 瞬态图的完整拓扑序；存在有出口循环则返回 null，不混同封闭 SCC。
std::optional<std::vector<std::size_t>> TransientOrder(const ProbabilityGraph& graph, const GraphIndex& index,
    const std::vector<std::optional<NodeValues>>& values, std::stop_token stop) {
  std::vector<std::size_t> indegree(values.size());
  std::size_t count = 0;
  for (std::size_t node = 0; node < values.size(); ++node) {
    CheckStop(stop);
    if (values[node]) continue;
    ++count;
    for (const auto edge_id : index.outgoing[node]) {
      const auto target = graph.Edges()[edge_id].target.value;
      if (!values[target]) ++indegree[target];
    }
  }
  std::deque<std::size_t> queue;
  for (std::size_t id = 0; id < values.size(); ++id) if (!values[id] && indegree[id] == 0) queue.push_back(id);
  std::vector<std::size_t> ordered;
  while (!queue.empty()) {
    CheckStop(stop);
    const auto node = queue.front(); queue.pop_front(); ordered.push_back(node);
    for (const auto edge_id : index.outgoing[node]) {
      const auto target = graph.Edges()[edge_id].target.value;
      if (!values[target] && --indegree[target] == 0) queue.push_back(target);
    }
  }
  if (ordered.size() != count) return std::nullopt;
  return ordered;
}
/// @param graph 只读图；@param index 出边索引；@param node 当前瞬态节点。
/// @param values 后继均已求解的数组；@return 当前精确值，增加一个完整回合成本。
NodeValues WeightedSuccessors(const ProbabilityGraph& graph, const GraphIndex& index, std::size_t node,
    const std::vector<std::optional<NodeValues>>& values) {
  NodeValues result{}; result[4] = Rational{1};
  for (const auto edge_id : index.outgoing[node]) {
    const auto& edge = graph.Edges()[edge_id];
    const auto& successor = values.at(edge.target.value).value();
    for (std::size_t column = 0; column < result.size(); ++column) result[column] += edge.probability * successor[column];
  }
  return result;
}
/// 精确增广方程的局部拥有者，只在确有循环且预算允许时分配 O(n²) 空间。
class AbsorptionEquations {
public:
  /// @param graph 只读图；@param index 出边；@param boundaries 只读边界；@param transient 连续未知量到节点映射。
  AbsorptionEquations(const ProbabilityGraph& graph, const GraphIndex& index,
      const std::vector<std::optional<NodeValues>>& boundaries, std::vector<std::size_t> transient)
      : nodes_(std::move(transient)), matrix_(nodes_.size(), std::vector<Rational>(nodes_.size() + 5)) {
    std::vector<std::optional<std::size_t>> by_node(boundaries.size());
    for (std::size_t row = 0; row < nodes_.size(); ++row) by_node[nodes_[row]] = row;
    for (std::size_t row = 0; row < nodes_.size(); ++row) {
      matrix_[row][row] = Rational{1}; matrix_[row][nodes_.size() + 4] = Rational{1};
      for (const auto edge_id : index.outgoing[nodes_[row]]) {
        const auto& edge = graph.Edges()[edge_id];
        if (by_node[edge.target.value]) matrix_[row][*by_node[edge.target.value]] -= edge.probability;
        else {
          const auto& value = boundaries[edge.target.value].value();
          for (std::size_t column = 0; column < value.size(); ++column)
            matrix_[row][nodes_.size() + column] += edge.probability * value[column];
        }
      }
    }
  }
  /// @param stop 取消令牌；@return 每个瞬态节点的五项精确值；奇异抛 SingularSignal，不改外部图。
  [[nodiscard]] std::vector<std::pair<std::size_t, NodeValues>> Solve(std::stop_token stop) {
    const auto size = nodes_.size();
    const auto width = size + 5;
    for (std::size_t pivot_column = 0; pivot_column < size; ++pivot_column) {
      CheckStop(stop);
      std::size_t pivot_row = pivot_column;
      while (pivot_row < size && matrix_[pivot_row][pivot_column] == Rational{0}) ++pivot_row;
      if (pivot_row == size) throw SingularSignal{};
      if (pivot_row != pivot_column) std::swap(matrix_[pivot_row], matrix_[pivot_column]);
      const Rational pivot = matrix_[pivot_column][pivot_column];
      for (std::size_t column = pivot_column; column < width; ++column) matrix_[pivot_column][column] /= pivot;
      for (std::size_t row = 0; row < size; ++row) {
        CheckStop(stop);
        if (row == pivot_column || matrix_[row][pivot_column] == Rational{0}) continue;
        const Rational factor = matrix_[row][pivot_column];
        for (std::size_t column = pivot_column; column < width; ++column) matrix_[row][column] -= factor * matrix_[pivot_column][column];
      }
    }
    std::vector<std::pair<std::size_t, NodeValues>> result;
    for (std::size_t row = 0; row < size; ++row) {
      NodeValues value{};
      std::copy_n(matrix_[row].begin() + static_cast<std::ptrdiff_t>(size), 5, value.begin());
      result.emplace_back(nodes_[row], std::move(value));
    }
    return result;
  }
private:
  std::vector<std::size_t> nodes_;
  std::vector<std::vector<Rational>> matrix_;
};
} // namespace

ProbabilityGraph::ProbabilityGraph(std::vector<ProbabilityNode> nodes, std::vector<ProbabilityEdge> edges,
    GraphNodeId root, std::vector<GraphTruncation> truncations)
    : nodes_(std::move(nodes)), edges_(std::move(edges)), root_(root) {
  if (nodes_.empty() || root_.value >= nodes_.size()) throw std::invalid_argument("graph root must be inside a nonempty graph");
  for (const auto& node : nodes_) {
    switch (node.outcome) {
      case GraphOutcome::attacker_win: case GraphOutcome::defender_win: case GraphOutcome::draw:
      case GraphOutcome::non_terminal: case GraphOutcome::unknown: break;
      default: throw std::invalid_argument("unsupported graph node outcome");
    }
    if (node.cycle_resolution != CycleResolution::declare_draw && node.cycle_resolution != CycleResolution::solve_absorption_probability)
      throw std::invalid_argument("unsupported cycle resolution");
  }
  std::vector<Rational> totals(nodes_.size());
  for (const auto& edge : edges_) {
    if (edge.source.value >= nodes_.size() || edge.target.value >= nodes_.size()) throw std::invalid_argument("edge endpoint is outside the graph");
    if (edge.probability <= Rational{0} || edge.probability > Rational{1}) throw std::invalid_argument("edge probability must be in (0, 1]");
    totals[edge.source.value] += edge.probability;
  }
  for (std::size_t id = 0; id < nodes_.size(); ++id)
    if (nodes_[id].outcome == GraphOutcome::non_terminal && totals[id] != Rational{1})
      throw std::invalid_argument("non-terminal outgoing probabilities must sum exactly to 1");
  for (const auto reason : truncations) {
    switch (reason) {
      case GraphTruncation::max_turns: case GraphTruncation::max_nodes: case GraphTruncation::max_edges: break;
      default: throw std::invalid_argument("unsupported graph truncation reason");
    }
    if (std::find(truncations_.begin(), truncations_.end(), reason) == truncations_.end()) truncations_.push_back(reason);
  }
}

std::vector<StrongComponent> AnalyzeComponents(const ProbabilityGraph& graph, std::stop_token stop) {
  CheckStop(stop);
  const GraphIndex index{graph, stop};
  const auto finish = FinishOrder(graph, index, stop);
  std::vector<std::optional<ComponentId>> by_node(graph.Nodes().size());
  std::vector<StrongComponent> components;
  for (auto iterator = finish.rbegin(); iterator != finish.rend(); ++iterator) {
    CheckStop(stop);
    if (by_node[*iterator]) continue;
    const ComponentId id{components.size()};
    StrongComponent component{id, {}, ComponentKind::acyclic, {}, false};
    std::vector<std::size_t> stack{*iterator}; by_node[*iterator] = id;
    while (!stack.empty()) {
      CheckStop(stop);
      const auto node = stack.back(); stack.pop_back(); component.nodes.push_back({node});
      for (const auto edge_id : index.incoming[node]) {
        const auto predecessor = graph.Edges()[edge_id].source.value;
        if (!by_node[predecessor]) { by_node[predecessor] = id; stack.push_back(predecessor); }
      }
    }
    std::sort(component.nodes.begin(), component.nodes.end());
    components.push_back(std::move(component));
  }
  std::vector<bool> cyclic(components.size());
  for (const auto& component : components) cyclic[component.id.value] = component.nodes.size() > 1;
  for (const auto& edge : graph.Edges()) {
    CheckStop(stop);
    const auto source = by_node[edge.source.value].value();
    const auto target = by_node[edge.target.value].value();
    if (source == target) { if (edge.source == edge.target) cyclic[source.value] = true; }
    else components[source.value].outgoing.push_back(target);
  }
  std::vector<std::vector<ComponentId>> predecessors(components.size());
  std::deque<ComponentId> reachable;
  for (auto& component : components) {
    CheckStop(stop);
    std::sort(component.outgoing.begin(), component.outgoing.end());
    component.outgoing.erase(std::unique(component.outgoing.begin(), component.outgoing.end()), component.outgoing.end());
    const bool closed = cyclic[component.id.value] && component.outgoing.empty();
    const bool draw_resolved = closed && std::all_of(component.nodes.begin(), component.nodes.end(), [&](GraphNodeId id) {
      return graph.Nodes()[id.value].cycle_resolution == CycleResolution::declare_draw;
    });
    component.reaches_terminal = draw_resolved || std::any_of(component.nodes.begin(), component.nodes.end(), [&](GraphNodeId id) {
      return IsTerminal(graph.Nodes()[id.value].outcome);
    });
    if (component.reaches_terminal) reachable.push_back(component.id);
    for (const auto target : component.outgoing) predecessors[target.value].push_back(component.id);
  }
  while (!reachable.empty()) {
    CheckStop(stop);
    const auto target = reachable.front(); reachable.pop_front();
    for (const auto source : predecessors[target.value]) if (!components[source.value].reaches_terminal) {
      components[source.value].reaches_terminal = true; reachable.push_back(source);
    }
  }
  for (auto& component : components) {
    if (!cyclic[component.id.value]) component.kind = ComponentKind::acyclic;
    else if (component.outgoing.empty()) component.kind = ComponentKind::closed_cycle;
    else if (component.reaches_terminal) component.kind = ComponentKind::terminal_reachable_cycle;
    else component.kind = ComponentKind::open_unresolved_cycle;
  }
  return components;
}

GraphSolution SolveGraph(const ProbabilityGraph& graph, BattleSide observer,
    std::optional<std::size_t> max_equation_nodes, std::stop_token stop) {
  if (observer != BattleSide::attacker && observer != BattleSide::defender) throw std::invalid_argument("observer must be a BattleSide");
  if (max_equation_nodes && *max_equation_nodes == 0) throw std::invalid_argument("max_equation_nodes must be greater than 0");
  try {
    CheckStop(stop);
    if (!graph.Truncations().empty() || std::any_of(graph.Nodes().begin(), graph.Nodes().end(), [](const ProbabilityNode& node) {
      return node.outcome == GraphOutcome::unknown;
    })) return UnavailableGraph{GraphSolveStatus::incomplete_graph, {"graph is truncated or contains unknown nodes"}};
    const auto components = AnalyzeComponents(graph, stop);
    const GraphIndex index{graph, stop};
    auto values = BoundaryValues(graph, components);
    const auto order = TransientOrder(graph, index, values, stop);
    if (order) {
      for (auto iterator = order->rbegin(); iterator != order->rend(); ++iterator) {
        CheckStop(stop); values[*iterator] = WeightedSuccessors(graph, index, *iterator, values);
      }
    } else {
      std::vector<std::size_t> transient;
      for (std::size_t id = 0; id < values.size(); ++id) if (!values[id]) transient.push_back(id);
      if (max_equation_nodes && transient.size() > *max_equation_nodes)
        return UnavailableGraph{GraphSolveStatus::resource_limit_exceeded, {"transient equation node count exceeds limit"}};
      AbsorptionEquations equations{graph, index, values, std::move(transient)};
      for (auto& [id, value] : equations.Solve(stop)) values[id] = std::move(value);
    }
    const auto& root = values[graph.Root().value].value();
    if (root[0] + root[1] + root[2] != Rational{1}) throw std::logic_error("exact graph probabilities do not sum to 1");
    const auto win_index = observer == BattleSide::attacker ? 0 : 1;
    const auto loss_index = observer == BattleSide::attacker ? 1 : 0;
    std::variant<FiniteExpectedTurns, InfiniteExpectedTurns> expected = FiniteExpectedTurns{root[4]};
    if (root[3] > Rational{0}) expected = InfiniteExpectedTurns{};
    return SolvedGraph{observer, root[win_index], root[loss_index], root[2], root[3], std::move(expected)};
  } catch (const CancelledSignal&) {
    return UnavailableGraph{GraphSolveStatus::cancelled, {"graph computation cancelled"}};
  } catch (const SingularSignal&) {
    return UnavailableGraph{GraphSolveStatus::singular_system, {"exact absorption equation is singular"}};
  }
}
} // namespace pbi
