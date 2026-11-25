#pragma once

#include "pbi/cancellation.hpp"
#include "pbi/damage.hpp"
#include <array>
#include <variant>

namespace pbi {
/// 配置枚举的六项 EV 轴，顺序与旧 StatValues 保持一致。
enum class ConfigurationStatField { hp, attack, defense, special_attack, special_defense, speed };
/// 完整性格倍率；兼容旧预设仅提高一项而不降低另一项的行为。
struct ConfigurationNature {
  std::array<double, 5> multipliers{1.0, 1.0, 1.0, 1.0, 1.0};
  /// @param other 只读倍率；@return 五轴是否全部相等。
  bool operator==(const ConfigurationNature& other) const = default;
};
/// 纯计算配置快照，不携带数据库 preset ID 或可变实体。
struct ConfigurationStatProfile {
  BattleStats ivs{31, 31, 31, 31, 31, 31};
  BattleStats evs{};
  ConfigurationNature nature;
};
/// 已解析的预设/自定义快照；label 只解释第一代表，不参与行为归并。
struct ConfigurationStatPreset {
  ConfigurationStatProfile profile;
  std::string label;
};
/// 预设模式保持输入顺序，按合法原始 profile 计数，不提前去重。
struct PresetStatEnumeration {
  std::vector<ConfigurationStatPreset> presets;
};
/// 受控模式按字段顺序、排序后的 EV 值、性格顺序执行惰性枚举。
struct ControlledStatEnumeration {
  std::vector<ConfigurationStatField> fields;
  std::vector<std::int32_t> ev_values;
  std::vector<ConfigurationNature> natures;
};
/// 显式原始有效 profile 预算；超过时整次失败，绝不返回归一化的部分空间。
struct ConfigurationStatInput {
  BattleStats base;
  std::int32_t level = 50;
  std::variant<PresetStatEnumeration, ControlledStatEnumeration> enumeration;
  std::size_t max_raw_profiles = 4096;
};
/// 最终能力等价类；保留第一个 EV/IV/性格代表和精确原始成员数。
struct ConfigurationStatClass {
  ConfigurationStatProfile representative;
  BattleStats actual;
  std::string label;
  Integer member_count{1};
};
/// 全部有效原始 profile 的无损分区，类顺序与首次遇见顺序一致。
struct ConfigurationStatSpace {
  std::vector<ConfigurationStatClass> classes;
  Integer raw_profile_count{0};
};
/// @param base 只读种族值；@param level 等级；@param profile 只读完整投入与倍率。
/// @return 复用基础能力公式后按旧 binary64 性格乘法 floor 的六项能力。
/// 非有限倍率、非法投入或 int32 输出越界明确失败。
[[nodiscard]] BattleStats CalculateConfigurationStats(const BattleStats& base, std::int32_t level,
                                                     const ConfigurationStatProfile& profile);
/// @param input 只读预设/受控候选命令；@param cancellation 同源安全取消令牌。
/// @return 按最终能力归并的精确分区；预算越界、空空间和取消明确抛异常。
[[nodiscard]] ConfigurationStatSpace EnumerateConfigurationStats(
    const ConfigurationStatInput& input, CancellationToken cancellation = {});
} // namespace pbi
