#include "pbi/configuration_stats.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <locale>
#include <map>
#include <set>
#include <sstream>

namespace pbi {
namespace {
/// @param stats 只读六项值；@return 适合比较/归并的固定顺序数组。
std::array<std::int32_t, 6> Values(const BattleStats& stats) {
  return {stats.hp, stats.attack, stats.defense, stats.special_attack, stats.special_defense, stats.speed};
}
/// @param values 只读六项数组；@return 拥有值，不借用数组。
BattleStats Stats(const std::array<std::int32_t, 6>& values) {
  return {values[0], values[1], values[2], values[3], values[4], values[5]};
}
/// @param value 已计算的能力；@return int32值，越界明确失败。
std::int32_t Narrow(double value) {
  if (!std::isfinite(value) || value < std::numeric_limits<std::int32_t>::min() ||
      value > std::numeric_limits<std::int32_t>::max()) {
    throw std::overflow_error("configuration stat exceeds int32 range");
  }
  return static_cast<std::int32_t>(value);
}
/// @param field 有限EV轴；@return 固定数组下标，未知枚举拒绝。
std::size_t FieldIndex(ConfigurationStatField field) {
  const auto index = static_cast<int>(field);
  if (index < 0 || index > 5) throw std::invalid_argument("unknown configuration stat field");
  return static_cast<std::size_t>(index);
}
/// @param token 可共享空/有效令牌；取消时终止整次枚举。
void CheckCancellation(const CancellationToken& token) {
  if (token.Requested()) throw std::runtime_error("configuration stat enumeration cancelled");
}
/// @param nature 只读五轴倍率；不把非有限值送入 floor 或行为键。
void ValidateNature(const ConfigurationNature& nature) {
  if (std::ranges::any_of(nature.multipliers, [](double value) { return !std::isfinite(value); })) {
    throw std::invalid_argument("nature multipliers must be finite");
  }
}
/// @param value 有限性格倍率；@return Python repr 相同的最短有效数字和指数切换标签。
std::string NatureLabel(double value) {
  std::string scientific;
  // 浮点to_chars要求macOS13.3/iOS16.3；最低部署13/16改用经典locale流，
  // 逐增有效位找到首个精确roundtrip文本，不改全局locale或数值计算。
  for (int precision = 0; precision < std::numeric_limits<double>::max_digits10; ++precision) {
    std::ostringstream output;
    output.imbue(std::locale::classic());
    output.precision(precision);
    output << std::scientific << value;
    auto candidate = output.str();
    std::istringstream input{candidate};
    input.imbue(std::locale::classic());
    double parsed = std::numeric_limits<double>::quiet_NaN();
    input >> parsed;
    // 次正规数解析可能设置failbit但仍得到正确值，故直接比较其完整double结果。
    if (parsed == value && (value != 0.0 || std::signbit(parsed) == std::signbit(value))) {
      scientific = std::move(candidate);
      break;
    }
  }
  if (scientific.empty()) throw std::runtime_error("cannot format nature multiplier");
  const auto separator = scientific.find('e');
  const auto exponent = std::stoi(scientific.substr(separator + 1));
  if (exponent < -4 || exponent >= 16) return scientific;
  const bool negative = scientific.front() == '-';
  auto digits = scientific.substr(negative ? 1 : 0, separator - (negative ? 1 : 0));
  std::erase(digits, '.');
  const auto point = exponent + 1;
  std::string output = negative ? "-" : "";
  if (point <= 0) return output + "0." + std::string(static_cast<std::size_t>(-point), '0') + digits;
  if (static_cast<std::size_t>(point) >= digits.size()) {
    return output + digits + std::string(static_cast<std::size_t>(point) - digits.size(), '0') + ".0";
  }
  digits.insert(static_cast<std::size_t>(point), ".");
  return output + digits;
}
/// @param evs 投入数组；@param nature 性格；@param fields 命令轴顺序；@return 非行为标签。
std::string ControlledLabel(const std::array<std::int32_t, 6>& evs,
                            const ConfigurationNature& nature,
                            const std::vector<ConfigurationStatField>& fields) {
  static constexpr std::array<const char*, 6> names{
      "hp", "attack", "defense", "special_attack", "special_defense", "speed"};
  static constexpr std::array<const char*, 5> short_names{"atk", "def", "spa", "spd", "spe"};
  std::string label = "ev:";
  for (std::size_t index = 0; index < fields.size(); ++index) {
    if (index != 0) label += ',';
    const auto field = FieldIndex(fields[index]);
    label += std::string{names[field]} + '=' + std::to_string(evs[field]);
  }
  label += ";nature:";
  for (std::size_t index = 0; index < nature.multipliers.size(); ++index) {
    if (index != 0) label += ',';
    label += std::string{short_names[index]} + '=' + NatureLabel(nature.multipliers[index]);
  }
  return label;
}
} // namespace

BattleStats CalculateConfigurationStats(const BattleStats& base, std::int32_t level,
                                         const ConfigurationStatProfile& profile) {
  if (level < 1 || level > 100) throw std::invalid_argument("configuration level must be 1 to 100");
  const auto bases = Values(base);
  const auto ivs = Values(profile.ivs);
  const auto evs = Values(profile.evs);
  std::int32_t total = 0;
  for (std::size_t index = 0; index < bases.size(); ++index) {
    if (bases[index] <= 0 || ivs[index] < 0 || ivs[index] > 31 || evs[index] < 0 || evs[index] > 252) {
      throw std::invalid_argument("configuration stat input violates base or IV or EV bounds");
    }
    total += evs[index];
  }
  if (total > 510) throw std::invalid_argument("total EVs must not exceed 510");
  ValidateNature(profile.nature);
  std::array<std::int32_t, 6> actual{};
  actual[0] = Narrow(static_cast<double>(CalculateHp({bases[0], ivs[0], evs[0], level})));
  for (std::size_t index = 1; index < bases.size(); ++index) {
    const auto raw = CalculateNonHp({bases[index], ivs[index], evs[index], level}, NatureEffect::neutral);
    actual[index] = Narrow(std::floor(static_cast<double>(raw) * profile.nature.multipliers[index - 1]));
  }
  return Stats(actual);
}

ConfigurationStatSpace EnumerateConfigurationStats(const ConfigurationStatInput& input,
                                                   CancellationToken cancellation) {
  if (input.max_raw_profiles == 0) throw std::invalid_argument("max_raw_profiles must be positive");
  CheckCancellation(cancellation);
  ConfigurationStatSpace result;
  std::map<std::array<std::int32_t, 6>, std::size_t> grouped;
  /// @param profile 完整合法原始配置；@param label 代表说明；按原成员计数再归并。
  const auto append = [&](const ConfigurationStatProfile& profile, std::string label) {
    CheckCancellation(cancellation);
    ++result.raw_profile_count;
    if (result.raw_profile_count > input.max_raw_profiles) {
      throw std::length_error("stat enumeration exceeds max_raw_profiles before deduplication");
    }
    const auto actual = CalculateConfigurationStats(input.base, input.level, profile);
    const auto [entry, inserted] = grouped.emplace(Values(actual), result.classes.size());
    if (inserted) result.classes.push_back({profile, actual, std::move(label), Integer{1}});
    else ++result.classes[entry->second].member_count;
  };
  if (const auto* presets = std::get_if<PresetStatEnumeration>(&input.enumeration)) {
    for (const auto& preset : presets->presets) append(preset.profile, preset.label);
  } else {
    const auto& command = std::get<ControlledStatEnumeration>(input.enumeration);
    if (command.fields.empty() || command.ev_values.empty() || command.natures.empty()) {
      throw std::invalid_argument("controlled stat fields and values and natures must not be empty");
    }
    std::array<bool, 6> seen{};
    for (const auto field : command.fields) {
      const auto index = FieldIndex(field);
      if (seen[index]) throw std::invalid_argument("controlled stat fields must be unique");
      seen[index] = true;
    }
    auto values = command.ev_values;
    std::ranges::sort(values);
    if (values.front() < 0 || values.back() > 252 || std::ranges::adjacent_find(values) != values.end()) {
      throw std::invalid_argument("controlled EV values must be unique and between 0 and 252");
    }
    std::set<std::array<double, 5>> seen_natures;
    for (const auto& nature : command.natures) {
      ValidateNature(nature);
      if (!seen_natures.insert(nature.multipliers).second) {
        throw std::invalid_argument("controlled natures must be unique");
      }
    }
    std::array<std::int32_t, 6> evs{};
    /// @param self 显式递归；@param depth 当前命令轴；@param total 已选EV总量。
    /// 保留 product 顺序，非负前缀超510时整段跳过，不扫描非法组合笛卡尔尾部。
    const auto visit = [&](auto&& self, std::size_t depth, std::int32_t total) -> void {
      CheckCancellation(cancellation);
      if (depth == command.fields.size()) {
        for (const auto& nature : command.natures) {
          append({{31, 31, 31, 31, 31, 31}, Stats(evs), nature}, ControlledLabel(evs, nature, command.fields));
        }
        return;
      }
      const auto field = FieldIndex(command.fields[depth]);
      for (const auto value : values) {
        if (total + value > 510) break;
        evs[field] = value;
        self(self, depth + 1, total + value);
      }
      evs[field] = 0;
    };
    visit(visit, 0, 0);
  }
  if (result.classes.empty()) throw std::invalid_argument("stat dimension has no executable values");
  return result;
}
} // namespace pbi
