#include "fixed_graph_query_contract.hpp"
#include "state_graph_projection_contract.hpp"
#include "projection_number_contract.hpp"
#include "winning_paths_contract.hpp"
#include <cctype>

namespace pbi::contract {
namespace {
/// 原HTTP语义拒绝与CABI协议/资源失败分开，不把非法cursor编码成空成功。
class QueryFailure final : public std::runtime_error {
public:
  /// @param status 原HTTP状态；@param code 原业务错误码；@param message 不含环境秘密的原诊断。
  QueryFailure(int status, std::string code, std::string message) : std::runtime_error(std::move(message)), status(status), code(std::move(code)) {}
  int status;
  std::string code;
};
/// @param stop 同源只读令牌；取消整体失败，不交付部分查询或战报。
void Check(CancellationToken stop) { if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "fixed graph query cancelled"); }
/// @param message 原图浏览冲突说明；不会从该分支继续返回部分数据。
[[noreturn]] void Conflict(std::string message) { throw QueryFailure{409, "battle_exploration_conflict", std::move(message)}; }
/// @param value 协议索引；@return 非负机器整数，计数不接受浮点或bool。
std::size_t Count(const Json& value) {
  const auto number = ReadInteger(value);
  if (number < 0) throw RequestError(PBI_INVALID_INPUT_V1, "graph count must be nonnegative");
  return static_cast<std::size_t>(number);
}
/// @param value 小整数或无损十进制身份；@param stop 同源取消；@return 非负任意精度整数。
Integer Identity(const Json& value, CancellationToken stop) {
  const auto result = value.is_string() ? ReadProjectionInteger(value, stop) : Integer{ReadInteger(value)};
  if (result < 0) throw RequestError(PBI_INVALID_INPUT_V1, "graph query identity must be nonnegative");
  return result;
}
/// @param value 原cursor对象；@param stop 同源取消；@return 完整拥有步骤，根身份只由真实Core规定。
std::vector<ExplorationPathStep> ReadCursor(const Json& value, CancellationToken stop) {
  RequireSchema(value, {}, {"steps"});
  std::vector<ExplorationPathStep> steps;
  if (!value.contains("steps")) return steps;
  if (!value.at("steps").is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "cursor steps must be an array");
  for (const auto& step : value.at("steps")) {
    Check(stop); RequireFields(step, {"source_node_id", "edge_id", "target_node_id"});
    steps.push_back({{Identity(step.at("source_node_id"), stop)}, {Identity(step.at("edge_id"), stop)}, {Identity(step.at("target_node_id"), stop)}});
  }
  return steps;
}
/// @param steps 原用户路径；@return 机械身份JSON，不搜索代表前驱，不改变选择顺序。
Json Cursor(const std::vector<ExplorationPathStep>& steps) {
  auto values = Json::array();
  for (const auto& step : steps) values.push_back({{"source_node_id", step.source_node_id.value.str()}, {"edge_id", step.edge_id.value.str()}, {"target_node_id", step.target_node_id.value.str()}});
  return {{"steps", std::move(values)}};
}
/// 只读已验证路径的位置及按真实正式边产生的线性战报。
struct Position { std::size_t current; Rational probability; std::vector<BattleReportStep> report; };
/// @param graph 正式typed图；@param address 外部不透明句柄；@param cursor 完整用户路径；@param stop 同源取消。
/// @return 正式边前缀精确概率和完整替代历史；不依赖节点的代表前驱。
Position Replay(const BattleGraph& graph, const FixedGraphAddress& address, const std::vector<ExplorationPathStep>& cursor, CancellationToken stop) {
  Integer expected = 0;
  for (std::size_t depth = 0; depth < cursor.size(); ++depth) {
    Check(stop);
    if (cursor[depth].source_node_id.value != expected) Conflict("exploration path is discontinuous at depth " + std::to_string(depth)
        + ": expected source " + expected.str() + ", got " + cursor[depth].source_node_id.value.str());
    expected = cursor[depth].target_node_id.value;
  }
  Position result{0, Rational{1}, {}};
  result.report.reserve(cursor.size());
  for (std::size_t depth = 0; depth < cursor.size(); ++depth) {
    Check(stop);
    const auto& step = cursor[depth];
    if (step.edge_id.value >= Integer{graph.Edges().size()}) Conflict("invalid exploration cursor for graph '" + address.graph_id
        + "': edge_id " + step.edge_id.value.str() + " is outside the graph");
    const auto& edge = graph.Edges()[step.edge_id.value.convert_to<std::size_t>()];
    if (Integer{edge.source.value} != step.source_node_id.value || Integer{edge.target.value} != step.target_node_id.value) {
      Conflict("invalid exploration cursor for graph '" + address.graph_id + "': step at depth " + std::to_string(depth) + " does not match edge " + step.edge_id.value.str());
    }
    auto report = ProjectBattleGraphStep(ProjectionRecord(graph.Nodes()[edge.source.value]), ProjectionRecord(edge), result.probability, depth + 1, stop);
    result.probability = report.cumulative_probability;
    result.current = edge.target.value;
    result.report.push_back(std::move(report));
  }
  return result;
}
/// @param graph 本次唯一完整typed图；@param position 已验证cursor位置；@param expanded 指定组；@param stop 同源取消。
/// @return 仅当前节点相关记录的拥有投影，不复制整幅图的任何无关事件。
BattleNodeProjection Project(const BattleGraph& graph, const Position& position, std::span<const std::string> expanded, CancellationToken stop) {
  std::vector<StateGraphProjectionEdge> edges;
  for (const auto& edge : graph.Edges()) { Check(stop); if (edge.source.value == position.current) edges.push_back(ProjectionRecord(edge)); }
  return ProjectBattleGraphNode(ProjectionRecord(graph.Nodes()[position.current]), edges, position.probability, expanded, stop);
}
/// @param request 外部句柄/版本；@param cursor 已验证用户路径；@param projection 当前Core投影。
/// @param position Core真实战报；@param stop 同源取消；@return 原公开exploration完整DTO，不增加实现细节字段。
Json Exploration(const FixedGraphQueryRequest& request, const std::vector<ExplorationPathStep>& cursor,
    const BattleNodeProjection& projection, const Position& position, CancellationToken stop) {
  auto value = StateGraphProjectionJson(projection, stop);
  const auto identity = Cursor(cursor);
  auto steps = Json::array();
  for (const auto& step : position.report) { Check(stop); steps.push_back(BattleReportStepJson(step, stop)); }
  const auto terminal = value.at("node").at("terminal");
  return {{"graph_id", request.address.graph_id}, {"calculation_revision", request.address.calculation_revision}, {"cursor", identity},
      {"node", std::move(value["node"])}, {"transition_groups", std::move(value["transition_groups"])},
      {"cumulative_probability", value.at("cumulative_probability")}, {"breadcrumbs", identity.at("steps")}, {"terminal", terminal},
      {"battle_report", {{"graph_id", request.address.graph_id}, {"calculation_revision", request.address.calculation_revision}, {"root_node_id", "0"},
          {"current_node_id", projection.node.id.value.str()}, {"depth", cursor.size()}, {"cumulative_probability", value.at("cumulative_probability")}, {"steps", std::move(steps)}}}};
}
/// @param request 明确变体；@return 正式结果模式，不从展示字符串推测分支。
std::string_view Mode(const FixedGraphQueryRequest& request) {
  if (std::holds_alternative<FixedGraphExplore>(request.query)) return "explore";
  if (std::holds_alternative<FixedGraphOutcomes>(request.query)) return "outcomes";
  if (std::holds_alternative<FixedGraphAdvance>(request.query)) return "advance";
  if (std::holds_alternative<FixedGraphBacktrack>(request.query)) return "backtrack";
  return "winning_paths";
}
} // namespace

