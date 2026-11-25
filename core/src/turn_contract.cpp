#include "turn_contract.hpp"
#include "state_graph_projection_contract.hpp"
#include "graph_explanation_contract.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <type_traits>

namespace pbi::contract {
namespace {
constexpr std::array<std::string_view, 2> sides{"attacker", "defender"};
constexpr std::array<std::string_view, 2> policies{"uniform-random", "first-legal-action"};
constexpr std::array<std::string_view, 11> phases{"turn-start", "action-selection", "action-order", "before-move",
    "accuracy-check", "before-damage", "damage", "after-damage", "after-move", "faint-check", "turn-end"};
constexpr std::array<std::string_view, 5> outcomes{"attacker-win", "defender-win", "draw", "non-terminal", "unknown"};
constexpr std::array<std::string_view, 3> truncations{"max-turns", "max-nodes", "max-edges"};
constexpr std::array<std::string_view, 4> terminations{"knockout", "mutual-knockout", "no-legal-action", "cycle-guard"};
constexpr std::array<std::string_view, 4> effect_sources{"move", "ability", "item", "status"};
constexpr std::array<std::string_view, 5> random_types{"hit_check", "damage_roll", "speed_tie", "secondary_effect", "custom"};

/// @param stop 当前计算的只读取消令牌；已取消时抛正式错误，不输出半套结果。
void CheckStop(CancellationToken stop) {
  if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "calculation cancelled");
}
/// @param value 正整数 JSON；@param maximum 当前协议硬上限；@return 合法预算，超限明确失败。
std::size_t Limit(const Json& value, std::size_t maximum) {
  const auto number = ReadInteger(value);
  if (number <= 0) throw RequestError(PBI_INVALID_INPUT_V1, "calculation limits must be positive");
  if (static_cast<std::uint64_t>(number) > maximum) throw RequestError(PBI_RESOURCE_LIMIT_V1, "calculation limit exceeds ABI budget");
  return static_cast<std::size_t>(number);
}
/// @param value 可省略的完整 turn_limits；@return 保留原 Core 不限制默认值，正数则明确保护，null 同原无上限。
TurnLimits ReadTurnLimits(const Json* value) {
  TurnLimits limits{};
  if (!value) return limits;
  RequireSchema(*value, {}, {"max_branches", "max_event_paths"});
  if (value->contains("max_branches") && !value->at("max_branches").is_null()) limits.max_branches = Limit(value->at("max_branches"), std::numeric_limits<std::size_t>::max());
  if (value->contains("max_event_paths") && !value->at("max_event_paths").is_null()) limits.max_event_paths = Limit(value->at("max_event_paths"), std::numeric_limits<std::size_t>::max());
  return limits;
}
/// @param value 完整状态 JSON；@param remaining_rolls 当前批次随机策略槽位余量。
/// @return 复用唯一状态合同解码的拥有状态，不复制业务校验或状态字段定义。
BattleState ReadInputState(const Json& value, std::size_t remaining_rolls) {
  auto state = ReadBattleStateValue(value);
  if (state.View().rules.View().damage_policy.random_damage_multipliers.size() > remaining_rolls)
    throw RequestError(PBI_RESOURCE_LIMIT_V1, "state policy roll budget exceeded");
  return state;
}
/// @param value 可空任意精度整数；@return 完整十进制字符串或 null，不经过浮点。
Json Number(const std::optional<Integer>& value) { return value ? Json(value->str()) : Json(nullptr); }
/// @param value 可空领域侧；@return 稳定侧标识或 null。
Json Side(std::optional<BattleSide> value) { return value ? Json(sides.at(static_cast<std::size_t>(*value))) : Json(nullptr); }
/// @param event 只读随机或业务事件；@return 保留完整类型与全部事实的正式协议对象。
Json EventJson(const PathEvent& event) {
  return std::visit([](const auto& item) {
    // 业务事实保留独立类型，同时提供旧随机事件身份，不从展示字符串恢复语义。
    const auto identity = [&]() {
      if constexpr (std::is_same_v<std::decay_t<decltype(item)>, TransitionEvent>) return item;
      else return item.Identity();
    }();
    const auto& random = identity.View();
    Json result{{"kind", "random"}, {"event_type", random_types.at(static_cast<std::size_t>(random.type))},
        {"event_id", random.event_id}, {"outcome_id", random.outcome_id}, {"numeric_value", Number(random.numeric_value)}};
    if constexpr (std::is_same_v<std::decay_t<decltype(item)>, BattleEvent>) {
      const auto& fact = item.View();
      result["kind"] = "battle"; result["battle_kind"] = BattleEventName(fact.kind); result["turn_number"] = fact.turn_number;
      result["actor"] = Side(fact.actor); result["target"] = Side(fact.target);
      result["move_id"] = fact.move_id ? Json(*fact.move_id) : Json(nullptr);
      result["source_identifier"] = fact.source_identifier ? Json(*fact.source_identifier) : Json(nullptr);
      result["value"] = Number(fact.value); result["before"] = Number(fact.before); result["after"] = Number(fact.after);
    }
    return result;
  }, event);
}

/// 结果投影的局部预算，完整图逐条计费，避免小输入生成无界 JSON 或事件树。
class Projection {
public:
  /// @param stop 同一计算的只读取消令牌；预算只属于本次结果，不修改领域对象。
  explicit Projection(CancellationToken stop) : stop_(std::move(stop)) {}
  /// @param value 一条完整节点/边/转移；记录其实际编码字节，超限不保留部分成功。
  void Charge(const Json& value) {
    CheckStop(stop_);
    const auto size = value.dump().size();
    if (size > bytes_left_) throw RequestError(PBI_RESOURCE_LIMIT_V1, "result byte budget exceeded");
    bytes_left_ -= size;
  }
  /// @param summary 同一后继下完整条件历史；@return 全部路径和原精确条件权重。
  [[nodiscard]] Json Paths(const EventSummary& summary) {
    if (summary.Paths().size() > paths_left_) throw RequestError(PBI_RESOURCE_LIMIT_V1, "result event path budget exceeded");
    paths_left_ -= summary.Paths().size();
    auto paths = Json::array();
    for (const auto& path : summary.Paths()) {
      CheckStop(stop_);
      if (path.events.size() > events_left_) throw RequestError(PBI_RESOURCE_LIMIT_V1, "result event count budget exceeded");
      events_left_ -= path.events.size();
      auto events = Json::array();
      for (const auto& event : path.events) events.push_back(EventJson(event));
      Json value{{"events", std::move(events)}, {"probability", FractionJson(path.probability)}};
      // 每条历史即时计入字节预算，不能先积累整个巨型历史树再发现超过传输上限。
      Charge(value);
      paths.push_back(std::move(value));
    }
    return paths;
  }
  /// @param value 只读正式后继；@return 完整状态/绝对概率/条件事件/来源，并计入输出预算。
  [[nodiscard]] Json Transition(const BattleTransition& value) {
    const auto& data = value.View();
    Json result{{"probability", FractionJson(data.probability)}, {"state", StateJson(data.state)},
        {"source_key", data.source_key ? Json(*data.source_key) : Json(nullptr)}};
    Charge(result);
    result["paths"] = Paths(data.events);
    return result;
  }
private:
  CancellationToken stop_;
  std::size_t bytes_left_ = PBI_V1_MAX_RESULT_BYTES;
  std::size_t paths_left_ = PBI_V1_MAX_RESULT_EVENT_PATHS;
  std::size_t events_left_ = PBI_V1_MAX_RESULT_EVENTS;
};

/// @param aspects 当前参考机制明确缺口；@return 完整来源/标识/能力说明，不把部分支持说成全机制支持。
Json CoverageJson(std::span<const UnsupportedAspect> aspects) {
  auto result = Json::array();
  for (const auto& aspect : aspects) result.push_back({{"source", effect_sources.at(static_cast<std::size_t>(aspect.source))},
      {"identifier", aspect.identifier}, {"capability", aspect.capability}});
  return result;
}
/// @return 原不可重排十一阶段的稳定名称数组，不在适配层执行回合。
Json PhasesJson() {
  auto result = Json::array();
  for (const auto phase : stable_turn_phases) result.push_back(phases.at(static_cast<std::size_t>(phase)));
  return result;
}
/// @param reason 可空真实终止/保护原因；@return 保留二者不同语义的稳定标识或 null。
Json ReasonJson(const std::optional<GraphStopReason>& reason) {
  if (!reason) return nullptr;
  return std::visit([](auto value) -> Json {
    if constexpr (std::is_same_v<decltype(value), GraphTruncation>) return truncations.at(static_cast<std::size_t>(value));
    else return terminations.at(static_cast<std::size_t>(value));
  }, *reason);
}
/// @param stats 构图真实最终统计；@return 全部计数，不重算概率或推测未展开节点。
Json StatisticsJson(const GraphStatistics& stats) {
  const auto& counts = stats.terminal_counts;
  return {{"nodes", stats.nodes}, {"edges", stats.edges}, {"max_turn_number", stats.max_turn_number},
      {"closed_cycles", stats.closed_cycles}, {"terminal_reachable_cycles", stats.terminal_reachable_cycles},
      {"terminal_counts", {{"attacker_wins", counts.attacker_wins}, {"defender_wins", counts.defender_wins},
      {"draws", counts.draws}, {"non_terminal", counts.non_terminal}, {"unknown", counts.unknown}}}};
}
/// @param graph 正式完整图；@return 有序保护原因，空集合不代表后续求解一定可用。
Json TruncationsJson(const BattleGraph& graph) {
  auto result = Json::array();
  for (const auto reason : graph.Truncations()) result.push_back(truncations.at(static_cast<std::size_t>(reason)));
  return result;
}
/// @param graph 正式回合构造的真实图；@param stop 同一取消令牌；@return 所有状态/事件/SCC/前驱路径。
Json FullGraphJson(const BattleGraph& graph, CancellationToken stop) {
  Projection budget{stop};
  auto nodes = Json::array(), edges = Json::array();
  for (const auto& node : graph.Nodes()) {
    CheckStop(stop);
    auto path = Json::array();
    for (const auto id : graph.RepresentativePath(node.id)) path.push_back(id.value);
    Json value{{"id", node.id.value}, {"state", StateJson(node.state)}, {"outcome", outcomes.at(static_cast<std::size_t>(node.outcome))},
        {"reason", ReasonJson(node.reason)}, {"predecessor_node", node.predecessor_node ? Json(node.predecessor_node->value) : Json(nullptr)},
        {"predecessor_edge", node.predecessor_edge ? Json(node.predecessor_edge->value) : Json(nullptr)}, {"path", std::move(path)}};
    budget.Charge(value); nodes.push_back(std::move(value));
  }
  for (const auto& edge : graph.Edges()) {
    CheckStop(stop);
    Json value{{"id", edge.id.value}, {"source", edge.source.value}, {"target", edge.target.value},
        {"probability", FractionJson(edge.probability)},
        {"source_key", edge.source_key ? Json(*edge.source_key) : Json(nullptr)}};
    budget.Charge(value);
    value["paths"] = budget.Paths(edge.events);
    edges.push_back(std::move(value));
  }
  auto components = ComponentsJson(graph.Components(), stop);
  budget.Charge(components);
  return {{"nodes", std::move(nodes)}, {"edges", std::move(edges)}, {"components", std::move(components)},
      {"statistics", StatisticsJson(graph.Statistics())}, {"truncations", TruncationsJson(graph)}};
}
} // namespace

