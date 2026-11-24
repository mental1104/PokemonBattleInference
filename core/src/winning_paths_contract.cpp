#include "winning_paths_contract.hpp"
#include <algorithm>
#include <array>
#include <limits>

namespace pbi::contract {
namespace {
constexpr std::array<std::string_view, 2> sides{"attacker", "defender"};
constexpr std::array<std::string_view, 3> truncations{"max-turns", "max-nodes", "max-edges"};
constexpr std::array<std::string_view, 4> component_kinds{"acyclic", "closed-cycle", "terminal-reachable-cycle", "open-unresolved-cycle"};
constexpr std::string_view sort_name = "shortest-high-probability";
/// @param stop 同源令牌；中断整批，不输出部分游标/组/前缀。
void Check(CancellationToken stop) { if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "winning paths cancelled"); }
/// @param message 原WinningPathQueryError文案；业务查询错误统一既有invalid_input供HTTP409机械映射。
[[noreturn]] void QueryError(const char* message) { throw RequestError(PBI_INVALID_INPUT_V1, message); }
/// @param value 已验证/未验证cursor原始字节；@return 不填充的RFC4648 URL-safe编码，与原Python一致。
std::string Encode64(std::string_view value) {
  constexpr std::string_view alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  std::string result; unsigned accumulator = 0; unsigned bits = 0;
  for (const unsigned char byte : value) {
    accumulator = (accumulator << 8) | byte; bits += 8;
    while (bits >= 6) { bits -= 6; result += alphabet[(accumulator >> bits) & 63U]; }
  }
  if (bits != 0) result += alphabet[(accumulator << (6 - bits)) & 63U];
  return result;
}
/// @param cursor 原ASCII分页游标；@return 原非strict urlsafe_b64decode字节，保留其忽略非字母与补齐规则。
std::string Decode64(const std::string& cursor) {
  std::string input = cursor; input.append((4 - input.size() % 4) % 4, '=');
  std::string result; unsigned accumulator = 0; unsigned position = 0; unsigned padding = 0;
  for (const unsigned char byte : input) {
    if (byte > 127) QueryError("cursor is malformed");
    if (byte == '=') {
      if (position >= 2 && position + ++padding >= 4) return result;
      continue;
    }
    unsigned decoded;
    if (byte >= 'A' && byte <= 'Z') decoded = byte - 'A';
    else if (byte >= 'a' && byte <= 'z') decoded = byte - 'a' + 26;
    else if (byte >= '0' && byte <= '9') decoded = byte - '0' + 52;
    else if (byte == '+' || byte == '-') decoded = 62;
    else if (byte == '/' || byte == '_') decoded = 63;
    else continue;
    padding = 0; accumulator = (accumulator << 6) | decoded;
    if (position != 0) result += static_cast<char>((accumulator >> (6 - 2 * position)) & 255U);
    position = (position + 1) % 4;
  }
  if (position != 0) QueryError("cursor is malformed");
  return result;
}
/// 原cursor任意精度整数词法与普通JSON分开，避免JSON库先经double丢失/拒绝巨大offset。
struct CursorDocument { Json value; std::optional<std::string> version_token; std::optional<std::string> offset_token; };
/// @param text 一个原JSON数字词法；@return 完整JSON number grammar，不经机器数值解析或递归regex栈。
bool JsonNumber(std::string_view text) {
  std::size_t index = text.starts_with('-') ? 1 : 0;
  const auto digit = [](char byte) { return byte >= '0' && byte <= '9'; };
  if (index == text.size()) return false;
  if (text[index] == '0') ++index;
  else {
    if (text[index] < '1' || text[index] > '9') return false;
    while (index < text.size() && digit(text[index])) ++index;
  }
  if (index < text.size() && text[index] == '.') {
    const auto first = ++index;
    while (index < text.size() && digit(text[index])) ++index;
    if (first == index) return false;
  }
  if (index < text.size() && (text[index] == 'e' || text[index] == 'E')) {
    ++index;
    if (index < text.size() && (text[index] == '+' || text[index] == '-')) ++index;
    const auto first = index;
    while (index < text.size() && digit(text[index])) ++index;
    if (first == index) return false;
  }
  return index == text.size();
}
/// @param raw 原UTF8 JSON；@return 由标准JSON parser验证结构/字符串，整数和浮点原词法另存，不缩窄offset。
CursorDocument ReadCursorDocument(const std::string& raw) {
  CursorDocument result; std::string normalized; std::string key; int depth = 0;
  for (std::size_t index = 0; index < raw.size();) {
    const char byte = raw[index];
    if (byte == '"') {
      const auto first = index++;
      while (index < raw.size()) {
        if (raw[index] == '\\') { index += 2; continue; }
        if (raw[index++] == '"') break;
      }
      const auto token = raw.substr(first, index - first);
      const auto text = Json::parse(token).get<std::string>();
      auto next = index; while (next < raw.size() && (raw[next] == ' ' || raw[next] == '\r' || raw[next] == '\n' || raw[next] == '\t')) ++next;
      if (depth == 1 && next < raw.size() && raw[next] == ':') {
        key = text;
        if (key == "v") result.version_token.reset();
        if (key == "offset") result.offset_token.reset();
      }
      normalized += token; continue;
    }
    // Python json.loads默认允许这些非有限浮点；它们不是合法offset，但无关extra字段不影响cursor。
    std::size_t nonfinite_size = 0;
    for (const auto token : {std::string_view{"NaN"}, std::string_view{"Infinity"}, std::string_view{"-Infinity"}})
      if (std::string_view{raw}.substr(index).starts_with(token)) { nonfinite_size = token.size(); break; }
    if (nonfinite_size != 0) {
      if (depth == 1 && key == "v") result.version_token = raw.substr(index, nonfinite_size);
      if (depth == 1 && key == "offset") result.offset_token = raw.substr(index, nonfinite_size);
      normalized += '0'; index += nonfinite_size; continue;
    }
    if ((byte >= '0' && byte <= '9') || byte == '-') {
      const auto first = index++;
      while (index < raw.size() && std::string_view{"0123456789eE+-."}.find(raw[index]) != std::string_view::npos) ++index;
      const auto token = raw.substr(first, index - first);
      if (!JsonNumber(token)) QueryError("cursor is malformed");
      if (depth == 1 && key == "v") result.version_token = token;
      if (depth == 1 && key == "offset") result.offset_token = token;
      normalized += '0'; continue;
    }
    if (byte == '{' || byte == '[') ++depth;
    if (byte == '}' || byte == ']') --depth;
    normalized += byte; ++index;
  }
  result.value = Json::parse(normalized);
  return result;
}
/// @param text 原graph/revision/cursor；@return 原Python Unicode strip是否改变首尾；内部空白不修改。
bool Unnormalized(const std::string& text) {
  if (text.empty()) return true;
  const auto ascii_space = [](unsigned char byte) { return (byte >= 9 && byte <= 13) || (byte >= 28 && byte <= 32); };
  if (ascii_space(text.front()) || ascii_space(text.back())) return true;
  constexpr std::array<std::string_view, 19> spaces{"\xc2\x85", "\xc2\xa0", "\xe1\x9a\x80", "\xe2\x80\x80", "\xe2\x80\x81", "\xe2\x80\x82", "\xe2\x80\x83", "\xe2\x80\x84", "\xe2\x80\x85", "\xe2\x80\x86", "\xe2\x80\x87", "\xe2\x80\x88", "\xe2\x80\x89", "\xe2\x80\x8a", "\xe2\x80\xa8", "\xe2\x80\xa9", "\xe2\x80\xaf", "\xe2\x81\x9f", "\xe3\x80\x80"};
  return std::ranges::any_of(spaces, [&](auto value) { return text.starts_with(value) || text.ends_with(value); });
}
/// @param query 已验证原查询；@param configuration Core唯一配置身份；@return 不含offset的原cursor绑定。
Json Binding(const WinningPathQuery& query, const WinningPathConfiguration& configuration) {
  return {{"v", 1}, {"graph_id", query.graph_id}, {"calculation_revision", query.calculation_revision},
      {"configuration_key", configuration.configuration_key}, {"winner", sides.at(static_cast<std::size_t>(query.winner))}, {"sort", sort_name}};
}
/// @param value 原可空cursor；@param query 同图查询；@param configuration 同Core配置。
/// @return 精确非负offset；保留原查询不匹配与offset非法的不同文案。
Integer DecodeCursor(const Json& value, const WinningPathQuery& query, const WinningPathConfiguration& configuration) {
  if (value.is_null()) return 0;
  if (!value.is_string() || Unnormalized(value.get<std::string>())) QueryError("cursor must be a normalized string or None");
  CursorDocument document;
  try { document = ReadCursorDocument(Decode64(value.get<std::string>())); }
  catch (const RequestError&) { throw; }
  catch (const std::exception&) { QueryError("cursor is malformed"); }
  const auto expected = Binding(query, configuration);
  if (!document.value.is_object()) QueryError("cursor is malformed");
  for (const auto& [key, field] : expected.items()) {
    if (key == "v") continue;
    if (!document.value.contains(key) || document.value.at(key) != field) QueryError("cursor does not belong to this winning-path query");
  }
  bool version = document.value.value("v", Json{}) == Json(true);
  if (document.version_token) {
    try { version = std::stod(*document.version_token) == 1; } catch (const std::exception&) { version = false; }
  }
  if (!version) QueryError("cursor does not belong to this winning-path query");
  if (!document.offset_token || document.offset_token->find_first_not_of("-0123456789") != std::string::npos) QueryError("cursor offset must be a non-negative integer");
  Integer result = 0; const auto& text = *document.offset_token;
  const auto first = text.front() == '-' ? 1U : 0U;
  for (std::size_t index = first; index < text.size(); ++index) result = result * 10 + (text[index] - '0');
  if (first != 0 && result != 0) QueryError("cursor offset must be a non-negative integer");
  return result;
}
/// @param result 原完整Core结果；@return Python ensure_ascii/compact/sort_keys唯一不填充cursor。
std::optional<std::string> EncodeCursor(const WinningPathGroupsResult& result) {
  if (!result.next_offset) return std::nullopt;
  const WinningPathQuery query{result.graph_id, result.calculation_revision, result.winner};
  auto binding = Binding(query, result.configuration); binding["offset"] = result.next_offset->convert_to<std::size_t>();
  const auto json = binding.dump(-1, ' ', true); std::string ascii;
  for (const char byte : json) if (byte == 127) ascii += "\\u007f"; else ascii += byte;
  return Encode64(ascii);
}
/// @param value 非负JSON整数/十进制文本；@return 平台可表示的正式输入预算/索引，不截断。
std::size_t Index(const Json& value) {
  const Integer integer = value.is_string() ? ReadDecimalInteger(value) : Integer{ReadInteger(value)};
  if (integer < 0 || integer > std::numeric_limits<std::size_t>::max()) QueryError("winning path index is outside platform range");
  return integer.convert_to<std::size_t>();
}
/// @tparam Value 元素拥有类型；@tparam Project 机械编码；@param values 原顺序值；@param project 唯一字段编码。
/// @return 完整JSON数组，空数组不转null。
template<class Value, class Project> Json Array(const std::vector<Value>& values, Project project) {
  auto result = Json::array(); for (const auto& value : values) result.push_back(project(value)); return result;
}
/// @param value 可空普通整数/字符串；@return 完整原可空字段，普通int64仍是JSON整数。
template<class Value> Json Optional(const std::optional<Value>& value) { return value ? Json(*value) : Json(nullptr); }
/// @param value 原四字段候选；@return 原联合行动JSON，无投影groupID或虚构概率。
Json Alternative(const WinningJointActionAlternative& value) {
  return {{"attacker_move_id", Optional(value.attacker_move_id)}, {"defender_move_id", Optional(value.defender_move_id)},
      {"attacker_source_identifier", Optional(value.attacker_source_identifier)}, {"defender_source_identifier", Optional(value.defender_source_identifier)}};
}
/// @param value 原回合全部候选；@return 主字段只有唯一解释时填充，歧义候选始终完整。
Json Action(const WinningJointActionStep& value) {
  auto result = Alternative(value.exact.value_or(WinningJointActionAlternative{}));
  result["turn_number"] = value.turn_number; result["ambiguous"] = value.alternatives.size() > 1;
  result["alternatives"] = Array(value.alternatives, Alternative); return result;
}
/// @param value 原侧配置；@return 原机械UNKNOWN，不泄漏透明rawcontext为已执行机制。
Json ConfigurationSide(const WinningPathConfigurationSide& value) {
  return {{"pokemon_id", value.pokemon_id}, {"name", value.name}, {"level", value.level}, {"ability_identifier", value.ability_identifier},
      {"item_identifier", value.item_identifier}, {"move_ids", value.move_ids}};
}
/// @param value 原关键事件；@return 原稳定侧/种类，不解析文案。
Json KeyEvent(const WinningPathKeyEvent& value) {
  return {{"kind", BattleEventName(value.kind)}, {"actor", value.actor ? Json(sides.at(static_cast<std::size_t>(*value.actor))) : Json(nullptr)},
      {"target", value.target ? Json(sides.at(static_cast<std::size_t>(*value.target))) : Json(nullptr)}, {"move_id", Optional(value.move_id)}, {"source_identifier", Optional(value.source_identifier)}};
}
/// @param group 完整纯组；@return 数量/ID/任意精度伤害十进制文本，HTTP边界只机械转json.Number。
Json Group(const WinningPathGroup& group) {
  return {{"path_key", group.path_key}, {"terminal_turn", group.terminal_turn}, {"probability", ExactProbabilityJson(group.probability)},
      {"raw_path_count", group.raw_path_count.str()}, {"raw_history_count_estimate", group.raw_history_count_estimate.str()},
      {"terminal_reasons", group.terminal_reasons}, {"terminal_node_ids", Array(group.terminal_node_ids, [](const auto& value) { return Json(value.value.str()); })},
      {"actions", Array(group.actions, Action)}, {"representative_path", Array(group.representative_path, [](const auto& value) -> Json {
        return {{"source_node_id", value.source.value.str()}, {"edge_id", value.edge.value.str()}, {"target_node_id", value.target.value.str()}};
      })}, {"damage_values", Array(group.damage_values, [](const auto& value) { return Json(value.str()); })},
      {"attacker_remaining_hp_values", group.attacker_remaining_hp_values}, {"defender_remaining_hp_values", group.defender_remaining_hp_values}, {"key_events", Array(group.key_events, KeyEvent)}};
}
/// @param value 原当前页前缀；@param stop 同源取消；@return 完整原前缀字段，不重新归并或重算概率。
Json Prefix(const WinningPathPrefixNode& value, CancellationToken stop) {
  Check(stop);
  return {{"prefix_key", value.prefix_key}, {"depth", value.depth}, {"action", value.action ? Action(*value.action) : Json(nullptr)},
      {"probability", ExactProbabilityJson(value.probability)}, {"raw_path_count", value.raw_path_count.str()}, {"terminal_path_keys", value.terminal_path_keys},
      {"children", Array(value.children, [&](const auto& child) { return Prefix(child, stop); })}};
}
/// @param value owning schema已校验的查询对象；@return 原共同参数/默认值，cursor稍后绑定图配置。
WinningPathQuery ReadQueryFields(const Json& value) {
  WinningPathQuery query{value.at("graph_id").get<std::string>(), value.at("calculation_revision").get<std::string>(), ReadEnum<BattleSide>(value.at("winner"), sides)};
  if (Unnormalized(query.graph_id)) QueryError("graph_id must be a non-empty normalized string");
  if (Unnormalized(query.calculation_revision)) QueryError("calculation_revision must be a non-empty normalized string");
  if (value.contains("limit")) query.limit = Index(value.at("limit"));
  if (query.limit < 1 || query.limit > 100) QueryError("limit must be between 1 and 100");
  if (value.contains("sort") && value.at("sort") != sort_name) QueryError("sort must be a WinningPathSort");
  if (value.contains("max_traversed_walks")) query.max_traversed_walks = Index(value.at("max_traversed_walks"));
  if (query.max_traversed_walks == 0) QueryError("max_traversed_walks must be greater than 0");
  return query;
}
} // namespace

