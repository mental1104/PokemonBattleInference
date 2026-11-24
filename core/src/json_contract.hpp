#pragma once
// 仅供 ABI 实现共享的固定 JSON 边界；纯 Core 不包含这个私有头。
#include "pbi_core.h"
#include "pbi/damage.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace pbi::contract {
using Json = nlohmann::json;
/// 协议失败携带稳定错误码，所有文本固定为 ASCII，不回显用户输入。
class RequestError final : public std::runtime_error {
public:
  /// @param code 稳定错误码；@param message 固定错误说明，复制后由异常拥有。
  RequestError(pbi_status_v1 code, const char* message) : std::runtime_error(message), code(code) {}
  pbi_status_v1 code;
};


/// 检查固定对象字段，拒绝遗漏与静默忽略未知参数。
/// @param value 只读 JSON 对象；@param fields 该对象的完整字段集合。
inline void RequireFields(const Json& value, std::initializer_list<std::string_view> fields) {
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
inline std::int64_t ReadInteger(const Json& value) {
  if (!value.is_number_integer() ||
      (value.is_number_unsigned() && value.get<std::uint64_t>() >
                                        static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))) {
    throw RequestError(PBI_INVALID_INPUT_V1, "integer field out of range");
  }
  return value.get<std::int64_t>();
}

/// @param value 只读 JSON 整数；@return 已检查范围的 int32，否则显式失败。
inline std::int32_t ReadInt32(const Json& value) {
  const auto integer = ReadInteger(value);
  if (integer < std::numeric_limits<std::int32_t>::min() || integer > std::numeric_limits<std::int32_t>::max()) {
    throw RequestError(PBI_INVALID_INPUT_V1, "integer field exceeds int32 range");
  }
  return static_cast<std::int32_t>(integer);
}

/// @param value 只读六项整数对象；@return 完整能力数据，禁止缺失或未知字段。
inline BattleStats ReadBattleStats(const Json& value) {
  RequireFields(value, {"hp", "attack", "defense", "special_attack", "special_defense", "speed"});
  return {ReadInt32(value.at("hp")), ReadInt32(value.at("attack")), ReadInt32(value.at("defense")),
          ReadInt32(value.at("special_attack")), ReadInt32(value.at("special_defense")), ReadInt32(value.at("speed"))};
}
/// @param value 只读六项能力；@return 完整协议对象，不执行数值计算。
inline Json BattleStatsJson(const BattleStats& value) {
  return {{"hp", value.hp}, {"attack", value.attack}, {"defense", value.defense},
          {"special_attack", value.special_attack}, {"special_defense", value.special_defense}, {"speed", value.speed}};
}


