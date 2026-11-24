// C ABI 只负责协议、所有权与错误隔离，计算规则由 typed Core 唯一实现。
#include "pbi_core.h"
#include "pbi/calculations.hpp"
#include "pbi/damage.hpp"

#include <nlohmann/json.hpp>
#include <atomic>
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
using Operation = std::variant<HpRequest, StatRequest, StageRequest, KoRequest, DamageRequest>;

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

/// 检查带可选字段的固定 schema；未知参数不能静默丢失。
/// @param value 只读对象；@param required 必填字段；@param optional 可选字段。
void RequireSchema(const Json& value, std::initializer_list<std::string_view> required,
                   std::initializer_list<std::string_view> optional = {}) {
  if (!value.is_object()) throw RequestError(PBI_INVALID_INPUT_V1, "expected an object");
  for (const auto field : required) {
    if (!value.contains(field)) throw RequestError(PBI_INVALID_INPUT_V1, "missing required field");
  }
  for (const auto& field : value.items()) {
    if (std::find(required.begin(), required.end(), field.key()) == required.end() &&
        std::find(optional.begin(), optional.end(), field.key()) == optional.end()) {
      throw RequestError(PBI_INVALID_INPUT_V1, "unknown object field");
    }
  }
}

/// @param value JSON 布尔值；@return 原值，数字/字符串不进行隐式转换。
bool ReadBool(const Json& value) {
  if (!value.is_boolean()) throw RequestError(PBI_INVALID_INPUT_V1, "expected a boolean");
  return value.get<bool>();
}

/// @param value JSON 数值；@return 有限非负 binary64，拒绝 bool/null 和非有限数。
double ReadMultiplier(const Json& value) {
  if (!value.is_number()) throw RequestError(PBI_INVALID_INPUT_V1, "expected a numeric multiplier");
  const double number = value.get<double>();
  if (!std::isfinite(number) || number < 0) throw RequestError(PBI_INVALID_INPUT_V1, "invalid damage multiplier");
  return number;
}

/// 把协议有限标识转换成按声明顺序排列的领域枚举，不提供 UNKNOWN 回退。
/// @tparam Enum 领域枚举；@tparam Size 合同中枚举项数；@param value 字符串值；@param names 固定名称。
/// @return 对应枚举；未知名称为 UNSUPPORTED，错误 JSON 类型为 INVALID_INPUT。
template <class Enum, std::size_t Size>
Enum ReadEnum(const Json& value, const std::array<std::string_view, Size>& names) {
  if (!value.is_string()) throw RequestError(PBI_INVALID_INPUT_V1, "expected an enum string");
  const auto name = value.get<std::string>();
  const auto found = std::find(names.begin(), names.end(), name);
  if (found == names.end()) throw RequestError(PBI_UNSUPPORTED_V1, "unsupported damage rule identifier");
  return static_cast<Enum>(found - names.begin());
}

/// @param value 一侧只读 JSON 快照；@return 完整能力、属性和静态效果领域输入。
pbi::DamagePokemon ReadPokemon(const Json& value) {
  RequireSchema(value, {"level", "types", "stats"}, {"ability", "item", "can_evolve", "grounding"});
  const auto& stats = value.at("stats");
  RequireFields(stats, {"hp", "attack", "defense", "special_attack", "special_defense", "speed"});
  pbi::DamagePokemon result{ReadInt32(value.at("level")), {},
      {ReadInt32(stats.at("hp")), ReadInt32(stats.at("attack")), ReadInt32(stats.at("defense")),
       ReadInt32(stats.at("special_attack")), ReadInt32(stats.at("special_defense")), ReadInt32(stats.at("speed"))},
      pbi::DamageAbility::none, pbi::DamageItem::none, false, std::nullopt};
  if (!value.at("types").is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "types must be an array");
  for (const auto& type : value.at("types")) result.types.push_back(static_cast<pbi::PokemonType>(ReadInt32(type)));
  if (value.contains("ability")) result.ability = ReadEnum<pbi::DamageAbility>(value.at("ability"),
      std::array<std::string_view, 7>{"none", "technician", "adaptability", "thick_fat", "filter", "solid_rock", "sniper"});
  if (value.contains("item")) result.item = ReadEnum<pbi::DamageItem>(value.at("item"),
      std::array<std::string_view, 6>{"none", "life_orb", "choice_band", "choice_specs", "expert_belt", "eviolite"});
  if (value.contains("can_evolve")) result.can_evolve = ReadBool(value.at("can_evolve"));
  if (value.contains("grounding") && !value.at("grounding").is_null()) result.grounding = ReadEnum<pbi::Grounding>(value.at("grounding"),
      std::array<std::string_view, 2>{"grounded", "airborne"});
  return result;
}

