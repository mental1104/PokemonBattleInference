#pragma once

#include "pbi/calculations.hpp"
#include <array>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace pbi {

/// 纯领域属性标识，数值对应原 Python/PokeAPI；未知属性不能伪装为普通属性。
enum class PokemonType {
  normal = 1, fighting, flying, poison, ground, rock, bug, ghost, steel,
  fire, water, grass, electric, psychic, ice, dragon, dark, fairy
};
/// 直接伤害分类；变化招式必须由回合/效果层处理，不能返回虚构伤害。
enum class DamageCategory { physical, special, status };
/// 战斗快照已识别的特性；直接伤害入口对仍需动态 HP/畏缩处理的特性明确报 unsupported。
enum class DamageAbility { none, technician, adaptability, thick_fat, filter, solid_rock, sniper, multiscale, inner_focus };
/// 当前直接伤害支持的道具；锁招和道具消耗不属于本次纯计算。
enum class DamageItem { none, life_orb, choice_band, choice_specs, expert_belt, eviolite };
/// 环境状态；none 表示明确没有天气或场地，不是未知值回退。
enum class DamageWeather { none, harsh_sunlight, rain, sandstorm, hail, snow };
enum class DamageTerrain { none, electric, psychic, grassy, misty };
/// 接地覆盖值为空时，按原合同仅以飞行属性决定接地。
enum class Grounding { grounded, airborne };
/// 稳定伤害阶段，保留旧责任链的顺序和 trace 语义。
enum class DamageStage { base_power, attack_stat, defense_stat, stab, type_effectiveness,
                         screen, critical, spread, protect, final_damage, random };
/// 有限修正来源；领域层不使用动态字符串注册规则。
enum class DamageSource { technician, adaptability, thick_fat, filter, solid_rock, sniper,
                          life_orb, choice_band, choice_specs, expert_belt, eviolite,
                          stab, type_effectiveness, critical_hit, spread_move, protect_reduction,
                          harsh_sunlight, rain, sandstorm, hail, snow,
                          electric_terrain, psychic_terrain, grassy_terrain, misty_terrain,
                          reflect, light_screen, aurora_veil, random };

/// 明确不支持的规则或缺少知识，交给 ABI 映射为 UNSUPPORTED；不默认为中性。
class UnsupportedRule final : public std::invalid_argument {
public:
  /// @param message 固定 ASCII 规则错误；异常拥有一份副本。
  explicit UnsupportedRule(const char* message) : std::invalid_argument(message) {}
};

/// 六项已计算能力快照；只消费数据，不持有物种库/数据库句柄。
struct BattleStats {
  std::int32_t hp;
  std::int32_t attack;
  std::int32_t defense;
  std::int32_t special_attack;
  std::int32_t special_defense;
  std::int32_t speed;
  /// @param other 只读六项能力；@return 全部字段是否相同。
  bool operator==(const BattleStats& other) const = default;
};

/// 一侧进入直接计算的不可变快照（通过 const 借用），与配置/当前 HP 状态分离。
struct DamagePokemon {
  std::int32_t level;
  std::vector<PokemonType> types;
  BattleStats stats;
  DamageAbility ability = DamageAbility::none;
  DamageItem item = DamageItem::none;
  bool can_evolve = false;
  std::optional<Grounding> grounding;
  /// @param other 只读快照；@return 所有会影响战斗的字段是否相同。
  bool operator==(const DamagePokemon& other) const = default;
};

/// 招式知识快照，保留分类/属性/固定威力，不在 Core 查询数据源。
struct DamageMove {
  PokemonType type;
  DamageCategory category;
  std::int32_t power;
  /// @param other 只读招式；@return 属性、分类与威力是否相同。
  bool operator==(const DamageMove& other) const = default;
};

/// 防守侧屏障。旧链允许屏障和极光幕叠加，迁移不擅自改成官方互斥规则。
struct DamageScreens {
  bool reflect = false;
  bool light_screen = false;
  bool aurora_veil = false;
  /// @param other 只读边侧；@return 三种屏障是否相同。
  bool operator==(const DamageScreens& other) const = default;
};

