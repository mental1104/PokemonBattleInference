#include "pbi/graph.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param source 起点；@param target 终点；@param probability 精确边概率；@return 测试完整边值。
ProbabilityEdge Edge(std::size_t source, std::size_t target, Rational probability) {
  return {{source}, {target}, std::move(probability)};
}
} // namespace

/// 无环图的概率和完整回合期望用逆拓扑精确求解，观察方只交换胜负。
TEST(Graph, AcyclicExactProbabilitiesAndExpectedTurns) {
  const ProbabilityGraph graph{{{GraphOutcome::non_terminal}, {GraphOutcome::non_terminal},
      {GraphOutcome::attacker_win}, {GraphOutcome::defender_win}},
      {Edge(0, 1, Rational{2, 3}), Edge(0, 3, Rational{1, 3}), Edge(1, 2, Rational{1, 2}), Edge(1, 3, Rational{1, 2})}};
  const auto solution = SolveGraph(graph, BattleSide::attacker, 1);
  ASSERT_TRUE(std::holds_alternative<SolvedGraph>(solution));
  const auto& solved = std::get<SolvedGraph>(solution);
  EXPECT_EQ(solved.win, (Rational{1, 3})); EXPECT_EQ(solved.loss, (Rational{2, 3}));
  EXPECT_EQ(solved.draw, Rational{0}); EXPECT_EQ(solved.closed_cycle, Rational{0});
  EXPECT_EQ(std::get<FiniteExpectedTurns>(solved.expected_turns).value, (Rational{5, 3}));
  const auto reverse = std::get<SolvedGraph>(SolveGraph(graph, BattleSide::defender));
  EXPECT_EQ(reverse.win, solved.loss); EXPECT_EQ(reverse.loss, solved.win);
  EXPECT_EQ(graph.Nodes()[0].outcome, GraphOutcome::non_terminal);
}

/// 有出口循环需要精确吸收方程，不能把看到回边当成平局。
TEST(Graph, CyclicAbsorptionAndEquationBudget) {
  const ProbabilityGraph graph{{{GraphOutcome::non_terminal}, {GraphOutcome::non_terminal},
      {GraphOutcome::attacker_win}, {GraphOutcome::defender_win}},
      {Edge(0, 1, Rational{1}), Edge(1, 0, Rational{1, 2}), Edge(1, 2, Rational{1, 3}), Edge(1, 3, Rational{1, 6})}};
  const auto solved = std::get<SolvedGraph>(SolveGraph(graph));
  EXPECT_EQ(solved.win, (Rational{2, 3})); EXPECT_EQ(solved.loss, (Rational{1, 3}));
  EXPECT_EQ(std::get<FiniteExpectedTurns>(solved.expected_turns).value, Rational{4});
  const auto components = AnalyzeComponents(graph);
  ASSERT_EQ(components.size(), 3);
  EXPECT_EQ(components[0].kind, ComponentKind::terminal_reachable_cycle);
  EXPECT_EQ(components[0].nodes, (std::vector<GraphNodeId>{{0}, {1}}));
  EXPECT_TRUE(components[0].reaches_terminal);
  const auto limited = std::get<UnavailableGraph>(SolveGraph(graph, BattleSide::attacker, 1));
  EXPECT_EQ(limited.status, GraphSolveStatus::resource_limit_exceeded);
}

/// 封闭循环数学上为平局但实际不结束，保留正概率与无限期望，显式平局期望为零。
TEST(Graph, ClosedCycleAndFiniteDrawAreDistinct) {
  const ProbabilityGraph graph{{{GraphOutcome::non_terminal}, {GraphOutcome::non_terminal}, {GraphOutcome::draw}},
      {Edge(0, 1, Rational{1, 7}), Edge(0, 2, Rational{6, 7}), Edge(1, 1, Rational{1})}};
  const auto solved = std::get<SolvedGraph>(SolveGraph(graph));
  EXPECT_EQ(solved.draw, Rational{1}); EXPECT_EQ(solved.closed_cycle, (Rational{1, 7}));
  EXPECT_TRUE(std::holds_alternative<InfiniteExpectedTurns>(solved.expected_turns));
  const ProbabilityGraph terminal{{{GraphOutcome::draw}}, {}};
  const auto draw = std::get<SolvedGraph>(SolveGraph(terminal));
  EXPECT_EQ(draw.closed_cycle, Rational{0});
  EXPECT_EQ(std::get<FiniteExpectedTurns>(draw.expected_turns).value, Rational{0});
  const ProbabilityGraph unresolved{{{GraphOutcome::non_terminal, CycleResolution::solve_absorption_probability}}, {Edge(0, 0, Rational{1})}};
  const auto component = AnalyzeComponents(unresolved).front();
  EXPECT_EQ(component.kind, ComponentKind::closed_cycle); EXPECT_FALSE(component.reaches_terminal);
  EXPECT_EQ(std::get<SolvedGraph>(SolveGraph(unresolved)).closed_cycle, Rational{1});
}