/// 按显式字段更新策略的新副本；字段映射仅在序列化边界，不充当运行时规则注册表。
/// @param value 只读策略覆盖对象；@param baseline 由代际解析的默认策略副本。
/// @return 新策略；未知字段或非法倍率明确失败。
pbi::DamagePolicy ReadPolicy(const Json& value, pbi::DamagePolicy baseline) {
  using Policy = pbi::DamagePolicy;
  static constexpr std::array<std::pair<std::string_view, double Policy::*>, 23> multipliers{{
      {"terrain_boost_multiplier", &Policy::terrain_boost_multiplier},
      {"misty_terrain_dragon_multiplier", &Policy::misty_terrain_dragon_multiplier},
      {"weather_boost_multiplier", &Policy::weather_boost_multiplier}, {"weather_weaken_multiplier", &Policy::weather_weaken_multiplier},
      {"screen_single_target_multiplier", &Policy::screen_single_target_multiplier}, {"screen_multi_target_multiplier", &Policy::screen_multi_target_multiplier},
      {"aurora_veil_single_target_multiplier", &Policy::aurora_veil_single_target_multiplier}, {"aurora_veil_multi_target_multiplier", &Policy::aurora_veil_multi_target_multiplier},
      {"critical_hit_multiplier", &Policy::critical_hit_multiplier}, {"spread_move_multiplier", &Policy::spread_move_multiplier},
      {"protect_damage_multiplier", &Policy::protect_damage_multiplier}, {"same_type_attack_bonus_multiplier", &Policy::same_type_attack_bonus_multiplier},
      {"technician_base_power_multiplier", &Policy::technician_base_power_multiplier}, {"adaptability_stab_multiplier", &Policy::adaptability_stab_multiplier},
      {"thick_fat_damage_multiplier", &Policy::thick_fat_damage_multiplier}, {"filter_damage_multiplier", &Policy::filter_damage_multiplier},
      {"sniper_critical_multiplier", &Policy::sniper_critical_multiplier}, {"multiscale_damage_multiplier", &Policy::multiscale_damage_multiplier},
      {"life_orb_damage_multiplier", &Policy::life_orb_damage_multiplier}, {"choice_item_attack_multiplier", &Policy::choice_item_attack_multiplier},
      {"expert_belt_damage_multiplier", &Policy::expert_belt_damage_multiplier}, {"eviolite_defense_multiplier", &Policy::eviolite_defense_multiplier},
      {"burn_physical_attack_multiplier", &Policy::burn_physical_attack_multiplier}}};
  static constexpr std::array<std::pair<std::string_view, std::optional<double> Policy::*>, 3> optionals{{
      {"sandstorm_rock_spdef_multiplier", &Policy::sandstorm_rock_spdef_multiplier},
      {"snow_ice_defense_multiplier", &Policy::snow_ice_defense_multiplier}, {"hail_ice_defense_multiplier", &Policy::hail_ice_defense_multiplier}}};
  if (!value.is_object()) throw RequestError(PBI_INVALID_INPUT_V1, "policy must be an object");
  for (const auto& field : value.items()) {
    const auto multiplier = std::find_if(multipliers.begin(), multipliers.end(), [&](const auto& entry) { return entry.first == field.key(); });
    const auto optional = std::find_if(optionals.begin(), optionals.end(), [&](const auto& entry) { return entry.first == field.key(); });
    if (multiplier != multipliers.end()) baseline.*(multiplier->second) = ReadMultiplier(field.value());
    else if (optional != optionals.end()) baseline.*(optional->second) = field.value().is_null() ? std::nullopt : std::optional{ReadMultiplier(field.value())};
    else if (field.key() == "technician_base_power_threshold") baseline.technician_base_power_threshold = ReadInt32(field.value());
    else if (field.key() == "random_damage_multipliers") {
      if (!field.value().is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "random multipliers must be an array");
      if (field.value().size() > kMaxRolls) throw RequestError(PBI_RESOURCE_LIMIT_V1, "damage roll budget exceeded");
      baseline.random_damage_multipliers.clear();
      for (const auto& number : field.value()) baseline.random_damage_multipliers.push_back(ReadMultiplier(number));
    } else throw RequestError(PBI_INVALID_INPUT_V1, "unknown damage policy field");
  }
  return baseline;
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
  const auto& chart = value.at("type_chart");
  if (!chart.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "type chart must be an array");
  if (chart.size() > 324) throw RequestError(PBI_RESOURCE_LIMIT_V1, "type chart budget exceeded");
  std::vector<pbi::TypeEfficacy> entries;
  for (const auto& entry : chart) {
    RequireFields(entry, {"attacking", "defending", "percent"});
    entries.push_back({static_cast<pbi::PokemonType>(ReadInt32(entry.at("attacking"))),
                      static_cast<pbi::PokemonType>(ReadInt32(entry.at("defending"))), ReadInt32(entry.at("percent"))});
  }
  return {std::move(input), pbi::TypeChartSnapshot{std::move(entries)}, generation};
}