WinningPathQuery ReadWinningPathQueryValue(const Json& value, const WinningPathConfiguration& configuration, CancellationToken stop) {
  Check(stop); auto query = ReadQueryFields(value);
  query.offset = DecodeCursor(value.value("cursor", Json(nullptr)), query, configuration);
  return query;
}
WinningPathsRequest ReadWinningPathsRequest(const Json& value, std::size_t available_nodes, std::size_t available_edges, CancellationToken stop) {
  Check(stop);
  RequireSchema(value, {"kind", "graph_id", "calculation_revision", "winner", "graph"}, {"limit", "cursor", "sort", "max_traversed_walks"});
  auto query = ReadQueryFields(value);
  const auto& records = value.at("graph"); RequireSchema(records, {"nodes", "edges", "components", "truncations"}, {"root", "statistics"});
  if (!records.at("nodes").is_array() || !records.at("edges").is_array() || !records.at("components").is_array() || !records.at("truncations").is_array()) QueryError("winning graph records must be arrays");
  if (records.at("nodes").size() > available_nodes || records.at("edges").size() > available_edges) throw RequestError(PBI_RESOURCE_LIMIT_V1, "winning graph input exceeds ABI budget");
  WinningPathGraph graph;
  for (const auto& node : records.at("nodes")) { Check(stop); graph.nodes.push_back(ReadProjectionNodeValue(node, stop)); }
  for (const auto& edge : records.at("edges")) { Check(stop); graph.edges.push_back(ReadProjectionEdgeValue(edge, stop)); }
  if (records.contains("root")) graph.root.value = Index(records.at("root"));
  for (const auto& component : records.at("components")) {
    Check(stop); RequireFields(component, {"id", "nodes", "kind", "outgoing", "reaches_terminal"});
    WinningPathComponent entry{{Index(component.at("id"))}, {}, ReadEnum<ComponentKind>(component.at("kind"), component_kinds)};
    if (!component.at("nodes").is_array()) QueryError("winning component nodes must be an array");
    for (const auto& node : component.at("nodes")) entry.nodes.push_back({Integer{Index(node)}});
    graph.components.push_back(std::move(entry));
  }
  for (const auto& truncation : records.at("truncations")) graph.truncations.push_back(ReadEnum<GraphTruncation>(truncation, truncations));
  const auto configuration = DescribeWinningPathConfiguration(graph);
  query.offset = DecodeCursor(value.value("cursor", Json(nullptr)), query, configuration);
  return {std::move(graph), std::move(query)};
}
Json WinningPathGroupsJson(const WinningPathGroupsResult& result, CancellationToken stop) {
  const auto& configuration = result.configuration; Check(stop);
  return {{"kind", "winning_paths"}, {"graph_id", result.graph_id}, {"calculation_revision", result.calculation_revision},
      {"winner", sides.at(static_cast<std::size_t>(result.winner))}, {"sort", sort_name},
      {"configuration", {{"configuration_key", configuration.configuration_key}, {"attacker", ConfigurationSide(configuration.attacker)}, {"defender", ConfigurationSide(configuration.defender)}}},
      {"winner_probability", result.winner_probability ? ExactProbabilityJson(*result.winner_probability) : Json(nullptr)},
      {"returned_probability", ExactProbabilityJson(result.returned_probability)}, {"returned_coverage", result.returned_coverage ? ExactProbabilityJson(*result.returned_coverage) : Json(nullptr)},
      {"path_groups", Array(result.path_groups, Group)}, {"prefix_tree", Prefix(result.prefix_tree, stop)},
      {"cycle_references", Array(result.cycle_references, [](const auto& cycle) -> Json {
        return {{"source_node_id", cycle.source.value.str()}, {"edge_id", cycle.edge.value.str()}, {"target_node_id", cycle.target.value.str()},
            {"prefix_depth", cycle.prefix_depth}, {"component_id", cycle.component ? Json(cycle.component->value) : Json(nullptr)}};
      })}, {"next_cursor", Optional(EncodeCursor(result))}, {"has_more", result.has_more}, {"query_complete", result.query_complete}, {"traversal_truncated", result.traversal_truncated}};
}
Json EvaluateWinningPaths(const WinningPathsRequest& request, CancellationToken stop) {
  const auto result = [&] {
    try { return ListWinningPathGroups(request.graph, request.query, stop); }
    catch (const std::runtime_error&) { Check(stop); throw; }
  }();
  return WinningPathGroupsJson(result, stop);
}
} // namespace pbi::contract
