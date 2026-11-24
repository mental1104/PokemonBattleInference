#include "pbi/graph.hpp"
#include <nlohmann/json.hpp>
#include <array>
#include <iostream>
#include <string_view>

namespace {
using Json = nlohmann::json;
constexpr std::array outcome_names{
    std::pair{"attacker-win", pbi::GraphOutcome::attacker_win}, std::pair{"defender-win", pbi::GraphOutcome::defender_win},
    std::pair{"draw", pbi::GraphOutcome::draw}, std::pair{"non-terminal", pbi::GraphOutcome::non_terminal}, std::pair{"unknown", pbi::GraphOutcome::unknown}};
constexpr std::array component_names{
    std::pair{"acyclic", pbi::ComponentKind::acyclic}, std::pair{"closed-cycle", pbi::ComponentKind::closed_cycle},
    std::pair{"terminal-reachable-cycle", pbi::ComponentKind::terminal_reachable_cycle}, std::pair{"open-unresolved-cycle", pbi::ComponentKind::open_unresolved_cycle}};
constexpr std::array truncation_names{
    std::pair{"max-turns", pbi::GraphTruncation::max_turns}, std::pair{"max-nodes", pbi::GraphTruncation::max_nodes}, std::pair{"max-edges", pbi::GraphTruncation::max_edges}};
constexpr std::array failure_names{
    std::pair{"incomplete-graph", pbi::GraphSolveStatus::incomplete_graph}, std::pair{"resource-limit-exceeded", pbi::GraphSolveStatus::resource_limit_exceeded},
    std::pair{"singular-system", pbi::GraphSolveStatus::singular_system}, std::pair{"cancelled", pbi::GraphSolveStatus::cancelled}};
/// @param value JSON 字符串；@param names 唯一有限枚举映射；@return 类型化值，未知标识明确失败。
template<class T, std::size_t N>
T ReadChoice(const Json& value, const std::array<std::pair<const char*, T>, N>& names) {
  const auto text = value.get<std::string>();
  for (const auto& [name, candidate] : names) if (text == name) return candidate;
  throw std::invalid_argument("unsupported graph vector identifier");
}
/// @param value 已验证的领域枚举；@param names 固定映射；@return 借用静态标识，未知枚举失败。
template<class T, std::size_t N>
const char* Name(T value, const std::array<std::pair<const char*, T>, N>& names) {
  for (const auto& [name, candidate] : names) if (value == candidate) return name;
  throw std::invalid_argument("unsupported graph enum");
}
/// @param value 任意精度分子/分母字符串；@return 精确分数，负分母先统一符号。
pbi::Rational Fraction(const Json& value) {
  pbi::Integer numerator{value.at("numerator").get<std::string>()};
  pbi::Integer denominator{value.at("denominator").get<std::string>()};
  if (denominator < 0) { numerator = -numerator; denominator = -denominator; }
  return {numerator, denominator};
}
/// @param value 精确分数；@return 不经浮点转换的完整十进制字符串对象。
Json FractionJson(const pbi::Rational& value) {
  return {{"numerator", value.numerator().str()}, {"denominator", value.denominator().str()}};
}
/// @param value 非负 JSON 整数；@return 当前图索引；拒绝负数和浮点。
std::size_t Index(const Json& value) {
  if (!value.is_number_integer() || (value.is_number_integer() && !value.is_number_unsigned() && value.get<std::int64_t>() < 0))
    throw std::invalid_argument("graph index must be a non-negative integer");
  return value.get<std::size_t>();
}
/// 测试/benchmark 的 JSON 边界，不作为 C ABI，也不将 JSON 传给任何 Core 领域函数。
class GraphVector {
public:
  /// @param input 单个测试图合同；投影成真实不可变 Core 图，不包含 Python 运行时。
  explicit GraphVector(const Json& input)
      : graph_(ReadNodes(input.at("nodes")), ReadEdges(input.at("edges")), {Index(input.at("root"))}, ReadTruncations(input.at("truncations"))) {
    const auto observer = input.at("observer").get<std::string>();
    if (observer == "attacker") observer_ = pbi::BattleSide::attacker;
    else if (observer == "defender") observer_ = pbi::BattleSide::defender;
    else throw std::invalid_argument("unsupported observer");
    if (!input.at("max_equation_nodes").is_null()) limit_ = Index(input.at("max_equation_nodes"));
  }
  /// @return 实际 SCC 与求解完整结果；不改变源图，错误由逐行入口显式报告。
  [[nodiscard]] Json Run() const {
    auto components = Json::array();
    for (const auto& component : pbi::AnalyzeComponents(graph_)) {
      auto nodes = Json::array(); auto outgoing = Json::array();
      for (const auto id : component.nodes) nodes.push_back(id.value);
      for (const auto id : component.outgoing) outgoing.push_back(id.value);
      components.push_back({{"id", component.id.value}, {"nodes", nodes}, {"kind", Name(component.kind, component_names)},
          {"outgoing", outgoing}, {"reaches_terminal", component.reaches_terminal}});
    }
    const auto solution = pbi::SolveGraph(graph_, observer_, limit_);
    Json result{{"components", components}};
    if (const auto* solved = std::get_if<pbi::SolvedGraph>(&solution)) {
      result["status"] = "solved";
      result["win"] = FractionJson(solved->win); result["loss"] = FractionJson(solved->loss);
      result["draw"] = FractionJson(solved->draw); result["closed_cycle"] = FractionJson(solved->closed_cycle);
      if (const auto* finite = std::get_if<pbi::FiniteExpectedTurns>(&solved->expected_turns))
        result["expected_turns"] = {{"status", "finite"}, {"value", FractionJson(finite->value)}};
      else result["expected_turns"] = {{"status", "infinite"}, {"value", nullptr}};
    } else {
      const auto& unavailable = std::get<pbi::UnavailableGraph>(solution);
      result["status"] = Name(unavailable.status, failure_names);
      result["win"] = nullptr; result["loss"] = nullptr; result["draw"] = nullptr; result["closed_cycle"] = nullptr;
      result["expected_turns"] = {{"status", "unavailable"}, {"value", nullptr}};
    }
    return result;
  }
private:
  /// @param input 节点数组；@return 稳定 outcome 与逐节点循环策略的拥有值。
  static std::vector<pbi::ProbabilityNode> ReadNodes(const Json& input) {
    if (!input.is_array()) throw std::invalid_argument("nodes must be an array");
    std::vector<pbi::ProbabilityNode> nodes;
    for (const auto& node : input) {
      const auto cycle = node.at("cycle_resolution").get<std::string>();
      if (cycle != "declare-draw" && cycle != "solve-absorption-probability") throw std::invalid_argument("unsupported cycle resolution");
      nodes.push_back({ReadChoice(node.at("outcome"), outcome_names), cycle == "declare-draw" ? pbi::CycleResolution::declare_draw : pbi::CycleResolution::solve_absorption_probability});
    }
    return nodes;
  }
  /// @param input 边数组；@return 完整正概率边，后续由 ProbabilityGraph 检查守恒。
  static std::vector<pbi::ProbabilityEdge> ReadEdges(const Json& input) {
    if (!input.is_array()) throw std::invalid_argument("edges must be an array");
    std::vector<pbi::ProbabilityEdge> edges;
    for (const auto& edge : input) edges.push_back({{Index(edge.at("source"))}, {Index(edge.at("target"))}, Fraction(edge.at("probability"))});
    return edges;
  }
  /// @param input 截断数组；@return 原有三个预算原因，不把截断编码为 draw。
  static std::vector<pbi::GraphTruncation> ReadTruncations(const Json& input) {
    if (!input.is_array()) throw std::invalid_argument("truncations must be an array");
    std::vector<pbi::GraphTruncation> result;
    for (const auto& value : input) result.push_back(ReadChoice(value, truncation_names));
    return result;
  }
  pbi::ProbabilityGraph graph_;
  pbi::BattleSide observer_ = pbi::BattleSide::attacker;
  std::optional<std::size_t> limit_;
};
} // namespace

/// 无参数；逐行读取测试图并调用真实 Core，单行失败输出 error 后继续，不伪造成功结果。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << GraphVector{Json::parse(line)}.Run().dump() << '\n'; }
    catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
