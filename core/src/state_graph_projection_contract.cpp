#include "state_graph_projection_contract.hpp"
#include "event_record_contract.hpp"
#include "projection_number_contract.hpp"
#include <boost/multiprecision/integer.hpp>
#include <cmath>

namespace pbi::contract {
namespace {
constexpr std::array<std::string_view, 2> sides{"attacker", "defender"};
constexpr std::array<std::string_view, 5> outcomes{"attacker-win", "defender-win", "draw", "non-terminal", "unknown"};
constexpr std::array<std::string_view, 6> group_names{"action-selection", "action-order", "hit-check", "damage-distribution", "secondary-effect", "composite"};
constexpr std::array<std::string_view, 5> random_names{"hit_check", "damage_roll", "speed_tie", "secondary_effect", "custom"};
constexpr std::array<std::string_view, 4> terminations{"knockout", "mutual-knockout", "no-legal-action", "cycle-guard"};
constexpr std::array<std::string_view, 3> truncations{"max-turns", "max-nodes", "max-edges"};
/// @param stop 同源令牌；取消整体失败，不输出部分节点或分组。
void Check(CancellationToken stop) { if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "state graph projection cancelled"); }
/// @param value JSON非负整数；@return 节点/边索引，不接受float/bool。
std::size_t Index(const Json& value) {
  const auto integer = ReadInteger(value);
  if (integer < 0) throw RequestError(PBI_INVALID_INPUT_V1, "projection index must be nonnegative");
  return static_cast<std::size_t>(integer);
}
/// @param value 正式图小整数或快照任意精度文本；@param stop 同源取消；@return 非负只读身份，不经浮点。
Integer Identity(const Json& value, CancellationToken stop) {
  const Integer identity = value.is_string() ? ReadProjectionInteger(value, stop) : Integer{ReadInteger(value)};
  if (identity < 0) throw RequestError(PBI_INVALID_INPUT_V1, "projection identity must be nonnegative");
  return identity;
}
/// @param value 原完整图可空reason；@return 区分确定终局和预算截断的拥有值。
std::optional<GraphStopReason> ReadReason(const Json& value) {
  if (value.is_null()) return std::nullopt;
  const auto text = value.get<std::string>();
  for (std::size_t index = 0; index < terminations.size(); ++index) if (text == terminations[index]) return GraphStopReason{static_cast<BattleTermination>(index)};
  for (std::size_t index = 0; index < truncations.size(); ++index) if (text == truncations[index]) return GraphStopReason{static_cast<GraphTruncation>(index)};
  throw RequestError(PBI_UNSUPPORTED_V1, "unknown graph stop reason");
}
/// @param reason 可空Core终止/保护；@return 原稳定标识或null，不把unknown当成draw。
Json Reason(const std::optional<GraphStopReason>& reason) {
  if (!reason) return nullptr;
  return std::visit([](auto value) -> Json {
    if constexpr (std::is_same_v<decltype(value), GraphTruncation>) return truncations.at(static_cast<std::size_t>(value));
    else return terminations.at(static_cast<std::size_t>(value));
  }, *reason);
}
/// @param value 可空任意精度整数；@return 无损十进制文本/null，客户端可机械解码JSON整数。
Json Number(const std::optional<Integer>& value) { return value ? Json(value->str()) : Json(nullptr); }
/// @param side 可空稳定侧；@return 原标识/null。
Json Side(std::optional<BattleSide> side) { return side ? Json(sides.at(static_cast<std::size_t>(*side))) : Json(nullptr); }
/// @param value 已验证非负精确概率；@return 与Python Fraction.__float__一致的binary64 ties-to-even展示值。
double Decimal(const Rational& value) {
  if (value.numerator() == 0) return 0;
  const auto& numerator = value.numerator();
  const auto& denominator = value.denominator();
  int exponent = static_cast<int>(boost::multiprecision::msb(numerator)) - static_cast<int>(boost::multiprecision::msb(denominator));
  if (exponent >= 0 ? numerator < (denominator << exponent) : (numerator << -exponent) < denominator) --exponent;
  if (exponent < -1075) return 0;
  exponent = std::max(exponent, -1022);
  const int shift = 52 - exponent;
  const Integer scaled = numerator << shift;
  Integer quotient = scaled / denominator;
  const Integer twice_remainder = (scaled % denominator) * 2;
  if (twice_remainder > denominator || (twice_remainder == denominator && (quotient & 1) != 0)) ++quotient;
  return std::ldexp(quotient.convert_to<double>(), exponent - 52);
}
/// @param value 正式精确概率；@return JS安全分数和原展示近似，不用于后续概率运算。
} // namespace