/// 解码单条计算，并限制实际批次伤害槽位总量。
/// @param object 只读 JSON 操作；@param remaining_rolls 尚可拥有的槽位预算。
/// @return 类型化操作和消耗的槽位数；不修改调用方预算。
std::pair<Operation, std::size_t> ReadOperation(const Json& object, std::size_t remaining_rolls) {
  if (!object.is_object() || !object.contains("kind") || !object.at("kind").is_string()) {
    throw RequestError(PBI_INVALID_INPUT_V1, "operation kind must be a string");
  }
  const auto kind = object.at("kind").get<std::string>();
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

/// @param request 只读完整伤害请求；@return 档位、完整 trace 及规范 Core 的精确 KO 结果。
Json Evaluate(const DamageRequest& request) {
  const auto result = pbi::CalculateDamage(request.input, request.knowledge);
  const auto ko = pbi::EstimateKoChance(result.rolls, result.defender_hp);
  auto trace = Json::array();
  for (const auto& entry : result.trace) {
    trace.push_back({{"key", pbi::DamageSourceName(entry.key)}, {"stage", pbi::DamageStageName(entry.stage)},
        {"source", pbi::DamageSourceName(entry.source)}, {"reason", entry.reason},
        {"multiplier", entry.multiplier ? Json(*entry.multiplier) : Json(nullptr)},
        {"min_multiplier", entry.min_multiplier ? Json(*entry.min_multiplier) : Json(nullptr)},
        {"max_multiplier", entry.max_multiplier ? Json(*entry.max_multiplier) : Json(nullptr)}});
  }
  return {{"kind", "damage"}, {"damage_ruleset_id", "python-compatible.gen" + std::to_string(request.generation) + ".v1"},
      {"rolls", result.rolls}, {"defender_hp", result.defender_hp}, {"base_damage", result.base_damage}, {"trace", std::move(trace)},
      {"ohko", FractionJson(ko.ohko)}, {"two_hit", FractionJson(ko.two_hit)},
      {"guaranteed_ohko", ko.guaranteed_ohko}, {"guaranteed_two_hit", ko.guaranteed_two_hit}};
}

/// @return 所有成功/失败响应共有的版本信息，新对象无共享状态。
Json Envelope() {
  return {{"schema_version", 1}, {"engine_version", PBI_ENGINE_VERSION}, {"rules_version", "calculation-rules.v2"}};
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
  } catch (const pbi::UnsupportedDamageRule& error) {
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