TurnRequest ReadTurnRequest(const Json& value, std::size_t remaining_rolls) {
  RequireSchema(value, {"kind", "state", "type_chart", "selection"}, {"turn_limits"});
  const auto& selection = value.at("selection");
  RequireFields(selection, {"mode", "attacker", "defender"});
  const auto mode = selection.at("mode").get<std::string>();
  // 直接构造有效的互斥分支，不先创建零 ID 等无效默认行动再覆盖。
  auto actions = [&]() -> std::variant<ExplicitTurnActions, PolicyTurnActions> {
    if (mode == "actions") return ExplicitTurnActions{ReadActionValue(selection.at("attacker")), ReadActionValue(selection.at("defender"))};
    if (mode == "policies") return PolicyTurnActions{ReadEnum<ActionPolicy>(selection.at("attacker"), policies), ReadEnum<ActionPolicy>(selection.at("defender"), policies)};
    throw RequestError(PBI_UNSUPPORTED_V1, "unsupported turn selection mode");
  }();
  return {ReadInputState(value.at("state"), remaining_rolls), ReadTypeChart(value.at("type_chart")), std::move(actions),
      ReadTurnLimits(value.contains("turn_limits") ? &value.at("turn_limits") : nullptr)};
}

FixedBattleRequest ReadFixedBattleRequest(const Json& value, std::size_t remaining_rolls,
    std::size_t available_nodes, std::size_t available_edges) {
  RequireSchema(value, {"kind", "state", "type_chart", "attacker_policy", "defender_policy", "observer"},
      {"turn_limits", "graph_limits", "max_equation_nodes", "include_graph", "progress_interval", "include_representative_paths", "include_root_action_explanation", "graph_mode"});
  auto state = ReadInputState(value.at("state"), remaining_rolls);
  FixedBattleOptions options;
  options.attacker_policy = ReadEnum<ActionPolicy>(value.at("attacker_policy"), policies);
  options.defender_policy = ReadEnum<ActionPolicy>(value.at("defender_policy"), policies);
  options.observer = ReadEnum<BattleSide>(value.at("observer"), sides);
  options.turn_limits = ReadTurnLimits(value.contains("turn_limits") ? &value.at("turn_limits") : nullptr);
  // 与原 infer_one_on_one_battle 默认一致；回合上限继承 state.rules，不额外降为 64。
  options.graph_limits = {20000, 80000, std::nullopt};
  if (value.contains("graph_limits")) {
    const auto& limits = value.at("graph_limits");
    RequireSchema(limits, {}, {"max_nodes", "max_edges", "max_turns"});
    if (limits.contains("max_nodes")) options.graph_limits.max_nodes = Limit(limits.at("max_nodes"), PBI_V1_MAX_GENERATED_NODES);
    if (limits.contains("max_edges")) options.graph_limits.max_edges = Limit(limits.at("max_edges"), PBI_V1_MAX_GENERATED_EDGES);
    if (limits.contains("max_turns") && !limits.at("max_turns").is_null()) options.graph_limits.max_turns = static_cast<std::int64_t>(Limit(limits.at("max_turns"), PBI_V1_MAX_INFERENCE_TURNS));
  }
  if (*options.graph_limits.max_nodes > available_nodes || *options.graph_limits.max_edges > available_edges)
    throw RequestError(PBI_RESOURCE_LIMIT_V1, "batch graph reservation budget exceeded");
  // 原精确求解器缺省 None：不能悄悄复用旧显式 graph 输入的 128 方程保护。
  if (value.contains("max_equation_nodes") && !value.at("max_equation_nodes").is_null())
    options.max_equation_nodes = Limit(value.at("max_equation_nodes"), std::numeric_limits<std::size_t>::max());
  options.progress_interval = value.contains("progress_interval") ? Limit(value.at("progress_interval"), std::numeric_limits<std::size_t>::max()) : 100;
  auto purpose = FixedGraphPurpose::exploration;
  if (value.contains("graph_mode")) {
    const auto mode = value.at("graph_mode").get<std::string>();
    if (mode == "configuration_summary") purpose = FixedGraphPurpose::configuration_summary;
    else if (mode != "full") throw RequestError(PBI_UNSUPPORTED_V1, "unsupported fixed graph mode");
  }
  if (purpose == FixedGraphPurpose::configuration_summary && !value.contains("progress_interval")) options.progress_interval = 200;
  return {std::move(state), ReadTypeChart(value.at("type_chart")), options,
      value.contains("include_graph") ? ReadBool(value.at("include_graph")) : false,
      value.contains("include_representative_paths") ? ReadBool(value.at("include_representative_paths")) : false,
      value.contains("include_root_action_explanation") ? ReadBool(value.at("include_root_action_explanation")) : false, purpose};
}