Json ExactProbabilityJson(const Rational& value) {
  auto result = FractionJson(value);
  const auto decimal = Decimal(value);
  result["decimal"] = decimal;
  result["percent"] = decimal * 100;
  return result;
}
namespace {
/// @param action 原MOVE_SELECTED身份；@return 原side/action_type/move_id字段，不添加slot信息。
Json Action(const JointActionDetail& action) {
  return {{"side", Side(action.side)}, {"action_type", action.action_type}, {"move_id", action.move_id ? Json(*action.move_id) : Json(nullptr)}};
}
/// @param value 原结构化业务事件；@return 原application DTO，任意精度事实无损编码。
Json Battle(const BattleEvent& value) {
  const auto& data = value.View();
  return {{"kind", BattleEventName(data.kind)}, {"turn_number", data.turn_number}, {"actor", Side(data.actor)}, {"target", Side(data.target)},
      {"move_id", data.move_id ? Json(*data.move_id) : Json(nullptr)}, {"source_identifier", data.source_identifier ? Json(*data.source_identifier) : Json(nullptr)},
      {"value", Number(data.value)}, {"before_value", Number(data.before)}, {"after_value", Number(data.after)}};
}
/// @param value 原普通随机事件；@return 不包含内部metadata身份的原随机DTO。
Json Random(const TransitionEvent& value) {
  const auto& data = value.View();
  return {{"event_type", random_names.at(static_cast<std::size_t>(data.type))}, {"event_id", data.event_id},
      {"outcome_id", data.outcome_id}, {"numeric_value", Number(data.numeric_value)}};
}
/// @tparam Value 固定元素类型；@tparam Project 对应机械投影；@param values 只读数组；@param project 元素转换。
/// @return 完整同序JSON数组，空集合仍是[]。
template<class Value, class Project> Json Array(const std::vector<Value>& values, Project project) {
  auto result = Json::array();
  for (const auto& value : values) result.push_back(project(value));
  return result;
}
/// @param damage 原档位事实；@return 原展示字段，不重新推算伤害或扣血。
Json Damage(const DamageRandomMetadata& damage) {
  return {{"raw_roll_index", damage.raw_roll_index}, {"raw_roll_value", damage.raw_roll_value.str()},
      {"final_damage", damage.final_damage.str()}, {"actual_hp_loss", damage.actual_hp_loss.str()}};
}
/// @param values 任意精度整数列表；@return 同序无损文本数组。
Json Numbers(const std::vector<Integer>& values) { return Array(values, [](const auto& value) { return Json(value.str()); }); }
/// @param path 原路径读取结果；@return 全部随机、伤害和业务事实，保持原顺序。
Json Path(const TransitionEventPathDetail& path) {
  return {{"random_results", Array(path.random_results, Random)}, {"damage_rolls", Array(path.damage_rolls, Damage)}, {"battle_events", Array(path.battle_events, Battle)}};
}
/// @param value 原紧凑结果；@return 完整离散档位与行动结果，不删除空值。
Json Compact(const CompactRandomResult& value) {
  constexpr std::array<std::string_view, 4> statuses{"executed", "blocked", "cancelled", "passed"};
  auto actions = Json::array();
  for (const auto& resolution : value.action_resolutions) {
    auto action = Action(resolution.action);
    action["order_position"] = Number(resolution.order_position);
    action["status"] = statuses.at(static_cast<std::size_t>(resolution.status));
    action["hit"] = resolution.hit ? Json(*resolution.hit) : Json(nullptr);
    action["reason"] = resolution.reason ? Json(*resolution.reason) : Json(nullptr);
    actions.push_back(std::move(action));
  }
  const auto effects = Array(value.status_effects, [](const auto& effect) -> Json {
    return {{"result", effect.result == StatusEffectResult::applied ? "applied" : "prevented"}, {"source_side", Side(effect.source_side)},
        {"target_side", Side(effect.target_side)}, {"source_identifier", effect.source_identifier ? Json(*effect.source_identifier) : Json(nullptr)}};
  });
  return {{"target_node_id", value.target_node_id.value.str()}, {"action_resolutions", std::move(actions)},
      {"order_reason", value.order_reason == ActionOrderReason::speed_tie_random ? "speed-tie-random" : "priority-modifier-speed"},
      {"critical_hit", value.critical_hit ? Json(*value.critical_hit) : Json(nullptr)}, {"raw_roll_values", Numbers(value.raw_roll_values)},
      {"final_damage_values", Numbers(value.final_damage_values)}, {"actual_hp_losses", Numbers(value.actual_hp_losses)},
      {"status_effects", effects}, {"path_count", value.path_count}};
}
/// @param outcome Core完整后继读取值；@return 原application全部公开字段，概率由同Core读取值提供。
Json Outcome(const TransitionOutcome& outcome) {
  const auto& labels = outcome.label_fields;
  return {{"edge_id", outcome.edge_id.value.str()}, {"target_node_id", outcome.target_node_id.value.str()}, {"probability", ExactProbabilityJson(outcome.probability)},
      {"joint_probability", ExactProbabilityJson(outcome.joint_probability)}, {"cumulative_probability", ExactProbabilityJson(outcome.cumulative_probability)},
      {"label_fields", {{"selected_move_ids", labels.selected_move_ids}, {"acting_sides", Array(labels.acting_sides, [](auto side) { return Side(side); })},
          {"target_sides", Array(labels.target_sides, [](auto side) { return Side(side); })}, {"result_keys", labels.result_keys}, {"source_identifiers", labels.source_identifiers}}},
      {"raw_random_values", Numbers(outcome.raw_random_values)}, {"random_results", Array(outcome.random_results, Random)},
      {"damage_rolls", Array(outcome.damage_rolls, Damage)}, {"compact_results", Array(outcome.compact_results, Compact)},
      {"battle_event_paths", Array(outcome.battle_event_paths, [](const auto& path) { return Array(path, Battle); })}, {"event_paths", Array(outcome.event_paths, Path)}};
}
/// @param value 正式状态codec的单个status对象；@return 原展示DTO所有显式可空字段。
Json Status(Json value) {
  for (const auto* name : {"turns_asleep", "toxic_counter", "turns_remaining", "source_id"}) if (!value.contains(name)) value[name] = nullptr;
  return value;
}
/// @param value 正式StateJson中的一侧；@param battler 原执行枚举状态，透明rawcontext不改变其UNKNOWN展示。
/// @return 原BattlerDetail机械字段投影，不计算任何规则。
Json Battler(const Json& value, const BattlerState& battler) {
  const auto& spec = value.at("spec");
  const auto pokemon = PokemonJson(battler.View().spec.View().pokemon);
  auto moves = value.at("move_slots");
  for (auto& move : moves) move.erase("slot_id");
  auto volatile_statuses = value.at("status").at("volatile");
  for (auto& status : volatile_statuses) status = Status(std::move(status));
  std::ranges::sort(volatile_statuses.get_ref<Json::array_t&>(), [](const auto& first, const auto& second) { return first.at("kind") < second.at("kind"); });
  constexpr std::array stage_names{"attack", "defense", "special_attack", "special_defense", "speed", "accuracy", "evasion"};
  auto stages = Json::object();
  for (std::size_t index = 0; index < stage_names.size(); ++index) stages[stage_names[index]] = value.at("stages").at(index);
  return {{"pokemon_id", spec.at("pokemon_id")}, {"name", spec.at("name")}, {"ability", pokemon.at("ability") == "none" ? Json("unknown") : pokemon.at("ability")}, {"item", pokemon.at("item") == "none" ? Json("unknown") : pokemon.at("item")},
      {"current_hp", value.at("current_hp")}, {"max_hp", pokemon.at("stats").at("hp")}, {"moves", std::move(moves)},
      {"major_status", value.at("status").at("major").is_null() ? Json(nullptr) : Status(value.at("status").at("major"))},
      {"volatile_statuses", std::move(volatile_statuses)}, {"stat_stages", std::move(stages)}, {"last_move_id", value.at("last_move_id")},
      {"choice_lock_move_id", value.at("choice_lock_move_id")}, {"item_consumed", value.at("item_consumed")}, {"first_turn", value.at("is_first_turn")}};
}
/// @param node 原拥有节点；@param outgoing 是否有正式出边；@return 原完整节点读取模型，不丢失unknown。
Json Node(const StateGraphProjectionNode& node, bool outgoing) {
  const auto state = StateJson(node.state);
  const auto& field = state.at("field");
  return {{"node_id", node.id.value.str()}, {"turn_number", state.at("turn_number")}, {"phase", state.at("phase")},
      {"outcome", outcomes.at(static_cast<std::size_t>(node.outcome))}, {"termination_reason", Reason(node.reason)},
      {"attacker", Battler(state.at("attacker"), node.state.View().attacker)}, {"defender", Battler(state.at("defender"), node.state.View().defender)},
      {"field", {{"weather", field.at("weather") == "none" ? Json(nullptr) : field.at("weather")},
          {"terrain", field.at("terrain") == "none" ? Json(nullptr) : field.at("terrain")},
          {"attacker_side_conditions", field.at("attacker_side")}, {"defender_side_conditions", field.at("defender_side")}}},
      {"terminal", node.outcome == GraphOutcome::attacker_win || node.outcome == GraphOutcome::defender_win || node.outcome == GraphOutcome::draw},
      {"has_outgoing_edges", outgoing}};
}
} // namespace