FixedGraphQueryRequest ReadFixedGraphQueryRequest(const Json& value, std::size_t remaining_rolls,
    std::size_t available_nodes, std::size_t available_edges, CancellationToken stop) {
  Check(stop);
  RequireFields(value, {"kind", "fixed_request", "expected_engine_version", "expected_rules_version", "expected_nodes", "expected_edges", "query"});
  if (value.at("kind") != "fixed_graph_query" || value.at("fixed_request").at("kind") != "fixed_battle") throw RequestError(PBI_INVALID_INPUT_V1, "invalid frozen fixed graph operation kind");
  const auto& query = value.at("query");
  if (!query.is_object() || !query.contains("mode")) throw RequestError(PBI_INVALID_INPUT_V1, "fixed graph query requires a mode");
  const auto mode = query.at("mode").get<std::string>();
  if (mode == "winning_paths") RequireSchema(query, {"mode", "graph_id", "calculation_revision", "winner"}, {"limit", "cursor", "sort", "max_traversed_walks"});
  else if (mode == "outcomes") RequireSchema(query, {"mode", "graph_id", "calculation_revision", "group_id"}, {"cursor"});
  else if (mode == "advance") RequireSchema(query, {"mode", "graph_id", "calculation_revision", "edge_id"}, {"cursor"});
  else if (mode == "backtrack") RequireSchema(query, {"mode", "graph_id", "calculation_revision"}, {"cursor", "depth"});
  else if (mode == "explore") RequireSchema(query, {"mode", "graph_id", "calculation_revision"}, {"cursor"});
  else throw RequestError(PBI_UNSUPPORTED_V1, "unsupported fixed graph query mode");
  std::vector<ExplorationPathStep> cursor;
  if (mode != "winning_paths" && query.contains("cursor")) cursor = ReadCursor(query.at("cursor"), stop);
  const auto selection = [&]() -> decltype(FixedGraphQueryRequest::query) {
    if (mode == "winning_paths") return FixedGraphWinningQuery{query};
    if (mode == "outcomes") return FixedGraphOutcomes{query.at("group_id").get<std::string>()};
    if (mode == "advance") return FixedGraphAdvance{{Identity(query.at("edge_id"), stop)}};
    if (mode == "backtrack") return FixedGraphBacktrack{query.contains("depth") && !query.at("depth").is_null() ? std::optional{Identity(query.at("depth"), stop)} : std::nullopt};
    return FixedGraphExplore{};
  }();
  return {ReadFixedBattleRequest(value.at("fixed_request"), remaining_rolls, available_nodes, available_edges),
      value.at("expected_engine_version").get<std::string>(), value.at("expected_rules_version").get<std::string>(),
      Count(value.at("expected_nodes")), Count(value.at("expected_edges")),
      {query.at("graph_id").get<std::string>(), query.at("calculation_revision").get<std::string>()}, std::move(cursor), selection};
}

