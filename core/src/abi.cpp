// C ABI 只负责协议、所有权与错误隔离，计算规则由 calculations.cpp 唯一实现。
#include "pbi_core.h"
#include "pbi/calculations.hpp"

#include <nlohmann/json.hpp>
#include <atomic>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <new>
#include <stdexcept>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

/// 原子取消标记，无共享计算状态；生命周期由 C ABI 调用者管理。
struct pbi_cancel_token_v1 {
  std::atomic_bool cancelled{false};
};

namespace {
using Json = nlohmann::json;
constexpr std::size_t kMaxBytes = PBI_V1_MAX_REQUEST_BYTES;
constexpr std::size_t kMaxOperations = PBI_V1_MAX_OPERATIONS;
constexpr std::size_t kMaxRolls = PBI_V1_MAX_ROLLS;
constexpr std::size_t kMaxTotalRolls = PBI_V1_MAX_TOTAL_ROLLS;

/// 协议失败携带稳定错误码，所有文本固定为 ASCII，不回显用户输入。
class RequestError final : public std::runtime_error {
public:
  /// @param code 稳定错误码；@param message 固定错误说明，复制后由异常拥有。
  RequestError(pbi_status_v1 code, const char* message) : std::runtime_error(message), code(code) {}
  pbi_status_v1 code;
};

/// 固定协议在边界转换为四种静态计算输入，不把 JSON 传进领域层。
struct HpRequest { pbi::StatInput input; };
/// 非 HP 输入保存显式性格枚举，不使用浮点倍率。
struct StatRequest { pbi::StatInput input; pbi::NatureEffect nature; };
/// 能力等级输入独立于能力配置，允许完整 int64 能力值。
struct StageRequest { std::int64_t value; std::int32_t stage; };
/// KO 请求拥有伤害档位副本，不借用解析器内部节点。
struct KoRequest { std::vector<std::int32_t> rolls; std::int32_t hp; };
using Operation = std::variant<HpRequest, StatRequest, StageRequest, KoRequest>;

/// @param token 只读借用的可空令牌；已取消时抛出 RequestError，无副作用。
void CheckCancelled(const pbi_cancel_token_v1* token) {
  if (token && token->cancelled.load(std::memory_order_relaxed)) {
    throw RequestError(PBI_CANCELLED_V1, "calculation cancelled");
  }
}

/// 检查固定对象字段，拒绝遗漏与静默忽略未知参数。
/// @param value 只读 JSON 对象；@param fields 该对象的完整字段集合。
void RequireFields(const Json& value, std::initializer_list<std::string_view> fields) {
  if (!value.is_object() || value.size() != fields.size()) {
    throw RequestError(PBI_INVALID_INPUT_V1, "invalid object fields");
  }
  for (const auto field : fields) {
    if (!value.contains(field)) {
      throw RequestError(PBI_INVALID_INPUT_V1, "missing required field");
    }
  }
}

/// @param value 必须为 JSON 整数，不能是 bool/float 或越界 unsigned；@return 精确 int64。
std::int64_t ReadInteger(const Json& value) {
  if (!value.is_number_integer() ||
      (value.is_number_unsigned() && value.get<std::uint64_t>() >
                                        static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))) {
    throw RequestError(PBI_INVALID_INPUT_V1, "integer field out of range");
  }
  return value.get<std::int64_t>();
}

/// @param value 只读 JSON 整数；@return 已检查范围的 int32，否则显式失败。
std::int32_t ReadInt32(const Json& value) {
  const auto integer = ReadInteger(value);
  if (integer < std::numeric_limits<std::int32_t>::min() || integer > std::numeric_limits<std::int32_t>::max()) {
    throw RequestError(PBI_INVALID_INPUT_V1, "integer field exceeds int32 range");
  }
  return static_cast<std::int32_t>(integer);
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

/// 解码单条计算，并限制实际批次伤害槽位总量。
/// @param object 只读 JSON 操作；@param remaining_rolls 尚可拥有的槽位预算。
/// @return 类型化操作和消耗的槽位数；不修改调用方预算。
std::pair<Operation, std::size_t> ReadOperation(const Json& object, std::size_t remaining_rolls) {
  if (!object.is_object() || !object.contains("kind") || !object.at("kind").is_string()) {
    throw RequestError(PBI_INVALID_INPUT_V1, "operation kind must be a string");
  }
  const auto kind = object.at("kind").get<std::string>();
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
    std::vector<std::int32_t> values;
    values.reserve(rolls.size());
    for (const auto& value : rolls) values.push_back(ReadInt32(value));
    const auto count = values.size();
    return {KoRequest{std::move(values), ReadInt32(object.at("defender_hp"))}, count};
  }
  throw RequestError(PBI_UNSUPPORTED_V1, "unsupported operation kind");
}

/// @param value 已约分领域概率，只读；@return 分子分母十进制字符串，绝不经 double。
Json FractionJson(const pbi::Rational& value) {
  return {{"numerator", value.numerator().str()}, {"denominator", value.denominator().str()}};
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

/// @return 所有成功/失败响应共有的版本信息，新对象无共享状态。
Json Envelope() {
  return {{"schema_version", 1}, {"engine_version", PBI_ENGINE_VERSION}, {"rules_version", "modern-calculations.v1"}};
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
pbi_cancel_token_v1* pbi_v1_cancel_token_create() noexcept { return new (std::nothrow) pbi_cancel_token_v1; }
void pbi_v1_cancel_request(pbi_cancel_token_v1* token) noexcept {
  if (token) token->cancelled.store(true, std::memory_order_relaxed);
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
    for (const auto& operation : operations) {
      CheckCancelled(cancellation);
      auto [value, consumed] = ReadOperation(operation, remaining_rolls);
      remaining_rolls -= consumed;
      typed.push_back(std::move(value));
    }
    auto results = Json::array();
    for (const auto& operation : typed) {
      CheckCancelled(cancellation);
      results.push_back(std::visit([](const auto& value) { return Evaluate(value); }, operation));
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