/// 未知与预算截断均不可给默认零概率，且严格校验图的概率和及索引。
TEST(Graph, IncompleteAndInvalidGraphsNeverProducePartialResults) {
  const ProbabilityGraph unknown{{{GraphOutcome::unknown}}, {}};
  EXPECT_EQ(std::get<UnavailableGraph>(SolveGraph(unknown)).status, GraphSolveStatus::incomplete_graph);
  const ProbabilityGraph truncated{{{GraphOutcome::draw}}, {}, {0}, {GraphTruncation::max_nodes, GraphTruncation::max_nodes}};
  EXPECT_EQ(truncated.Truncations().size(), 1);
  EXPECT_EQ(std::get<UnavailableGraph>(SolveGraph(truncated)).status, GraphSolveStatus::incomplete_graph);
  EXPECT_THROW(static_cast<void>(ProbabilityGraph({}, {})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(ProbabilityGraph({{GraphOutcome::draw}}, {}, {1})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(ProbabilityGraph({{GraphOutcome::non_terminal}}, {Edge(0, 0, Rational{1, 2})})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(ProbabilityGraph({{GraphOutcome::draw}}, {Edge(0, 2, Rational{1})})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(ProbabilityGraph({{GraphOutcome::draw}}, {Edge(0, 0, Rational{0})})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(SolveGraph(unknown, BattleSide::attacker, 0)), std::invalid_argument);
}

/// 200 位分母的小概率出口仍是概率一的有限吸收，期望严格为该分母。
TEST(Graph, ArbitraryPrecisionTinyEscapeProbability) {
  const Integer denominator{std::string(200, '9')};
  const Rational escape{Integer{1}, denominator};
  const ProbabilityGraph graph{{{GraphOutcome::non_terminal}, {GraphOutcome::attacker_win}},
      {Edge(0, 0, Rational{1} - escape), Edge(0, 1, escape)}};
  const auto solved = std::get<SolvedGraph>(SolveGraph(graph));
  EXPECT_EQ(solved.win, Rational{1}); EXPECT_EQ(solved.closed_cycle, Rational{0});
  EXPECT_EQ(std::get<FiniteExpectedTurns>(solved.expected_turns).value, Rational{denominator});
}

/// 深链使用显式栈；已取消操作不暴露任何部分概率。
TEST(Graph, DeepIterativeTraversalAndCancellation) {
  constexpr std::size_t size = 12000;
  std::vector<ProbabilityNode> nodes(size, ProbabilityNode{GraphOutcome::non_terminal});
  nodes.back().outcome = GraphOutcome::attacker_win;
  std::vector<ProbabilityEdge> edges;
  for (std::size_t node = 0; node + 1 < size; ++node) edges.push_back(Edge(node, node + 1, Rational{1}));
  const ProbabilityGraph graph{std::move(nodes), std::move(edges)};
  const auto solved = std::get<SolvedGraph>(SolveGraph(graph, BattleSide::attacker, 1));
  EXPECT_EQ(solved.win, Rational{1});
  EXPECT_EQ(std::get<FiniteExpectedTurns>(solved.expected_turns).value, Rational{Integer{size - 1}});
  EXPECT_EQ(AnalyzeComponents(graph).size(), size);
  pbi::CancellationSource source; source.Request();
  EXPECT_EQ(std::get<UnavailableGraph>(SolveGraph(graph, BattleSide::attacker, {}, source.Token())).status, GraphSolveStatus::cancelled);
}
} // namespace pbi
