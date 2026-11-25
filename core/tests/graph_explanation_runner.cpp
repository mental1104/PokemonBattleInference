#include "../src/graph_explanation_contract.hpp"
#include "../src/turn_contract.hpp"
#include "../src/event_record_contract.hpp"
#include <iostream>
#include <unordered_map>

namespace {
using namespace pbi;
using namespace pbi::contract;
/// @param value 仅差分使用的完整原图records；@return 通过真实builder重建的图，不开放私有构造或公开script操作。
BattleGraph Rebuild(const Json& value) {
  std::vector<StateGraphProjectionNode> nodes;
  std::vector<StateGraphProjectionEdge> edges;
  for (const auto& node : value.at("nodes")) nodes.push_back(ReadProjectionNodeValue(node));
  for (const auto& edge : value.at("edges")) edges.push_back(ReadProjectionEdgeValue(edge, {}));
  if (nodes.empty()) throw std::invalid_argument("explanation fixture graph is empty");
  std::unordered_map<StateKey, std::size_t, StateKeyHash> by_key;
  for (std::size_t index = 0; index < nodes.size(); ++index) by_key.emplace(nodes[index].state.Key(), index);
  std::vector<std::vector<std::size_t>> outgoing(nodes.size());
  for (std::size_t index = 0; index < edges.size(); ++index) outgoing.at(edges[index].source.value.convert_to<std::size_t>()).push_back(index);
  auto graph = BuildBattleGraph(nodes.front().state, [&](const BattleState& state) {
    std::vector<BattleTransition> result;
    for (const auto index : outgoing.at(by_key.at(state.Key()))) {
      const auto& edge = edges[index];
      result.emplace_back(BattleTransitionData{edge.probability, nodes.at(edge.target.value.convert_to<std::size_t>()).state, edge.events, edge.source_key});
    }
    return result;
  });
  if (graph.Nodes().size() != nodes.size() || graph.Edges().size() != edges.size()) throw std::invalid_argument("fixture is not an original complete BFS graph");
  for (std::size_t index = 0; index < nodes.size(); ++index)
    if (graph.Nodes()[index].key != nodes[index].state.Key() || graph.Nodes()[index].outcome != nodes[index].outcome) throw std::invalid_argument("fixture node identity or outcome differs from actual builder");
  return graph;
}
/// @param input 正式fixed_battle操作或明确诊断fixture；@return 正式codec完整结果/原完整归因JSON。
Json Run(const Json& input) {
  if (input.at("kind") == "fixed_battle") return EvaluateFixedBattle(ReadFixedBattleRequest(input, 65536, 2000000, 8000000), {}, {});
  RequireSchema(input, {"kind", "graph"}, {"max_buckets", "root_summaries"});
  if (input.at("kind") != "root_action_explanation_fixture") throw std::invalid_argument("unknown explanation diagnostic mode");
  auto graph = Rebuild(input.at("graph"));
  std::vector<RootActionEventSummary> summaries;
  if (input.contains("root_summaries")) for (const auto& summary : input.at("root_summaries")) {
    RequireFields(summary, {"target", "paths"});
    const auto target = ReadInteger(summary.at("target"));
    if (target < 0) throw std::invalid_argument("root summary target must be nonnegative");
    summaries.push_back({{static_cast<std::size_t>(target)}, ReadEventSummaryValue(summary.at("paths"), {})});
  }
  const auto count = input.contains("max_buckets") ? ReadInteger(input.at("max_buckets")) : 12;
  if (count <= 0) throw std::invalid_argument("max_buckets must be positive");
  return RootActionPairExplanationJson(ExplainRootActionPairs(graph, summaries, static_cast<std::size_t>(count)), {});
}
} // namespace
/// 无参数；逐行调用正式Core归因/固定codec，错误独立回传，不调用Python或网络。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << Run(Json::parse(line)).dump() << '\n'; }
    catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