StateGraphProjectionNode ReadProjectionNodeValue(const Json& record, CancellationToken stop) {
  Check(stop);
  RequireFields(record, {"id", "state", "outcome", "reason", "predecessor_node", "predecessor_edge", "path"});
  auto state = ReadBattleStateValue(record.at("state"));
  StateGraphProjectionNode node{{Identity(record.at("id"), stop)}, std::move(state), ReadEnum<GraphOutcome>(record.at("outcome"), outcomes), ReadReason(record.at("reason"))};
  for (const auto* field : {"predecessor_node", "predecessor_edge"}) if (!record.at(field).is_null()) static_cast<void>(Identity(record.at(field), stop));
  if (!record.at("path").is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "node representative path must be an array");
  for (const auto& id : record.at("path")) static_cast<void>(Identity(id, stop));
  return node;
}

StateGraphProjectionEdge ReadProjectionEdgeValue(const Json& edge, CancellationToken stop) {
  Check(stop);
  RequireFields(edge, {"id", "source", "target", "probability", "source_key", "paths"});
  return {{Identity(edge.at("id"), stop)}, {Identity(edge.at("source"), stop)}, {Identity(edge.at("target"), stop)}, ReadProjectionFraction(edge.at("probability"), stop),
      ReadProjectionEventSummaryValue(edge.at("paths"), stop), edge.at("source_key").is_null() ? std::nullopt : std::optional{edge.at("source_key").get<std::string>()}};
}

