#pragma once

#include "pbi/state.hpp"
#include <compare>
#include <span>
#include "pbi/cancellation.hpp"
#include <variant>

namespace pbi {
/// 图节点 ID 与 SCC ID 是不同索引，防止跨索引空间误用。
struct GraphNodeId {
  std::size_t value;
  /// @param other 同一图中的节点索引；@return 数值全序比较。
  auto operator<=>(const GraphNodeId& other) const = default;
};
/// 一次分析内部的连续强连通分量标识。
struct ComponentId {
  std::size_t value;
  /// @param other 同次分析的分量索引；@return 数值全序比较。
  auto operator<=>(const ComponentId& other) const = default;
};
/// 胜负边界与截断未知明确分开，保护上限不能变成数学平局。
enum class GraphOutcome { attacker_win, defender_win, draw, non_terminal, unknown };
/// 原状态图的三种构建预算保护原因。
enum class GraphTruncation { max_turns, max_nodes, max_edges };
/// SCC 分类保留开放循环、封闭循环及可到达终局循环的不同语义。
enum class ComponentKind { acyclic, closed_cycle, terminal_reachable_cycle, open_unresolved_cycle };
/// 求解只需不可变领域节点投影，不读取数据库/HTTP 或依赖展示状态。
struct ProbabilityNode {
  GraphOutcome outcome;
  CycleResolution cycle_resolution = CycleResolution::declare_draw;
};
/// 一条完整回合级带权有向边，重复平行边仍各自保留权重。
struct ProbabilityEdge {
  GraphNodeId source;
  GraphNodeId target;
  Rational probability;
};
/// 已验证且拥有全部拓扑的有限概率图；节点 ID 为 nodes 的下标。
class ProbabilityGraph {
public:
  /// @param nodes 拥有的非空节点列表；@param edges 拥有的正概率边列表。
  /// @param root 合法根节点；@param truncations 有序去重的构图截断原因。
  /// 非终局出边必须精确和为 1；未知/终局允许无出边。非法图抛 invalid_argument。
  ProbabilityGraph(std::vector<ProbabilityNode> nodes, std::vector<ProbabilityEdge> edges,
                   GraphNodeId root = {0}, std::vector<GraphTruncation> truncations = {});
  /// @return 只读节点视图，借用不超过本图生命周期。
  [[nodiscard]] std::span<const ProbabilityNode> Nodes() const noexcept { return nodes_; }
  /// @return 只读完整边视图，借用不超过本图生命周期。
  [[nodiscard]] std::span<const ProbabilityEdge> Edges() const noexcept { return edges_; }
  /// @return 当前图内的稳定根索引。
  [[nodiscard]] GraphNodeId Root() const noexcept { return root_; }
  /// @return 有序截断原因只读视图；空列表仍需检查 unknown 节点。
  [[nodiscard]] std::span<const GraphTruncation> Truncations() const noexcept { return truncations_; }
private:
  std::vector<ProbabilityNode> nodes_;
  std::vector<ProbabilityEdge> edges_;
  GraphNodeId root_;
  std::vector<GraphTruncation> truncations_;
};
/// SCC 的完整只读结果投影，成员和出分量 ID 均升序排列。
struct StrongComponent {
  ComponentId id;
  std::vector<GraphNodeId> nodes;
  ComponentKind kind;
  std::vector<ComponentId> outgoing;
  bool reaches_terminal;
};
/// 有限期望回合只包含精确分数，永不把无限性编码为机器最大值。
struct FiniteExpectedTurns { Rational value; };
/// 正概率进入封闭循环时的无限期望标记。
struct InfiniteExpectedTurns {};
/// 完整数学解，观察方明确，所有概率精确且 win+loss+draw=1。
struct SolvedGraph {
  BattleSide observer;
  Rational win;
  Rational loss;
  Rational draw;
  Rational closed_cycle;
  std::variant<FiniteExpectedTurns, InfiniteExpectedTurns> expected_turns;
};
/// 未完成求解原因，不能携带貌似成功的部分概率。
enum class GraphSolveStatus { incomplete_graph, resource_limit_exceeded, singular_system, cancelled };
/// 失败结果只携带类别和稳定诊断，不提供数值默认值。
struct UnavailableGraph { GraphSolveStatus status; std::vector<std::string> diagnostics; };
/// 使用互斥结果使不可用状态不能被当作零胜率。
using GraphSolution = std::variant<SolvedGraph, UnavailableGraph>;
/// 同一次精确求解中一个节点的吸收值，固定按攻击方/防守方而非调用方视角表达。
struct GraphNodeAbsorption {
  Rational attacker_win;
  Rational defender_win;
  Rational draw;
  Rational closed_cycle;
  Rational expected_steps_to_boundary;
};
/// 全节点要么同时完整求解，要么整体不可用；归因不能混用部分或默认零值。
using GraphNodeSolution = std::variant<std::vector<GraphNodeAbsorption>, UnavailableGraph>;

/// 迭代 Kosaraju 分解，无递归深度限制，不修改输入图。
/// @param graph 已验证只读图；@param stop 可空取消令牌，取消抛 runtime_error。
/// @return 每节点恰好出现一次的稳定 SCC 列表。
[[nodiscard]] std::vector<StrongComponent> AnalyzeComponents(const ProbabilityGraph& graph, pbi::CancellationToken stop = {});
/// 复用唯一逆拓扑/高斯求解链，供原根概率与原根行动归因共用全节点事实。
/// @param graph 只读完整图；@param max_equation_nodes 原高斯瞬态上限，null表示不限。
/// @param stop 同源取消；@return 按原节点下标拥有的完整吸收向量或既有不可用结果。
[[nodiscard]] GraphNodeSolution SolveGraphNodes(const ProbabilityGraph& graph,
    std::optional<std::size_t> max_equation_nodes = std::nullopt, CancellationToken stop = {});
/// 用逆拓扑递推或精确高斯消元求吸收概率，封闭 SCC 单独记录无限期望。
/// @param graph 只读完整或明确截断图；@param observer 概率观察方。
/// @param max_equation_nodes 高斯消元的瞬态节点上限，null 表示不限，不限制 DAG。
/// @param stop 协作取消令牌，每轮图遍历和消元检查，取消结果不含部分概率。
/// @return 完整精确解或明确的未完成结果，非法上限/观察方抛 invalid_argument。
[[nodiscard]] GraphSolution SolveGraph(const ProbabilityGraph& graph, BattleSide observer = BattleSide::attacker,
    std::optional<std::size_t> max_equation_nodes = std::nullopt, pbi::CancellationToken stop = {});
} // namespace pbi
