#include "event_analysis_contract.hpp"
#include "event_record_contract.hpp"
#include "projection_number_contract.hpp"

namespace pbi::contract {
namespace {
constexpr std::array<std::string_view, 2> sides{"attacker", "defender"};
constexpr std::array<std::string_view, 5> random_types{"hit_check", "damage_roll", "speed_tie", "secondary_effect", "custom"};
constexpr std::array<std::string_view, 16> business_kinds{"turn-started", "move-selected", "action-ordered", "move-used", "action-blocked", "hit", "miss",
    "damage", "hp-changed", "pp-changed", "ability-triggered", "item-triggered", "status-applied", "status-prevented", "fainted", "turn-ended"};
/// @param stop 同源令牌；取消整体失败，不发布部分分析结果。
void CheckStop(CancellationToken stop) { if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "event analysis cancelled"); }
/// @param value 应为JSON数组；非数组明确失败，禁止对象隐式迭代。
void RequireArray(const Json& value) {
  if (!value.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "event collection must be an array");
}
/// @param value 平台内非负索引；@return 不接受bool/小数的稳定size_t。
std::size_t Index(const Json& value) {
  const auto integer = ReadInteger(value);
  if (integer < 0) throw RequestError(PBI_INVALID_INPUT_V1, "event graph index must be non-negative");
  return static_cast<std::size_t>(integer);
}
/// @param value 可空侧枚举；@return 空值保持无主体/目标，不用观察方替代。
std::optional<BattleSide> Side(const Json& value) {
  return value.is_null() ? std::nullopt : std::optional{ReadEnum<BattleSide>(value, sides)};
}
/// 唯一事件读取器的两个明确数值合同；旧operation保持默认1024，只有projection选择整体请求预算。
enum class EventNumberBudget { legacy_1024, projection_request };
/// @param value 可空精确整数；@param budget 当前operation明确数值合同；@param stop 同源取消。
/// @return 完整拥有整数，旧入口不扩大1024位约束，projection不削减原长路径。
std::optional<Integer> Number(const Json& value, EventNumberBudget budget = EventNumberBudget::legacy_1024, CancellationToken stop = {}) {
  if (value.is_null()) return std::nullopt;
  return budget == EventNumberBudget::projection_request ? ReadProjectionInteger(value, stop) : ReadDecimalInteger(value);
}
/// @param value 与真实turn/fixed_battle输出一致的事件；@param budget 当前明确数值合同；@param stop 同源取消。
/// @return 完整类型化事件；业务事实与附带随机身份冲突时拒绝，不从文案恢复语义。
PathEvent ReadPathEventImpl(const Json& value, EventNumberBudget budget, CancellationToken stop) {
  if (!value.is_object() || !value.contains("kind")) throw RequestError(PBI_INVALID_INPUT_V1, "event requires a kind");
  const bool business = value.at("kind") == "battle";
  if (business) RequireFields(value, {"kind", "event_type", "event_id", "outcome_id", "numeric_value", "battle_kind", "turn_number",
      "actor", "target", "move_id", "source_identifier", "value", "before", "after"});
  else {
    RequireFields(value, {"kind", "event_type", "event_id", "outcome_id", "numeric_value"});
    if (value.at("kind") != "random") throw RequestError(PBI_INVALID_INPUT_V1, "unsupported event kind");
  }
  const TransitionEvent identity{{ReadEnum<TransitionEventType>(value.at("event_type"), random_types),
      value.at("event_id").get<std::string>(), value.at("outcome_id").get<std::string>(), Number(value.at("numeric_value"), budget, stop)}};
  if (!business) return identity;
  BattleEvent fact{{ReadEnum<BattleEventKind>(value.at("battle_kind"), business_kinds), ReadInteger(value.at("turn_number")),
      Side(value.at("actor")), Side(value.at("target")), value.at("move_id").is_null() ? std::nullopt : std::optional{ReadInteger(value.at("move_id"))},
      value.at("source_identifier").is_null() ? std::nullopt : std::optional{value.at("source_identifier").get<std::string>()},
      Number(value.at("value"), budget, stop), Number(value.at("before"), budget, stop), Number(value.at("after"), budget, stop)}};
  if (fact.Identity() != identity) throw RequestError(PBI_INVALID_INPUT_V1, "battle event facts conflict with random identity");
  return fact;
}
/// @param value 一条边完整替代路径数组；@param stop 同源取消；@param budget 当前operation数值合同。
/// @return 原EventSummary严格归一和等价路径归并，条件概率不得被当作绝对概率。
EventSummary ReadEventSummaryImpl(const Json& value, CancellationToken stop, EventNumberBudget budget) {
  RequireArray(value);
  std::vector<WeightedEventPath> paths;
  for (const auto& path : value) {
    CheckStop(stop);
    RequireFields(path, {"events", "probability"});
    RequireArray(path.at("events"));
    std::vector<PathEvent> events;
    for (const auto& event : path.at("events")) { CheckStop(stop); events.push_back(ReadPathEventImpl(event, budget, stop)); }
    paths.push_back({std::move(events), budget == EventNumberBudget::projection_request ? ReadProjectionFraction(path.at("probability"), stop) : ReadFraction(path.at("probability"))});
  }
  return EventSummary{std::move(paths)};
}
} // namespace