StateGraphProjectionRequest ReadStateGraphProjectionRequest(const Json& value, std::size_t available_edges, CancellationToken stop) {
  Check(stop);
  if (!value.is_object() || !value.contains("mode")) throw RequestError(PBI_INVALID_INPUT_V1, "projection requires a mode");
  const bool step = value.at("mode") == "step";
  if (step) RequireFields(value, {"kind", "mode", "node", "outgoing_edges", "cumulative_probability", "edge_id", "depth"});
  else {
    RequireSchema(value, {"kind", "mode", "node", "outgoing_edges", "cumulative_probability"}, {"expanded_group_ids"});
    if (value.at("mode") != "node") throw RequestError(PBI_UNSUPPORTED_V1, "unknown projection mode");
  }
  if (value.at("kind") != "state_graph_projection") throw RequestError(PBI_INVALID_INPUT_V1, "invalid projection operation kind");
  auto node = ReadProjectionNodeValue(value.at("node"), stop);
  const auto& records = value.at("outgoing_edges");
  if (!records.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "projection outgoing edges must be an array");
  if (records.size() > available_edges) throw RequestError(PBI_RESOURCE_LIMIT_V1, "projection edge input exceeds ABI budget");
  std::vector<StateGraphProjectionEdge> edges;
  std::vector<Integer> ids;
  for (const auto& edge : records) {
    Check(stop);
    auto parsed = ReadProjectionEdgeValue(edge, stop);
    if (std::ranges::find(ids, parsed.id.value) != ids.end()) throw RequestError(PBI_INVALID_INPUT_V1, "projection edge IDs must be unique");
    ids.push_back(parsed.id.value);
    edges.push_back(std::move(parsed));
  }
  std::vector<std::string> expanded;
  if (value.contains("expanded_group_ids")) {
    if (!value.at("expanded_group_ids").is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "expanded group IDs must be an array");
    for (const auto& id : value.at("expanded_group_ids")) expanded.push_back(id.get<std::string>());
  }
  const auto query = [&]() -> std::variant<ProjectionNodeQuery, ProjectionStepQuery> {
    if (!step) return ProjectionNodeQuery{std::move(expanded)};
    const auto depth = Index(value.at("depth"));
    if (depth == 0) throw RequestError(PBI_INVALID_INPUT_V1, "report depth must be positive");
    return ProjectionStepQuery{{Identity(value.at("edge_id"), stop)}, depth};
  }();
  return {std::move(node), std::move(edges), ReadProjectionFraction(value.at("cumulative_probability"), stop), query};
}