/// 全部现有 Python DamagePolicy 字段的值快照。
/// double 仅保留旧伤害链 binary64 倍率/取整兼容；所有概率仍使用 Rational。
struct DamagePolicy {
  double terrain_boost_multiplier = 1.3;
  double misty_terrain_dragon_multiplier = 0.5;
  double weather_boost_multiplier = 1.5;
  double weather_weaken_multiplier = 0.5;
  std::optional<double> sandstorm_rock_spdef_multiplier = 1.5;
  std::optional<double> snow_ice_defense_multiplier = 1.5;
  std::optional<double> hail_ice_defense_multiplier;
  double screen_single_target_multiplier = 0.5;
  double screen_multi_target_multiplier = 2.0 / 3.0;
  double aurora_veil_single_target_multiplier = 0.5;
  double aurora_veil_multi_target_multiplier = 2.0 / 3.0;
  double critical_hit_multiplier = 1.5;
  double spread_move_multiplier = 0.75;
  double protect_damage_multiplier = 0.25;
  double same_type_attack_bonus_multiplier = 1.5;
  std::int32_t technician_base_power_threshold = 60;
  double technician_base_power_multiplier = 1.5;
  double adaptability_stab_multiplier = 2.0;
  double thick_fat_damage_multiplier = 0.5;
  double filter_damage_multiplier = 0.75;
  double sniper_critical_multiplier = 1.5;
  double multiscale_damage_multiplier = 0.5;
  double life_orb_damage_multiplier = 1.3;
  double choice_item_attack_multiplier = 1.5;
  double expert_belt_damage_multiplier = 1.2;
  double eviolite_defense_multiplier = 1.5;
  double burn_physical_attack_multiplier = 0.5;
  std::vector<double> random_damage_multipliers{
      0.85, 0.86, 0.87, 0.88, 0.89, 0.90, 0.91, 0.92,
      0.93, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99, 1.0};
  /// @param other 只读完整策略；@return 所有倍率、阈值与随机槽位是否相同。
  bool operator==(const DamagePolicy& other) const = default;
};

/// 单条属性相克知识；Core 不内置与数据库脱节的另一套属性表。
struct TypeEfficacy {
  PokemonType attacking;
  PokemonType defending;
  std::int32_t percent;
};

/// 拥有并冻结本次所需知识的快照，缺失条目明确报错。
class TypeChartSnapshot {
public:
  /// @param entries 转移拥有权的相克条目；负倍率、未知属性或重复键抛出 invalid_argument。
  explicit TypeChartSnapshot(std::vector<TypeEfficacy> entries);
  /// @param attacking 招式属性；@param defending 目标属性；@return 百分制倍率，缺失抛出 UnsupportedRule。
  [[nodiscard]] std::int32_t Efficacy(PokemonType attacking, PokemonType defending) const;
private:
  std::vector<TypeEfficacy> entries_;
};

/// 一次纯伤害请求；policy 与知识均由外层按版本选择后注入。
struct DamageInput {
  DamagePokemon attacker;
  DamagePokemon defender;
  DamageMove move;
  DamagePolicy policy;
  DamageWeather weather = DamageWeather::none;
  DamageTerrain terrain = DamageTerrain::none;
  DamageScreens defender_side;
  bool critical = false;
  bool spread = false;
  bool protect_reduced = false;
  bool multi_target = false;
};

/// 一条实际生效的修正，保留顺序、来源与旧 reason；随机阶段的 multiplier 为空。
struct DamageTrace {
  DamageSource key;
  DamageStage stage;
  DamageSource source;
  std::optional<double> multiplier;
  std::optional<double> min_multiplier;
  std::optional<double> max_multiplier;
  std::string reason;
};

/// 新计算结果；伤害档位是整数，期望与概率展示派生值保持精确。
struct DamageResult {
  std::vector<std::int64_t> rolls;
  std::int32_t defender_hp;
  std::int64_t base_damage;
  std::vector<DamageTrace> trace;
};

/// @param generation 1…9 的原有兼容 profile；@return 对应的新策略，未知代际抛出 UnsupportedRule。
[[nodiscard]] DamagePolicy DamagePolicyForGeneration(std::int32_t generation);
/// @param policy 只读完整策略；非法倍率/空随机档位抛 invalid_argument，不执行计算。
void ValidateDamagePolicy(const DamagePolicy& policy);
/// @param version_group PokeAPI 固定版本组；@return 原 resolver 的代际，未知版本组明确失败。
[[nodiscard]] std::int32_t GenerationForVersionGroup(std::int32_t version_group);
/// @param value 只读修正来源；@return 协议使用的静态名称，未知枚举抛出 UnsupportedRule。
[[nodiscard]] std::string_view DamageSourceName(DamageSource value);
/// @param value 只读阶段；@return 协议使用的静态名称，未知枚举抛出 UnsupportedRule。
[[nodiscard]] std::string_view DamageStageName(DamageStage value);
/// @param input 只读战斗/策略快照；@param knowledge 完整所需相克知识，不保留引用。
/// @return 完整随机档位与 trace；非法输入/不支持规则明确失败，非有限或越界输出抛出 overflow_error。
[[nodiscard]] DamageResult CalculateDamage(const DamageInput& input, const TypeChartSnapshot& knowledge);

} // namespace pbi
