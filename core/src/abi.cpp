// C ABI 只负责协议、所有权与错误隔离，计算规则由 typed Core 唯一实现。
#include "pbi_core.h"
#include "pbi/calculations.hpp"
#include "pbi/damage.hpp"
#include "pbi/profile.hpp"
#include "json_contract.hpp"
#include "state_contract.hpp"
#include "graph_contract.hpp"

#include <nlohmann/json.hpp>
#include <stop_token>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <new>
#include <stdexcept>
#include <string>
#include <string_view>
#include <variant>
#include <type_traits>
#include <vector>

/// 单向线程安全取消源，无共享计算状态；不透明布局由 C ABI 独占。
struct pbi_cancel_token_v1 {
  std::stop_source source;
};

namespace {
using namespace pbi::contract;
constexpr std::size_t kMaxBytes = PBI_V1_MAX_REQUEST_BYTES;
constexpr std::size_t kMaxOperations = PBI_V1_MAX_OPERATIONS;
constexpr std::size_t kMaxRolls = PBI_V1_MAX_ROLLS;
constexpr std::size_t kMaxTotalRolls = PBI_V1_MAX_TOTAL_ROLLS;

/// 固定协议在边界转换为静态计算输入，不把 JSON 传进领域层。
struct HpRequest { pbi::StatInput input; };
/// 非 HP 输入保存显式性格枚举，不使用浮点倍率。
struct StatRequest { pbi::StatInput input; pbi::NatureEffect nature; };
/// 能力等级输入独立于能力配置，允许完整 int64 能力值。
struct StageRequest { std::int64_t value; std::int32_t stage; };
/// KO 请求拥有伤害档位副本，不借用解析器内部节点。
struct KoRequest { std::vector<std::int64_t> rolls; std::int32_t hp; };
/// 直接伤害请求拥有领域输入与知识快照，并记录原有兼容代际身份。
struct DamageRequest { pbi::DamageInput input; pbi::TypeChartSnapshot knowledge; std::int32_t generation; };
/// 完整能力配置复用领域性格选择和能力公式。
struct ProfileRequest { pbi::StatProfile input; };
using Operation = std::variant<HpRequest, StatRequest, StageRequest, KoRequest, DamageRequest, BattleStateRequest, StatusModifiersRequest, ProfileRequest, GraphRequest, LegalActionsRequest>;

/// @param token 只读借用的可空令牌；已取消时抛出 RequestError，无副作用。
void CheckCancelled(const pbi_cancel_token_v1* token) {
  if (token && token->source.stop_requested()) {
    throw RequestError(PBI_CANCELLED_V1, "calculation cancelled");
  }
}

/// @param object 已确认字段齐全的只读能力对象；@return 新的领域输入快照。
pbi::StatInput ReadStat(const Json& object) {
  return {ReadInt32(object.at("base")), ReadInt32(object.at("iv")),
          ReadInt32(object.at("ev")), ReadInt32(object.at("level"))};
}

/// @param value 标准十分制性格；@return 显式枚举，未知倍率返回 UNSUPPORTED。
pbi::NatureEffect ReadNature(const Json& value) {
  switch (ReadInt32(value)) {
  case 9: return pbi::NatureEffect::decreased;
  case 10: return pbi::NatureEffect::neutral;
  case 11: return pbi::NatureEffect::increased;
  default: throw RequestError(PBI_UNSUPPORTED_V1, "unsupported nature effect");
  }
}

/// @param value 只读操作对象；@param remaining_rolls 当前批次余量；@return 拥有所有快照的伤害请求。
DamageRequest ReadDamage(const Json& value, std::size_t remaining_rolls) {
  RequireSchema(value, {"kind", "generation_id", "attacker", "defender", "move", "type_chart"},
      {"policy", "weather", "terrain", "defender_side", "critical", "spread", "protect_reduced", "multi_target", "version_group_id"});
  const auto generation = ReadInt32(value.at("generation_id"));
  auto policy = pbi::DamagePolicyForGeneration(generation);
  if (value.contains("version_group_id") && pbi::GenerationForVersionGroup(ReadInt32(value.at("version_group_id"))) != generation) {
    throw RequestError(PBI_INVALID_INPUT_V1, "version group does not match generation");
  }
  if (value.contains("policy")) policy = ReadPolicy(value.at("policy"), std::move(policy));
  if (policy.random_damage_multipliers.size() > remaining_rolls) throw RequestError(PBI_RESOURCE_LIMIT_V1, "damage roll budget exceeded");
  const auto& move = value.at("move");
  RequireFields(move, {"type", "category", "power"});
  pbi::DamageInput input{ReadPokemon(value.at("attacker")), ReadPokemon(value.at("defender")),
      {static_cast<pbi::PokemonType>(ReadInt32(move.at("type"))),
       ReadEnum<pbi::DamageCategory>(move.at("category"), std::array<std::string_view, 3>{"physical", "special", "status"}), ReadInt32(move.at("power"))},
      std::move(policy), pbi::DamageWeather::none, pbi::DamageTerrain::none, {}, false, false, false, false};
  if (value.contains("weather")) input.weather = ReadEnum<pbi::DamageWeather>(value.at("weather"),
      std::array<std::string_view, 6>{"none", "harsh_sunlight", "rain", "sandstorm", "hail", "snow"});
  if (value.contains("terrain")) input.terrain = ReadEnum<pbi::DamageTerrain>(value.at("terrain"),
      std::array<std::string_view, 5>{"none", "electric_terrain", "psychic_terrain", "grassy_terrain", "misty_terrain"});
  if (value.contains("defender_side")) {
    const auto& side = value.at("defender_side");
    RequireFields(side, {"reflect", "light_screen", "aurora_veil"});
    input.defender_side = {ReadBool(side.at("reflect")), ReadBool(side.at("light_screen")), ReadBool(side.at("aurora_veil"))};
  }
  if (value.contains("critical")) input.critical = ReadBool(value.at("critical"));
  if (value.contains("spread")) input.spread = ReadBool(value.at("spread"));
  if (value.contains("protect_reduced")) input.protect_reduced = ReadBool(value.at("protect_reduced"));
  if (value.contains("multi_target")) input.multi_target = ReadBool(value.at("multi_target"));
  return {std::move(input), ReadTypeChart(value.at("type_chart")), generation};
}

/// 解码单条计算，并限制实际批次伤害槽位总量。
/// @param object 只读 JSON 操作；@param remaining_rolls 尚可拥有的槽位预算。
/// @param remaining_nodes 本批余下图节点；@param remaining_edges 本批余下图边；@param stop 协作取消。
/// @return 类型化操作和消耗的槽位数；不修改调用方预算。
std::pair<Operation, std::size_t> ReadOperation(const Json& object, std::size_t remaining_rolls,
    std::size_t remaining_nodes, std::size_t remaining_edges, std::stop_token stop) {
  if (!object.is_object() || !object.contains("kind") || !object.at("kind").is_string()) {
    throw RequestError(PBI_INVALID_INPUT_V1, "operation kind must be a string");
  }
  const auto kind = object.at("kind").get<std::string>();
  if (kind == "graph") return {ReadGraphRequest(object, remaining_nodes, remaining_edges, stop), 0};
  if (kind == "legal_actions") {
    auto request = ReadLegalActionsRequest(object, remaining_rolls);
    const auto consumed = request.state.View().rules.View().damage_policy.random_damage_multipliers.size();
    return {std::move(request), consumed};
  }
  if (kind == "profile") {
    RequireFields(object, {"kind", "base", "ivs", "evs", "level", "decreased_stat_id", "increased_stat_id"});
    return {ProfileRequest{{ReadBattleStats(object.at("base")), ReadBattleStats(object.at("ivs")), ReadBattleStats(object.at("evs")),
        ReadInt32(object.at("level")), static_cast<pbi::NatureAxis>(ReadInt32(object.at("decreased_stat_id"))),
        static_cast<pbi::NatureAxis>(ReadInt32(object.at("increased_stat_id")))}}, 0};
  }
  if (kind == "battle_state") {
    auto [request, consumed] = ReadBattleStateRequest(object, remaining_rolls);
    return {std::move(request), consumed};
  }
  if (kind == "status_modifiers") return {ReadStatusModifiersRequest(object), 0};
  if (kind == "damage") {
    auto request = ReadDamage(object, remaining_rolls);
    const auto count = request.input.policy.random_damage_multipliers.size();
    return {std::move(request), count};
  }
  if (kind == "hp") {
    RequireFields(object, {"kind", "base", "iv", "ev", "level"});
    return {HpRequest{ReadStat(object)}, 0};
  }
  if (kind == "stat") {
    RequireFields(object, {"kind", "base", "iv", "ev", "level", "nature_tenths"});
    return {StatRequest{ReadStat(object), ReadNature(object.at("nature_tenths"))}, 0};
  }
  if (kind == "stage") {
    RequireFields(object, {"kind", "value", "stage"});
    return {StageRequest{ReadInteger(object.at("value")), ReadInt32(object.at("stage"))}, 0};
  }
  if (kind == "ko") {
    RequireFields(object, {"kind", "rolls", "defender_hp"});
    const auto& rolls = object.at("rolls");
    if (!rolls.is_array()) {
      throw RequestError(PBI_INVALID_INPUT_V1, "rolls must be an array");
    }
    if (rolls.size() > kMaxRolls || rolls.size() > remaining_rolls) {
      throw RequestError(PBI_RESOURCE_LIMIT_V1, "damage roll budget exceeded");
    }
    std::vector<std::int64_t> values;
    values.reserve(rolls.size());
    for (const auto& value : rolls) values.push_back(ReadInt32(value));
    const auto count = values.size();
    return {KoRequest{std::move(values), ReadInt32(object.at("defender_hp"))}, count};
  }
  throw RequestError(PBI_UNSUPPORTED_V1, "unsupported operation kind");
}

/// @param request 只读 HP 请求；@return 新的协议结果，不持有请求引用。
Json Evaluate(const HpRequest& request) {
  return {{"kind", "hp"}, {"value", pbi::CalculateHp(request.input)}};
}
/// @param request 只读非 HP 请求；@return 新的协议结果。
Json Evaluate(const StatRequest& request) {
  return {{"kind", "stat"}, {"value", pbi::CalculateNonHp(request.input, request.nature)}};
}
/// @param request 只读能力等级请求；@return 新的协议结果。
Json Evaluate(const StageRequest& request) {
  return {{"kind", "stage"}, {"value", pbi::ApplyStatStage(request.value, request.stage)}};
}
/// @param request 拥有伤害槽位的只读请求；@return 含两个精确概率的协议结果。
Json Evaluate(const KoRequest& request) {
  const auto result = pbi::EstimateKoChance(request.rolls, request.hp);
  return {{"kind", "ko"}, {"ohko", FractionJson(result.ohko)}, {"two_hit", FractionJson(result.two_hit)},
          {"guaranteed_ohko", result.guaranteed_ohko}, {"guaranteed_two_hit", result.guaranteed_two_hit}};
}

/// @param request 只读完整伤害请求；@return 同一 Core 的完整伤害/trace/KO 协议结果。
Json Evaluate(const DamageRequest& request) {
  return DamageJson(pbi::CalculateDamage(request.input, request.knowledge), request.generation);
}
/// @param request 只读状态更新请求；@return 纯 Core 的完整状态/键等价/可选伤害结果。
Json Evaluate(const BattleStateRequest& request) { return EvaluateBattleState(request); }
/// @param request 只读状态修正请求；@return 精确倍率和独立速度修正。
Json Evaluate(const StatusModifiersRequest& request) { return EvaluateStatusModifiers(request); }
/// @param request 只读完整配置；@return 同一 Core 计算的六项实际能力。
Json Evaluate(const ProfileRequest& request) { return {{"kind", "profile"}, {"stats", BattleStatsJson(pbi::CalculateStats(request.input))}}; }
/// @param request 只读状态和策略；@return 同 Core 生成的完整合法行动与精确选择概率。
Json Evaluate(const LegalActionsRequest& request) { return EvaluateLegalActions(request); }

/// @return 所有成功/失败响应共有的版本信息，新对象无共享状态。
Json Envelope() {
  return {{"schema_version", 1}, {"engine_version", PBI_ENGINE_VERSION}, {"rules_version", "calculation-rules.v5"}};
}

/// @param code 稳定错误枚举；@return 静态 ASCII 名称，无所有权转移。
const char* StatusName(pbi_status_v1 code) {
  switch (code) {
  case PBI_OK_V1: return "ok";
  case PBI_INVALID_INPUT_V1: return "invalid_input";
  case PBI_UNSUPPORTED_V1: return "unsupported";
  case PBI_RESOURCE_LIMIT_V1: return "resource_limit";
  case PBI_CANCELLED_V1: return "cancelled";
  case PBI_INTERNAL_ERROR_V1: return "internal_error";
  }
  return "internal_error";
}

/// @param encoded 完整 JSON 字节；@param output 已确认零初始化的非空输出。
/// @return 无；复制成功后才转移所有权，malloc 失败抛出 bad_alloc。
void WriteBuffer(const std::string& encoded, pbi_buffer_v1* output) {
  auto* data = static_cast<std::uint8_t*>(std::malloc(encoded.size()));
  if (!data) throw std::bad_alloc{};
  std::memcpy(data, encoded.data(), encoded.size());
  *output = {data, encoded.size()};
}

/// 最后一层错误隔离；即使错误编码内存不足也不得抛出。
/// @param code 原错误码；@param message 固定 ASCII 消息；@param output 空的输出。
/// @return 原错误码；内存耗尽时允许 output 仍为空。
pbi_status_v1 WriteError(pbi_status_v1 code, const char* message, pbi_buffer_v1* output) noexcept {
  try {
    auto error = Envelope();
    error["error"] = {{"code", StatusName(code)}, {"message", message}};
    WriteBuffer(error.dump(), output);
  } catch (...) {
    // 无法分配错误正文时，状态码仍足以让调用者区分失败。
  }
  return code;
}
} // namespace