PathEvent ReadPathEventValue(const Json& value) { return ReadPathEventImpl(value, EventNumberBudget::legacy_1024, {}); }
EventSummary ReadEventSummaryValue(const Json& value, CancellationToken stop) { return ReadEventSummaryImpl(value, stop, EventNumberBudget::legacy_1024); }
EventSummary ReadProjectionEventSummaryValue(const Json& value, CancellationToken stop) { return ReadEventSummaryImpl(value, stop, EventNumberBudget::projection_request); }
namespace {
/// @param value 原完整查询；@return 不在codec计算命中/历史满足性的类型化查询。
EventQuery ReadQuery(const Json& value) {
  RequireSchema(value, {"predicate"}, {"occurrence_mode", "turn_range", "min_occurrences", "max_occurrences", "distribution_count_limit", "distribution_turn_limit", "max_key_event_summaries"});
  EventQuery query;
  const auto& predicate = value.at("predicate");
  RequireSchema(predicate, {}, {"battle_event_kinds", "transition_event_types", "side", "side_role", "move_id", "effect_identifier", "event_id", "outcome_id"});
  if (predicate.contains("battle_event_kinds")) {
    RequireArray(predicate.at("battle_event_kinds"));
    for (const auto& kind : predicate.at("battle_event_kinds")) query.predicate.battle_event_kinds.push_back(ReadEnum<BattleEventKind>(kind, business_kinds));
  }
  if (predicate.contains("transition_event_types")) {
    RequireArray(predicate.at("transition_event_types"));
    for (const auto& type : predicate.at("transition_event_types")) query.predicate.transition_event_types.push_back(ReadEnum<TransitionEventType>(type, random_types));
  }
  if (predicate.contains("side")) query.predicate.side = Side(predicate.at("side"));
  if (predicate.contains("side_role")) query.predicate.side_role = ReadEnum<EventSideRole>(predicate.at("side_role"), std::array<std::string_view, 3>{"any", "actor", "target"});
  if (predicate.contains("move_id") && !predicate.at("move_id").is_null()) query.predicate.move_id = ReadInteger(predicate.at("move_id"));
  if (predicate.contains("effect_identifier") && !predicate.at("effect_identifier").is_null()) query.predicate.effect_identifier = predicate.at("effect_identifier").get<std::string>();
  if (predicate.contains("event_id") && !predicate.at("event_id").is_null()) query.predicate.event_id = predicate.at("event_id").get<std::string>();
  if (predicate.contains("outcome_id") && !predicate.at("outcome_id").is_null()) query.predicate.outcome_id = predicate.at("outcome_id").get<std::string>();
  if (value.contains("occurrence_mode")) query.occurrence_mode = ReadEnum<EventOccurrenceMode>(value.at("occurrence_mode"), std::array<std::string_view, 2>{"any", "first"});
  if (value.contains("turn_range") && !value.at("turn_range").is_null()) {
    const auto& range = value.at("turn_range");
    RequireSchema(range, {}, {"start_turn", "end_turn"});
    query.turn_range = EventTurnRange{range.contains("start_turn") ? Number(range.at("start_turn")) : std::nullopt, range.contains("end_turn") ? Number(range.at("end_turn")) : std::nullopt};
  }
  if (value.contains("min_occurrences")) query.min_occurrences = ReadDecimalInteger(value.at("min_occurrences"));
  if (value.contains("max_occurrences")) query.max_occurrences = Number(value.at("max_occurrences"));
  if (value.contains("distribution_count_limit")) query.distribution_count_limit = Index(value.at("distribution_count_limit"));
  if (value.contains("distribution_turn_limit")) query.distribution_turn_limit = Index(value.at("distribution_turn_limit"));
  if (value.contains("max_key_event_summaries")) query.max_key_event_summaries = Index(value.at("max_key_event_summaries"));
  return query;
}
/// @param probability 显式零条件或精确商；@return 与原defined/undefined-zero-condition一致的稳定结果。
Json ConditionalJson(const EventConditionalProbability& probability) {
  return {{"status", probability.value ? "defined" : "undefined-zero-condition"}, {"value", probability.value ? FractionJson(*probability.value) : Json(nullptr)},
      {"condition_probability", FractionJson(probability.condition_probability)}};
}
/// @param buckets 原全部分布桶；@return 不省略零概率或溢出桶的完整顺序投影。
Json DistributionJson(const std::vector<EventDistributionBucket>& buckets) {
  auto result = Json::array();
  for (const auto& bucket : buckets) result.push_back({{"key", bucket.key}, {"probability", FractionJson(bucket.probability)}});
  return result;
}
/// @param side 可空事件位置；@return 原侧标识，不把无主体变成默认攻击方。
Json SideJson(std::optional<BattleSide> side) { return side ? Json(sides.at(static_cast<std::size_t>(*side))) : Json(nullptr); }
/// @param query 真实领域查询；@return 包含所有缺省值的完整规范投影，不回显未经读取的JSON。
Json QueryJson(const EventQuery& query) {
  auto kinds = Json::array();
  for (const auto kind : query.predicate.battle_event_kinds) kinds.push_back(BattleEventName(kind));
  auto types = Json::array();
  for (const auto type : query.predicate.transition_event_types) types.push_back(random_types.at(static_cast<std::size_t>(type)));
  constexpr std::array<std::string_view, 3> roles{"any", "actor", "target"};
  return {{"predicate", {{"battle_event_kinds", std::move(kinds)}, {"transition_event_types", std::move(types)}, {"side", SideJson(query.predicate.side)},
      {"side_role", roles.at(static_cast<std::size_t>(query.predicate.side_role))}, {"move_id", query.predicate.move_id ? Json(*query.predicate.move_id) : Json(nullptr)},
      {"effect_identifier", query.predicate.effect_identifier ? Json(*query.predicate.effect_identifier) : Json(nullptr)},
      {"event_id", query.predicate.event_id ? Json(*query.predicate.event_id) : Json(nullptr)}, {"outcome_id", query.predicate.outcome_id ? Json(*query.predicate.outcome_id) : Json(nullptr)}}},
      {"occurrence_mode", query.occurrence_mode == EventOccurrenceMode::any ? "any" : "first"},
      {"turn_range", query.turn_range ? Json{{"start_turn", query.turn_range->start ? Json(query.turn_range->start->str()) : Json(nullptr)},
          {"end_turn", query.turn_range->end ? Json(query.turn_range->end->str()) : Json(nullptr)}} : Json(nullptr)},
      {"min_occurrences", query.min_occurrences.str()}, {"max_occurrences", query.max_occurrences ? Json(query.max_occurrences->str()) : Json(nullptr)},
      {"distribution_count_limit", query.distribution_count_limit}, {"distribution_turn_limit", query.distribution_turn_limit}, {"max_key_event_summaries", query.max_key_event_summaries}};
}
} // namespace