Json EvaluateTurn(const TurnRequest& request, CancellationToken stop) {
  CheckStop(stop);
  const StandardTurnResolver resolver{request.knowledge};
  auto transitions = std::visit([&](const auto& selection) {
    if constexpr (std::is_same_v<std::decay_t<decltype(selection)>, ExplicitTurnActions>)
      return resolver.Resolve(request.state, selection.attacker, selection.defender, request.limits, stop).transitions;
    else return resolver.Expand(request.state, selection.attacker, selection.defender, request.limits, stop);
  }, request.selection);
  Projection budget{stop};
  auto values = Json::array();
  for (const auto& transition : transitions) values.push_back(budget.Transition(transition));
  CheckStop(stop);
  return {{"kind", "battle_turn"}, {"transitions", std::move(values)}, {"phases", PhasesJson()},
      {"unsupported_aspects", CoverageJson(resolver.CoverageLimitations(request.state))}};
}

Json EvaluateFixedBattle(const FixedBattleRequest& request, const GraphProgressObserver& progress, CancellationToken stop) {
  std::vector<RootActionEventSummary> root_summaries;
  const auto computation = [&] {
    if (request.graph_purpose == FixedGraphPurpose::exploration) return InferFixedBattle(request.initial, request.knowledge, request.options, progress, stop);
    auto summary = InferSummaryFixedBattle(request.initial, request.knowledge, request.options, progress, stop);
    root_summaries = std::move(summary.root_summaries);
    return std::move(summary.computation);
  }();
  CheckStop(stop);
  auto result = GraphSolutionJson(computation.solution);
  result["kind"] = "fixed_battle"; result["observer"] = sides.at(static_cast<std::size_t>(request.options.observer));
  result["statistics"] = StatisticsJson(computation.graph.Statistics());
  result["truncations"] = TruncationsJson(computation.graph);
  result["unsupported_aspects"] = CoverageJson(computation.unsupported_aspects);
  result["graph"] = request.include_graph ? FullGraphJson(computation.graph, stop) : Json(nullptr);
  if (request.include_representative_paths) result["representative_paths"] = RepresentativeBattlePathsJson(ProjectRepresentativeBattlePaths(computation.graph, stop), stop);
  if (request.include_root_action_explanation) {
    result["root_action_explanation"] = nullptr;
    if (std::holds_alternative<SolvedGraph>(computation.solution)) {
      // 与原worker一致：解释为成功结果的可空增强，失败不抹掉已完整求得概率；取消仍整批失败。
      try { result["root_action_explanation"] = RootActionPairExplanationJson(ExplainRootActionPairs(computation.graph, root_summaries, 12, stop), stop); }
      catch (const std::exception&) { CheckStop(stop); }
    }
  }
  return result;
}
} // namespace pbi::contract