std::uint32_t pbi_v1_abi_version() noexcept { return 1; }
const char* pbi_v1_engine_version() noexcept { return PBI_ENGINE_VERSION; }
/// @return 拥有的未取消令牌；对象或 stop_state 分配失败均返回 nullptr，不越过 C 边界抛异常。
pbi_cancel_token_v1* pbi_v1_cancel_token_create() noexcept {
  // stop_source 的内部状态分配也可能失败；nothrow new 不会捕获构造函数异常。
  try { return new pbi_cancel_token_v1; } catch (...) { return nullptr; }
}
void pbi_v1_cancel_request(pbi_cancel_token_v1* token) noexcept {
  if (token) token->source.request_stop();
}
void pbi_v1_cancel_token_destroy(pbi_cancel_token_v1* token) noexcept { delete token; }
void pbi_v1_buffer_release(pbi_buffer_v1* buffer) noexcept {
  if (buffer) {
    std::free(buffer->data);
    *buffer = {nullptr, 0};
  }
}

pbi_status_v1 pbi_v1_compute(const std::uint8_t* request, std::size_t request_size,
                            const pbi_cancel_token_v1* cancellation,
                            pbi_buffer_v1* output) noexcept {
  // 不覆盖未释放结果；调用者始终保持原 buffer 的所有权。
  if (!output || output->data || output->size) return PBI_INVALID_INPUT_V1;
  try {
    CheckCancelled(cancellation);
    if (!request || !request_size) throw RequestError(PBI_INVALID_INPUT_V1, "request must not be empty");
    if (request_size > kMaxBytes) throw RequestError(PBI_RESOURCE_LIMIT_V1, "request byte budget exceeded");
    // 在解析阶段限制深度，拒绝与固定 schema 无关的极深嵌套。
    const auto limit_depth = [](int depth, Json::parse_event_t, Json&) {
      if (depth > 16) throw RequestError(PBI_RESOURCE_LIMIT_V1, "JSON nesting budget exceeded");
      return true;
    };
    const auto decoded = Json::parse(request, request + request_size, limit_depth);
    RequireFields(decoded, {"schema_version", "operations"});
    if (ReadInteger(decoded.at("schema_version")) != 1) {
      throw RequestError(PBI_UNSUPPORTED_V1, "unsupported schema version");
    }
    const auto& operations = decoded.at("operations");
    if (!operations.is_array() || operations.empty()) throw RequestError(PBI_INVALID_INPUT_V1, "operations must be a nonempty array");
    if (operations.size() > kMaxOperations) throw RequestError(PBI_RESOURCE_LIMIT_V1, "operation budget exceeded");
    std::vector<Operation> typed;
    typed.reserve(operations.size());
    std::size_t remaining_rolls = kMaxTotalRolls;
    std::size_t remaining_nodes = PBI_V1_MAX_GRAPH_NODES;
    std::size_t remaining_edges = PBI_V1_MAX_GRAPH_EDGES;
    const auto stop = cancellation ? cancellation->source.get_token() : std::stop_token{};
    for (const auto& operation : operations) {
      CheckCancelled(cancellation);
      auto [value, consumed] = ReadOperation(operation, remaining_rolls, remaining_nodes, remaining_edges, stop);
      remaining_rolls -= consumed;
      if (const auto* graph = std::get_if<GraphRequest>(&value)) {
        remaining_nodes -= graph->graph.Nodes().size();
        remaining_edges -= graph->graph.Edges().size();
      }
      typed.push_back(std::move(value));
    }
    auto results = Json::array();
    for (const auto& operation : typed) {
      CheckCancelled(cancellation);
      // 图遍历/消元借用原 C 令牌的 stop_token，不创建轮询线程，也不在长图操作中忽略取消。
      results.push_back(std::visit([stop](const auto& value) {
        if constexpr (std::is_same_v<std::decay_t<decltype(value)>, GraphRequest>) return EvaluateGraph(value, stop);
        else return Evaluate(value);
      }, operation));
    }
    auto response = Envelope();
    response["results"] = std::move(results);
    const auto encoded = response.dump();
    // 最后一次检查是批次提交点；取消不向调用方交付部分 results。
    CheckCancelled(cancellation);
    WriteBuffer(encoded, output);
    return PBI_OK_V1;
  } catch (const RequestError& error) {
    return WriteError(error.code, error.what(), output);
  } catch (const nlohmann::json::exception&) {
    return WriteError(PBI_INVALID_INPUT_V1, "invalid JSON request", output);
  } catch (const pbi::UnsupportedRule& error) {
    return WriteError(PBI_UNSUPPORTED_V1, error.what(), output);
  } catch (const std::invalid_argument& error) {
    return WriteError(PBI_INVALID_INPUT_V1, error.what(), output);
  } catch (const std::overflow_error&) {
    return WriteError(PBI_RESOURCE_LIMIT_V1, "integer result exceeds output range", output);
  } catch (const std::bad_alloc&) {
    return WriteError(PBI_RESOURCE_LIMIT_V1, "allocation failed", output);
  } catch (...) {
    return WriteError(PBI_INTERNAL_ERROR_V1, "native calculation failed", output);
  }
}