EventAnalysisRequest ReadEventAnalysisRequest(const Json& value, std::size_t available_nodes, std::size_t available_edges, CancellationToken stop) {
  CheckStop(stop);
  RequireFields(value, {"kind", "calculation_revision", "inference_run_id", "graph", "query", "observer"});
  if (value.at("kind") != "event_analysis") throw RequestError(PBI_INVALID_INPUT_V1, "invalid event analysis operation kind");
  const auto& graph = value.at("graph");
  RequireFields(graph, {"nodes", "edges", "root", "root_turn_number", "truncations"});
  RequireArray(graph.at("edges"));
  if (graph.at("edges").size() > available_edges) throw RequestError(PBI_RESOURCE_LIMIT_V1, "event topology exceeds ABI edge budget");
  // 复用唯一正式拓扑读取器；只拆出同一条边的事件元数据，不执行无关图求解。
  auto topology = graph;
  topology.erase("root_turn_number");
  topology["kind"] = "graph";
  topology["observer"] = value.at("observer");
  std::vector<EventSummary> events;
  for (auto& edge : topology["edges"]) {
    CheckStop(stop);
    if (!edge.is_object() || !edge.contains("event_paths")) throw RequestError(PBI_INVALID_INPUT_V1, "event topology edge requires complete event_paths");
    events.push_back(ReadEventSummaryValue(edge.at("event_paths"), stop));
    edge.erase("event_paths");
  }
  auto parsed = ReadGraphRequest(topology, available_nodes, available_edges, stop);
  return {{value.at("calculation_revision").get<std::string>(), value.at("inference_run_id").get<std::string>(),
      {std::move(parsed.graph), std::move(events), ReadDecimalInteger(graph.at("root_turn_number"))}}, ReadQuery(value.at("query")), parsed.observer};
}