Json StateGraphProjectionJson(const BattleNodeProjection& projection, CancellationToken stop) {
  auto groups = Json::array();
  for (const auto& group : projection.transition_groups) {
    Check(stop);
    groups.push_back({{"group_id", group.group_id}, {"kind", group_names.at(static_cast<std::size_t>(group.kind))}, {"label_key", group.label_key},
        {"probability", ExactProbabilityJson(group.selection_probability)}, {"selection_probability", ExactProbabilityJson(group.selection_probability)},
        {"attacker_action", group.attacker_action ? Action(*group.attacker_action) : Json(nullptr)},
        {"defender_action", group.defender_action ? Action(*group.defender_action) : Json(nullptr)},
        {"raw_result_count", group.raw_result_count}, {"distinct_outcome_count", group.distinct_outcome_count},
        {"summary", {{"minimum_damage", Number(group.summary.minimum_damage)}, {"maximum_damage", Number(group.summary.maximum_damage)},
            {"minimum_hp_loss", Number(group.summary.minimum_hp_loss)}, {"maximum_hp_loss", Number(group.summary.maximum_hp_loss)}}},
        {"expanded", group.expanded}, {"outcomes", Array(group.outcomes, Outcome)}});
  }
  Check(stop);
  return {{"node", Node(projection.node, projection.has_outgoing_edges)}, {"cumulative_probability", ExactProbabilityJson(projection.cumulative_probability)},
      {"transition_groups", std::move(groups)}};
}

Json RepresentativeBattlePathsJson(const std::vector<RepresentativeBattlePath>& paths, CancellationToken stop) {
  constexpr std::array<std::string_view, 4> phases{"action-selection", "action-resolution", "end-of-turn", "terminal"};
  auto result = Json::array();
  for (const auto& path : paths) {
    Check(stop);
    auto steps = Json::array();
    for (const auto& step : path.steps) {
      Check(stop);
      steps.push_back({{"node_id", step.node_id.value.str()}, {"turn_number", step.turn_number}, {"phase", phases.at(static_cast<std::size_t>(step.phase))},
          {"attacker_hp", step.attacker_hp}, {"defender_hp", step.defender_hp}, {"outcome", outcomes.at(static_cast<std::size_t>(step.outcome))}, {"events", step.events}});
    }
    result.push_back({{"reference", path.reference}, {"outcome", outcomes.at(static_cast<std::size_t>(path.outcome))}, {"steps", std::move(steps)}});
  }
  return result;
}

Json BattleReportStepJson(const BattleReportStep& step, CancellationToken stop) {
  Check(stop);
  auto result = Json{{"depth", step.depth}, {"source_node_id", step.source_node_id.value.str()}, {"edge_id", step.edge_id.value.str()},
      {"target_node_id", step.target_node_id.value.str()}, {"edge_probability", ExactProbabilityJson(step.edge_probability)},
      {"cumulative_probability", ExactProbabilityJson(step.cumulative_probability)}, {"event_paths", Array(step.event_paths, Path)}};
  Check(stop);
  return result;
}

Json EvaluateStateGraphProjection(const StateGraphProjectionRequest& request, CancellationToken stop) {
  try {
    if (const auto* query = std::get_if<ProjectionStepQuery>(&request.query)) {
      const auto edge = std::ranges::find(request.outgoing_edges, query->edge_id, &StateGraphProjectionEdge::id);
      if (edge == request.outgoing_edges.end()) throw RequestError(PBI_INVALID_INPUT_V1, "report edge is not available from current node");
      const auto result = ProjectBattleGraphStep(request.node, *edge, request.cumulative_probability, query->depth, stop);
      return {{"kind", "state_graph_projection"}, {"mode", "step"}, {"step", BattleReportStepJson(result, stop)}};
    }
    const auto& query = std::get<ProjectionNodeQuery>(request.query);
    return {{"kind", "state_graph_projection"}, {"mode", "node"}, {"projection", StateGraphProjectionJson(ProjectBattleGraphNode(request.node,
        request.outgoing_edges, request.cumulative_probability, query.expanded_group_ids, stop), stop)}};
  } catch (const std::runtime_error&) {
    if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "state graph projection cancelled");
    throw;
  }
}
} // namespace pbi::contract