/// 检查带可选字段的固定 schema；未知参数不能静默丢失。
/// @param value 只读对象；@param required 必填字段；@param optional 可选字段。
inline void RequireSchema(const Json& value, std::initializer_list<std::string_view> required,
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
inline bool ReadBool(const Json& value) {
  if (!value.is_boolean()) throw RequestError(PBI_INVALID_INPUT_V1, "expected a boolean");
  return value.get<bool>();
}

/// @param value JSON 数值；@return 有限非负 binary64，拒绝 bool/null 和非有限数。
inline double ReadMultiplier(const Json& value) {
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
inline pbi::DamagePokemon ReadPokemon(const Json& value) {
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
      std::array<std::string_view, 9>{"none", "technician", "adaptability", "thick_fat", "filter", "solid_rock", "sniper", "multiscale", "inner_focus"});
  if (value.contains("item")) result.item = ReadEnum<pbi::DamageItem>(value.at("item"),
      std::array<std::string_view, 6>{"none", "life_orb", "choice_band", "choice_specs", "expert_belt", "eviolite"});
  if (value.contains("can_evolve")) result.can_evolve = ReadBool(value.at("can_evolve"));
  if (value.contains("grounding") && !value.at("grounding").is_null()) result.grounding = ReadEnum<pbi::Grounding>(value.at("grounding"),
      std::array<std::string_view, 2>{"grounded", "airborne"});
  return result;
}

/// 固定策略字段的输入/输出映射，仅用于 JSON 适配，不注册任何运行时规则。
using Policy = pbi::DamagePolicy;
inline constexpr std::array<std::pair<std::string_view, double Policy::*>, 23> multipliers{{
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
inline constexpr std::array<std::pair<std::string_view, std::optional<double> Policy::*>, 3> optionals{{
      {"sandstorm_rock_spdef_multiplier", &Policy::sandstorm_rock_spdef_multiplier},
      {"snow_ice_defense_multiplier", &Policy::snow_ice_defense_multiplier}, {"hail_ice_defense_multiplier", &Policy::hail_ice_defense_multiplier}}};

/// 按显式字段更新策略的新副本；字段映射仅在序列化边界，不充当运行时规则注册表。
/// @param value 只读策略覆盖对象；@param baseline 由代际解析的默认策略副本。
/// @return 新策略；未知字段或非法倍率明确失败。
inline pbi::DamagePolicy ReadPolicy(const Json& value, pbi::DamagePolicy baseline) {
  if (!value.is_object()) throw RequestError(PBI_INVALID_INPUT_V1, "policy must be an object");
  for (const auto& field : value.items()) {
    const auto multiplier = std::find_if(multipliers.begin(), multipliers.end(), [&](const auto& entry) { return entry.first == field.key(); });
    const auto optional = std::find_if(optionals.begin(), optionals.end(), [&](const auto& entry) { return entry.first == field.key(); });
    if (multiplier != multipliers.end()) baseline.*(multiplier->second) = ReadMultiplier(field.value());
    else if (optional != optionals.end()) baseline.*(optional->second) = field.value().is_null() ? std::nullopt : std::optional{ReadMultiplier(field.value())};
    else if (field.key() == "technician_base_power_threshold") baseline.technician_base_power_threshold = ReadInt32(field.value());
    else if (field.key() == "random_damage_multipliers") {
      if (!field.value().is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "random multipliers must be an array");
      if (field.value().size() > PBI_V1_MAX_ROLLS) throw RequestError(PBI_RESOURCE_LIMIT_V1, "damage roll budget exceeded");
      baseline.random_damage_multipliers.clear();
      for (const auto& number : field.value()) baseline.random_damage_multipliers.push_back(ReadMultiplier(number));
    } else throw RequestError(PBI_INVALID_INPUT_V1, "unknown damage policy field");
  }
  return baseline;
}


/// @param value 已约分领域概率，只读；@return 分子分母十进制字符串，绝不经 double。
inline Json FractionJson(const pbi::Rational& value) {
  return {{"numerator", value.numerator().str()}, {"denominator", value.denominator().str()}};
}

/// @param value 十进制整数文本；@return 精确任意精度整数，最多 1024 位，拒绝隐式八进制。
inline Integer ReadDecimalInteger(const Json& value) {
  if (!value.is_string()) throw RequestError(PBI_INVALID_INPUT_V1, "fraction components must be decimal strings");
  const auto text = value.get<std::string>();
  const std::size_t first = !text.empty() && text.front() == '-' ? 1 : 0;
  if (text.size() - first > 1024) throw RequestError(PBI_RESOURCE_LIMIT_V1, "fraction digit budget exceeded");
  if (first == text.size()) throw RequestError(PBI_INVALID_INPUT_V1, "invalid decimal integer");
  Integer result = 0;
  for (std::size_t index = first; index < text.size(); ++index) {
    if (text[index] < '0' || text[index] > '9') throw RequestError(PBI_INVALID_INPUT_V1, "invalid decimal integer");
    result = result * 10 + (text[index] - '0');
  }
  return first ? Integer{-result} : result;
}
/// @param value 精确分数字符串对象；@return 规范分数，零分母明确失败，不经 float。
inline Rational ReadFraction(const Json& value) {
  RequireFields(value, {"numerator", "denominator"});
  const auto numerator = ReadDecimalInteger(value.at("numerator"));
  const auto denominator = ReadDecimalInteger(value.at("denominator"));
  if (denominator == 0) throw RequestError(PBI_INVALID_INPUT_V1, "fraction denominator must not be zero");
  // 先统一分母符号，避免底层有理数构造对负分母的限制泄漏成 INTERNAL_ERROR。
  if (denominator < 0) return Rational{Integer{-numerator}, Integer{-denominator}};
  return Rational{numerator, denominator};
}
/// @param value 只读策略；@return 按同一字段映射编码的完整策略，不漏掉默认字段。
inline Json PolicyJson(const DamagePolicy& value) {
  auto result = Json::object();
  for (const auto& [name, member] : multipliers) result[name] = value.*member;
  for (const auto& [name, member] : optionals) result[name] = value.*member ? Json(*(value.*member)) : Json(nullptr);
  result["technician_base_power_threshold"] = value.technician_base_power_threshold;
  result["random_damage_multipliers"] = value.random_damage_multipliers;
  return result;
}
/// @param value 只读宝可梦快照；@return 全部输入字段，动态状态仍由状态合同独立保存。
inline Json PokemonJson(const DamagePokemon& value) {
  const auto& stats = value.stats;
  constexpr std::array<std::string_view, 9> abilities{"none", "technician", "adaptability", "thick_fat", "filter", "solid_rock", "sniper", "multiscale", "inner_focus"};
  constexpr std::array<std::string_view, 6> items{"none", "life_orb", "choice_band", "choice_specs", "expert_belt", "eviolite"};
  auto types = Json::array(); for (const auto type : value.types) types.push_back(static_cast<int>(type));
  return {{"level", value.level}, {"types", types},
      {"stats", {{"hp", stats.hp}, {"attack", stats.attack}, {"defense", stats.defense}, {"special_attack", stats.special_attack}, {"special_defense", stats.special_defense}, {"speed", stats.speed}}},
      {"ability", abilities.at(static_cast<std::size_t>(value.ability))}, {"item", items.at(static_cast<std::size_t>(value.item))},
      {"can_evolve", value.can_evolve}, {"grounding", value.grounding ? Json(*value.grounding == Grounding::grounded ? "grounded" : "airborne") : Json(nullptr)}};
}
/// @param value 属性相克数组；@return 拥有条目的知识快照，最多 18*18 项，重复由 Core 拒绝。
inline TypeChartSnapshot ReadTypeChart(const Json& value) {
  if (!value.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "type chart must be an array");
  if (value.size() > 324) throw RequestError(PBI_RESOURCE_LIMIT_V1, "type chart budget exceeded");
  std::vector<TypeEfficacy> entries;
  for (const auto& entry : value) {
    RequireFields(entry, {"attacking", "defending", "percent"});
    entries.push_back({static_cast<PokemonType>(ReadInt32(entry.at("attacking"))), static_cast<PokemonType>(ReadInt32(entry.at("defending"))), ReadInt32(entry.at("percent"))});
  }
  return TypeChartSnapshot{std::move(entries)};
}

/// @param result 只读完整伤害结果；@param generation 原兼容代际；@return trace 和精确 KO 的协议对象。
inline Json DamageJson(const pbi::DamageResult& result, std::int32_t generation) {
  const auto ko = pbi::EstimateKoChance(result.rolls, result.defender_hp);
  auto trace = Json::array();
  for (const auto& entry : result.trace) {
    trace.push_back({{"key", pbi::DamageSourceName(entry.key)}, {"stage", pbi::DamageStageName(entry.stage)},
        {"source", pbi::DamageSourceName(entry.source)}, {"reason", entry.reason},
        {"multiplier", entry.multiplier ? Json(*entry.multiplier) : Json(nullptr)},
        {"min_multiplier", entry.min_multiplier ? Json(*entry.min_multiplier) : Json(nullptr)},
        {"max_multiplier", entry.max_multiplier ? Json(*entry.max_multiplier) : Json(nullptr)}});
  }
  return {{"kind", "damage"}, {"damage_ruleset_id", "python-compatible.gen" + std::to_string(generation) + ".v1"},
      {"rolls", result.rolls}, {"defender_hp", result.defender_hp}, {"base_damage", result.base_damage}, {"trace", std::move(trace)},
      {"ohko", FractionJson(ko.ohko)}, {"two_hit", FractionJson(ko.two_hit)},
      {"guaranteed_ohko", ko.guaranteed_ohko}, {"guaranteed_two_hit", ko.guaranteed_two_hit}};
}

} // namespace pbi::contract