Json EventAnalysisResultJson(const EventAnalysisResult& solved, CancellationToken stop) {
  auto keys = Json::array();
  for (const auto& event : solved.key_events) {
    CheckStop(stop);
    keys.push_back({{"event_type", random_types.at(static_cast<std::size_t>(event.event_type))},
        {"battle_event_kind", event.battle_event_kind ? Json(BattleEventName(*event.battle_event_kind)) : Json(nullptr)},
        {"actor", SideJson(event.actor)}, {"target", SideJson(event.target)}, {"move_id", event.move_id ? Json(*event.move_id) : Json(nullptr)},
        {"effect_identifier", event.effect_identifier ? Json(*event.effect_identifier) : Json(nullptr)},
        {"event_id", event.event_id}, {"outcome_id", event.outcome_id}, {"path_group_count", event.path_group_count}});
  }
  return {{"kind", "event_analysis"}, {"calculation_revision", solved.calculation_revision}, {"inference_run_id", solved.inference_run_id},
      {"observer", sides.at(static_cast<std::size_t>(solved.observer))}, {"query", QueryJson(solved.query)}, {"baseline_win_probability", FractionJson(solved.baseline_win)},
      {"baseline_loss_probability", FractionJson(solved.baseline_loss)}, {"baseline_draw_probability", FractionJson(solved.baseline_draw)},
      {"event_probability", FractionJson(solved.event_probability)}, {"event_win_joint_probability", FractionJson(solved.event_win_joint_probability)},
      {"win_given_event", ConditionalJson(solved.win_given_event)}, {"win_given_not_event", ConditionalJson(solved.win_given_not_event)},
      {"first_occurrence_distribution", DistributionJson(solved.first_occurrence_distribution)}, {"occurrence_count_distribution", DistributionJson(solved.occurrence_count_distribution)},
      {"path_group_coverage", {{"total_edge_count", solved.path_group_coverage.total_edges}, {"matching_edge_count", solved.path_group_coverage.matching_edges},
          {"total_event_path_group_count", solved.path_group_coverage.total_path_groups}, {"matching_event_path_group_count", solved.path_group_coverage.matching_path_groups}}},
      {"key_events", std::move(keys)}, {"original_probability_preserved", solved.original_probability_preserved},
      {"computation_cost", {{"original_node_count", solved.cost.original_nodes}, {"original_edge_count", solved.cost.original_edges},
          {"product_node_count", solved.cost.product_nodes}, {"product_edge_count", solved.cost.product_edges}, {"exact_solver_run_count", solved.cost.exact_solver_runs}}}};
}

Json EvaluateEventAnalysis(const EventAnalysisRequest& request, CancellationToken stop) {
  try {
    return EventAnalysisResultJson(AnalyzeBattleEvents(request.artifact, request.query, request.observer, stop), stop);
  } catch (const std::runtime_error&) {
    // 纯域协作取消与普通异常分开映射，防止运行中取消掉入C ABI INTERNAL_ERROR兜底。
    CheckStop(stop);
    throw;
  }
}
} // namespace pbi::contract
