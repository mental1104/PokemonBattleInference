#pragma once

#include "pbi/damage.hpp"
#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace pbi {
/// 原旧Nature枚举顺序；Quiet保留旧字典的Speed=1.0，不改变现代配置/回合性格。
enum class LegacyNature { hardy, lonely, adamant, naughty, brave, bold, docile, impish, lax, relaxed,
  modest, mild, bashful, rash, quiet, calm, gentle, careful, quirky, sassy, timid, hasty, jolly, naive, serious };

/// 原PokemonDirector实际消费的构造事实；六轴顺序HP/Atk/Def/SpAtk/SpDef/Speed，EV允许原浮点除四语义。
/// individual_values刻意不在此模型：原HTTP没有传入director，实际固定使用全31；null nature表示原无修正。
struct LegacyPokemonInput {
  std::int64_t level = 100;
  std::array<std::int64_t, 6> base{};
  std::vector<std::int64_t> basepoint{0, 0, 0, 0, 0, 0};
  std::optional<LegacyNature> nature = LegacyNature::adamant;
  std::vector<PokemonType> types;
};

/// 旧自由招式，无现代效果/道具/等级修正；status同原链产生零伤害。
struct LegacyMove {
  std::int64_t power = 40;
  PokemonType type = PokemonType::normal;
  DamageCategory category = DamageCategory::physical;
};

/// 独立旧伤害输入；random_unit是平台注入的[0,1]随机事实，uniform/round/截断全部在Core执行。
struct LegacyDamageInput {
  LegacyPokemonInput attacker;
  LegacyPokemonInput defender;
  LegacyMove move;
  double random_unit = 0;
};

/// 旧能力公式的任意精度整数结果，不能用现代分层floor或int32快照替代。
using LegacyStats = std::array<Integer, 6>;

/// 原七字段结果与准备证据；HTTP只投影原七字段，额外统计/随机倍率供差分与可复现诊断。
struct LegacyDamageResult {
  std::string formula;
  Integer min_damage;
  Integer max_damage;
  Integer random_damage;
  double min_damage_percent;
  double max_damage_percent;
  double random_damage_percent;
  LegacyStats attacker_stats;
  LegacyStats defender_stats;
  double random_multiplier;
};

/// @param input 只读历史构造事实，basepoint不足六项拒绝、超过六项忽略；不修改或校正EV/等级。
/// @return 原binary64能力公式的六项结果；非有限浮点/非法性格显式抛异常，不回退现代公式。
[[nodiscard]] LegacyStats CalculateLegacyStats(const LegacyPokemonInput& input);

/// @param input 只读双方/招式/随机事实；@param knowledge 拥有者提供的旧语义属性相克，不在Core查询DB。
/// @return 原逐链int/随机两位舍入/一位百分比结果；缺知识、除零、非有限输入显式抛异常。
[[nodiscard]] LegacyDamageResult CalculateLegacyDamage(const LegacyDamageInput& input, const TypeChartSnapshot& knowledge);
} // namespace pbi