Json EvaluateFixedGraphQuery(const FixedGraphQueryRequest& request, std::string_view current_engine, std::string_view current_rules, CancellationToken stop) {
  const auto mode = Mode(request);
  try {
    Check(stop);
    if (request.expected_engine_version != current_engine || request.expected_rules_version != current_rules) {
      Conflict("frozen battle graph calculation version mismatch");
    }
    const auto computation = InferFixedBattle(request.fixed.initial, request.fixed.knowledge, request.fixed.options, {}, stop);
    const auto& graph = computation.graph;
    if (graph.Nodes().size() != request.expected_nodes || graph.Edges().size() != request.expected_edges) Conflict("frozen battle graph no longer matches its creation counts");
    Json value;
    if (const auto* winning = std::get_if<FixedGraphWinningQuery>(&request.query)) {
      const auto configuration = DescribeWinningPathConfiguration(graph);
      const auto query = ReadWinningPathQueryValue(winning->value, configuration, stop);
      value = WinningPathGroupsJson(ListWinningPathGroups(graph, query, stop), stop);
    } else {
      auto cursor = request.cursor;
      auto position = Replay(graph, request.address, cursor, stop);
      if (const auto* advance = std::get_if<FixedGraphAdvance>(&request.query)) {
        const auto& node = graph.Nodes()[position.current];
        if (node.outcome == GraphOutcome::attacker_win || node.outcome == GraphOutcome::defender_win || node.outcome == GraphOutcome::draw) {
          Conflict("terminal node " + std::to_string(position.current) + " in graph '" + request.address.graph_id + "' cannot advance");
        }
        if (advance->edge_id.value >= Integer{graph.Edges().size()} || graph.Edges()[advance->edge_id.value.convert_to<std::size_t>()].source.value != position.current) {
          Conflict("edge " + advance->edge_id.value.str() + " does not leave current node " + std::to_string(position.current) + " in graph '" + request.address.graph_id + "'");
        }
        const auto& edge = graph.Edges()[advance->edge_id.value.convert_to<std::size_t>()];
        cursor.push_back({{Integer{edge.source.value}}, {Integer{edge.id.value}}, {Integer{edge.target.value}}});
        position = Replay(graph, request.address, cursor, stop);
      } else if (const auto* backtrack = std::get_if<FixedGraphBacktrack>(&request.query)) {
        if (!backtrack->depth && cursor.empty()) Conflict("invalid exploration cursor for graph '" + request.address.graph_id + "': cannot move back from the root cursor");
        const Integer depth = backtrack->depth ? *backtrack->depth : Integer{cursor.size() - 1};
        if (depth > Integer{cursor.size()}) Conflict("invalid exploration cursor for graph '" + request.address.graph_id + "': depth " + depth.str() + " is outside 0.." + std::to_string(cursor.size()));
        cursor.resize(depth.convert_to<std::size_t>());
        position = Replay(graph, request.address, cursor, stop);
      }
      if (const auto* outcomes = std::get_if<FixedGraphOutcomes>(&request.query)) {
        const std::vector ids{outcomes->group_id};
        const auto projected = Project(graph, position, ids, stop);
        auto body = StateGraphProjectionJson(projected, stop);
        bool found = false;
        for (auto& group : body.at("transition_groups")) if (group.at("group_id") == outcomes->group_id) {
          value = {{"graph_id", request.address.graph_id}, {"calculation_revision", request.address.calculation_revision}, {"cursor", Cursor(cursor)},
              {"current_node_id", projected.node.id.value.str()}, {"cumulative_probability", body.at("cumulative_probability")}, {"transition_group", std::move(group)}};
          found = true; break;
        }
        if (!found) throw QueryFailure{404, "battle_graph_resource_not_found", "transition group '" + outcomes->group_id + "' was not found on node " + std::to_string(position.current)};
      } else value = Exploration(request, cursor, Project(graph, position, {}, stop), position, stop);
    }
    Check(stop);
    return {{"kind", "fixed_graph_query"}, {"mode", mode}, {"value", std::move(value)}};
  } catch (const QueryFailure& failure) {
    Check(stop);
    return {{"kind", "fixed_graph_query"}, {"mode", mode}, {"error", {{"http_status", failure.status}, {"code", failure.code}, {"message", failure.what()}}}};
  } catch (const std::runtime_error&) {
    Check(stop);
    throw;
  }
}
} // namespace pbi::contract
