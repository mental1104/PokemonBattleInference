#include "pbi/damage.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <type_traits>
#include <utility>

namespace pbi {
namespace {

/// 验证连续的有限枚举，防止 C++ 调用者通过强制转换绕过不支持规则检查。
/// @tparam T 领域枚举类型；@param value 输入值；@param first 最小值；@param last 最大值。
template <class T> void RequireEnum(T value, T first, T last) {
  using Underlying = std::underlying_type_t<T>;
  if (static_cast<Underlying>(value) < static_cast<Underlying>(first) ||
      static_cast<Underlying>(value) > static_cast<Underlying>(last)) {
    throw UnsupportedRule("unsupported damage enum value");
  }
}

/// @param value binary64 中间结果；@return 向下取整的 int64，非有限/越界明确失败。
std::int64_t FloorInteger(double value) {
  constexpr double boundary = 9223372036854775808.0;
  const double result = std::floor(value);
  if (!std::isfinite(result) || result < -boundary || result >= boundary) {
    throw std::overflow_error("damage result exceeds int64 range");
  }
  return static_cast<std::int64_t>(result);
}

/// @param value 旧策略中的数值倍率；负数/非有限值明确失败，不改变倍率。
void RequireMultiplier(double value) {
  if (!std::isfinite(value) || value < 0) {
    throw std::invalid_argument("damage multiplier must be finite and nonnegative");
  }
}

/// 将整数比值按 nearest/ties-to-even 转换成 binary64，避免先转分子造成双重舍入。
/// @param numerator 有符号整数分子，只读；@param denominator 严格正分母，只读。
/// @return 与 Python int/int 一致的 binary64；这里的整数输入范围不涉及次正规数。
double IntegerRatioAsDouble(const Integer& numerator, const Integer& denominator) {
  if (numerator == 0) return 0.0;
  const bool negative = numerator < 0;
  const Integer magnitude = negative ? -numerator : numerator;
  int exponent = static_cast<int>(boost::multiprecision::msb(magnitude)) -
                 static_cast<int>(boost::multiprecision::msb(denominator));
  if (exponent >= 0 ? magnitude < (denominator << exponent) : (magnitude << -exponent) < denominator) --exponent;
  const int shift = 52 - exponent;
  const Integer scaled_numerator = shift >= 0 ? Integer{magnitude << shift} : magnitude;
  const Integer scaled_denominator = shift >= 0 ? denominator : Integer{denominator << -shift};
  Integer significand = scaled_numerator / scaled_denominator;
  const Integer twice_remainder = (scaled_numerator % scaled_denominator) * 2;
  if (twice_remainder > scaled_denominator ||
      (twice_remainder == scaled_denominator && (significand & 1) != 0)) ++significand;
  const double value = std::ldexp(significand.convert_to<double>(), exponent - 52);
  return negative ? -value : value;
}

/// @param policy 只读完整策略；检查所有字段和随机档位，不忽略自定义输入。
void ValidatePolicy(const DamagePolicy& policy) {
  const std::array values{
      policy.terrain_boost_multiplier, policy.misty_terrain_dragon_multiplier,
      policy.weather_boost_multiplier, policy.weather_weaken_multiplier,
      policy.screen_single_target_multiplier, policy.screen_multi_target_multiplier,
      policy.aurora_veil_single_target_multiplier, policy.aurora_veil_multi_target_multiplier,
      policy.critical_hit_multiplier, policy.spread_move_multiplier, policy.protect_damage_multiplier,
      policy.same_type_attack_bonus_multiplier, policy.technician_base_power_multiplier,
      policy.adaptability_stab_multiplier, policy.thick_fat_damage_multiplier, policy.filter_damage_multiplier,
      policy.sniper_critical_multiplier, policy.multiscale_damage_multiplier,
      policy.life_orb_damage_multiplier, policy.choice_item_attack_multiplier,
      policy.expert_belt_damage_multiplier, policy.eviolite_defense_multiplier, policy.burn_physical_attack_multiplier};
  for (const auto value : values) RequireMultiplier(value);
  for (const auto value : {policy.sandstorm_rock_spdef_multiplier, policy.snow_ice_defense_multiplier,
                           policy.hail_ice_defense_multiplier}) {
    if (value) RequireMultiplier(*value);
  }
  if (policy.technician_base_power_threshold < 0 || policy.random_damage_multipliers.empty()) {
    throw std::invalid_argument("invalid technician threshold or empty random multipliers");
  }
  for (const auto value : policy.random_damage_multipliers) RequireMultiplier(value);
}

/// @param pokemon 只读战斗快照；基础输入约束沿用原 BattlePokemon。
void ValidatePokemon(const DamagePokemon& pokemon) {
  if (pokemon.level < 1 || pokemon.types.empty()) {
    throw std::invalid_argument("pokemon must have a positive level and nonempty types");
  }
  for (const auto type : pokemon.types) RequireEnum(type, PokemonType::normal, PokemonType::fairy);
  RequireEnum(pokemon.ability, DamageAbility::none, DamageAbility::sniper);
  RequireEnum(pokemon.item, DamageItem::none, DamageItem::eviolite);
  if (pokemon.grounding) RequireEnum(*pokemon.grounding, Grounding::grounded, Grounding::airborne);
}

/// @param pokemon 只读战斗快照；@param type 待查属性；@return 是否具有该属性。
bool HasType(const DamagePokemon& pokemon, PokemonType type) {
  return std::find(pokemon.types.begin(), pokemon.types.end(), type) != pokemon.types.end();
}

/// @param pokemon 只读战斗快照；@return 原有最小接地规则结果，不推定重力等新机制。
bool Grounded(const DamagePokemon& pokemon) {
  return pokemon.grounding ? *pokemon.grounding == Grounding::grounded : !HasType(pokemon, PokemonType::flying);
}

/// 一次调用独占的累积结果；显式成员方法表达阶段取整和 trace 写入，不修改输入。
class Calculation {
public:
  /// @param input 借用至当前计算结束的只读输入；构造时选取物理/特殊的基础能力。
  explicit Calculation(const DamageInput& input)
      : input_(input), power_(input.move.power),
        attack_(input.move.category == DamageCategory::physical ? input.attacker.stats.attack : input.attacker.stats.special_attack),
        defense_(input.move.category == DamageCategory::physical ? input.defender.stats.defense : input.defender.stats.special_defense) {}

  /// @param key 修正来源；@param stage 阶段；@param multiplier binary64 兼容倍率；
  /// @param reason 原 reason 文本；@param source 可选的实际来源（STAB/会心允许特性改写）。
  /// 对对应能力逐阶段 floor，其余倍率按原链顺序累乘并记录 trace。
  void Apply(DamageSource key, DamageStage stage, double multiplier, std::string_view reason,
             std::optional<DamageSource> source = std::nullopt) {
    switch (stage) {
    case DamageStage::base_power: power_ = FloorInteger(static_cast<double>(power_) * multiplier); break;
    case DamageStage::attack_stat: attack_ = FloorInteger(static_cast<double>(attack_) * multiplier); break;
    case DamageStage::defense_stat: defense_ = FloorInteger(static_cast<double>(defense_) * multiplier); break;
    default: multiplier_ *= multiplier; break;
    }
    trace_.push_back({key, stage, source.value_or(key), multiplier, std::nullopt, std::nullopt, std::string{reason}});
  }

  /// 依照原链执行基础威力、攻防能力、公式，所有值都存放本调用实例。
  void Base() {
    const auto& policy = input_.policy;
    if (input_.attacker.ability == DamageAbility::technician && power_ <= policy.technician_base_power_threshold) {
      Apply(DamageSource::technician, DamageStage::base_power, policy.technician_base_power_multiplier,
            "Technician boosts moves with base power 60 or lower.");
    }
    if (input_.attacker.item == DamageItem::choice_band && input_.move.category == DamageCategory::physical) {
      Apply(DamageSource::choice_band, DamageStage::attack_stat, policy.choice_item_attack_multiplier,
            "Choice Band boosts Attack for physical moves.");
    }
    if (input_.attacker.item == DamageItem::choice_specs && input_.move.category == DamageCategory::special) {
      Apply(DamageSource::choice_specs, DamageStage::attack_stat, policy.choice_item_attack_multiplier,
            "Choice Specs boosts Special Attack for special moves.");
    }
    if (input_.weather == DamageWeather::sandstorm && policy.sandstorm_rock_spdef_multiplier &&
        input_.move.category == DamageCategory::special && HasType(input_.defender, PokemonType::rock)) {
      Apply(DamageSource::sandstorm, DamageStage::defense_stat, *policy.sandstorm_rock_spdef_multiplier,
            "Sandstorm boosts Rock-type Special Defense.");
    } else if (input_.weather == DamageWeather::snow && policy.snow_ice_defense_multiplier &&
               input_.move.category == DamageCategory::physical && HasType(input_.defender, PokemonType::ice)) {
      Apply(DamageSource::snow, DamageStage::defense_stat, *policy.snow_ice_defense_multiplier,
            "Modern snow boosts Ice-type Defense.");
    } else if (input_.weather == DamageWeather::hail && policy.hail_ice_defense_multiplier &&
               input_.move.category == DamageCategory::physical && HasType(input_.defender, PokemonType::ice)) {
      Apply(DamageSource::hail, DamageStage::defense_stat, *policy.hail_ice_defense_multiplier,
            "Hail boosts Ice-type Defense when enabled by policy.");
    }
    if (input_.defender.item == DamageItem::eviolite && input_.defender.can_evolve) {
      Apply(DamageSource::eviolite, DamageStage::defense_stat, policy.eviolite_defense_multiplier,
            "Eviolite boosts Defense and Special Defense when the holder can evolve.");
    }
    if (defense_ <= 0) throw std::invalid_argument("defense must be greater than 0");
    const auto level_factor = FloorInteger((2.0 * input_.attacker.level) / 5.0 + 2.0);
    const Integer product = Integer{level_factor} * power_ * attack_;
    // Python 的中间 floor 返回任意精度整数，scaled 可以超出 int64 而最终伤害仍合法。
    const Integer scaled{std::floor(IntegerRatioAsDouble(product, Integer{defense_}))};
    base_ = FloorInteger(IntegerRatioAsDouble(scaled, Integer{50})) + 2;
  }

  /// @param knowledge 借用的属性相克快照；先 STAB，再逐属性累乘，免疫仍保留其余 trace。
  void Typing(const TypeChartSnapshot& knowledge) {
    const auto& policy = input_.policy;
    const bool stab = HasType(input_.attacker, input_.move.type);
    const bool adaptability = stab && input_.attacker.ability == DamageAbility::adaptability;
    Apply(DamageSource::stab, DamageStage::stab,
          adaptability ? policy.adaptability_stab_multiplier : stab ? policy.same_type_attack_bonus_multiplier : 1.0,
          adaptability ? "Adaptability raises STAB to 2.0." : "Same-type attack bonus.",
          adaptability ? DamageSource::adaptability : DamageSource::stab);
    for (const auto type : input_.defender.types) {
      effectiveness_ *= knowledge.Efficacy(input_.move.type, type) / 100.0;
    }
    Apply(DamageSource::type_effectiveness, DamageStage::type_effectiveness, effectiveness_, "Type effectiveness multiplier.");
  }

  /// 依序执行屏障、会心、范围和保护。会心忽略屏障，但不提前改动其他倍率。
  void BattleFlags() {
    const auto& policy = input_.policy;
    if (!input_.critical) {
      const double screen = input_.multi_target ? policy.screen_multi_target_multiplier : policy.screen_single_target_multiplier;
      if (input_.defender_side.reflect && input_.move.category == DamageCategory::physical) {
        Apply(DamageSource::reflect, DamageStage::screen, screen, "Reflect reduces physical direct damage on defender side.");
      }
      if (input_.defender_side.light_screen && input_.move.category == DamageCategory::special) {
        Apply(DamageSource::light_screen, DamageStage::screen, screen, "Light Screen reduces special direct damage on defender side.");
      }
      if (input_.defender_side.aurora_veil) {
        Apply(DamageSource::aurora_veil, DamageStage::screen,
              input_.multi_target ? policy.aurora_veil_multi_target_multiplier : policy.aurora_veil_single_target_multiplier,
              "Aurora Veil reduces physical and special direct damage on defender side.");
      }
    }
    if (input_.critical) {
      const bool sniper = input_.attacker.ability == DamageAbility::sniper;
      const double multiplier = sniper ? policy.critical_hit_multiplier * policy.sniper_critical_multiplier : policy.critical_hit_multiplier;
      Apply(DamageSource::critical_hit, DamageStage::critical, multiplier,
            sniper ? "Sniper increases critical-hit damage by 50%." : "Critical hit direct damage multiplier.",
            sniper ? DamageSource::sniper : DamageSource::critical_hit);
    }
    if (input_.spread) Apply(DamageSource::spread_move, DamageStage::spread, policy.spread_move_multiplier, "Spread move damage multiplier for this target.");
    if (input_.protect_reduced) Apply(DamageSource::protect_reduction, DamageStage::protect, policy.protect_damage_multiplier, "Protect-style damage reduction hook.");
  }

  /// 天气和场地按原顺序进入最终倍率；接地覆盖和 disabled policy 都有明确含义。
  void Environment() {
    const auto& policy = input_.policy;
    const auto type = input_.move.type;
    if (input_.weather == DamageWeather::harsh_sunlight && type == PokemonType::fire) {
      Apply(DamageSource::harsh_sunlight, DamageStage::final_damage, policy.weather_boost_multiplier, "Harsh sunlight boosts Fire-type damage.");
    } else if (input_.weather == DamageWeather::harsh_sunlight && type == PokemonType::water) {
      Apply(DamageSource::harsh_sunlight, DamageStage::final_damage, policy.weather_weaken_multiplier, "Harsh sunlight weakens Water-type damage.");
    } else if (input_.weather == DamageWeather::rain && type == PokemonType::water) {
      Apply(DamageSource::rain, DamageStage::final_damage, policy.weather_boost_multiplier, "Rain boosts Water-type damage.");
    } else if (input_.weather == DamageWeather::rain && type == PokemonType::fire) {
      Apply(DamageSource::rain, DamageStage::final_damage, policy.weather_weaken_multiplier, "Rain weakens Fire-type damage.");
    }
    const auto terrain = input_.terrain;
    const bool boost = (terrain == DamageTerrain::electric && type == PokemonType::electric) ||
                       (terrain == DamageTerrain::psychic && type == PokemonType::psychic) ||
                       (terrain == DamageTerrain::grassy && type == PokemonType::grass);
    if (boost && Grounded(input_.attacker)) {
      const auto source = terrain == DamageTerrain::electric ? DamageSource::electric_terrain :
                          terrain == DamageTerrain::psychic ? DamageSource::psychic_terrain : DamageSource::grassy_terrain;
      const std::string name = terrain == DamageTerrain::electric ? "electric_terrain" : terrain == DamageTerrain::psychic ? "psychic_terrain" : "grassy_terrain";
      Apply(source, DamageStage::final_damage, policy.terrain_boost_multiplier, name + " boosts grounded matching-type attacks.");
    } else if (terrain == DamageTerrain::misty && type == PokemonType::dragon && Grounded(input_.defender)) {
      Apply(DamageSource::misty_terrain, DamageStage::final_damage, policy.misty_terrain_dragon_multiplier, "Misty Terrain weakens Dragon-type damage to grounded defenders.");
    }
  }

  /// 防守特性和攻击道具保留独立阶段来源；不支持的动态特性在解析时明确拒绝。
  void FinalEffects() {
    const auto& policy = input_.policy;
    const auto ability = input_.defender.ability;
    if (ability == DamageAbility::thick_fat && (input_.move.type == PokemonType::fire || input_.move.type == PokemonType::ice)) {
      Apply(DamageSource::thick_fat, DamageStage::final_damage, policy.thick_fat_damage_multiplier, "Thick Fat halves incoming Fire- and Ice-type damage.");
    } else if (effectiveness_ > 1.0 && (ability == DamageAbility::filter || ability == DamageAbility::solid_rock)) {
      Apply(ability == DamageAbility::filter ? DamageSource::filter : DamageSource::solid_rock,
            DamageStage::final_damage, policy.filter_damage_multiplier,
            ability == DamageAbility::filter ? "Filter reduces super-effective damage." : "Solid Rock reduces super-effective damage.");
    }
    if (input_.attacker.item == DamageItem::life_orb) {
      Apply(DamageSource::life_orb, DamageStage::final_damage, policy.life_orb_damage_multiplier, "Life Orb boosts direct damage.");
    } else if (input_.attacker.item == DamageItem::expert_belt && effectiveness_ > 1.0) {
      Apply(DamageSource::expert_belt, DamageStage::final_damage, policy.expert_belt_damage_multiplier, "Expert Belt boosts super-effective damage.");
    }
  }

  /// @return 最后按每个随机倍率 floor 后的新结果；不施加旧链不存在的最小伤害钳制。
  DamageResult Finish() {
    std::vector<std::int64_t> rolls;
    rolls.reserve(input_.policy.random_damage_multipliers.size());
    for (const auto random : input_.policy.random_damage_multipliers) {
      // 两次 binary64 乘法对应 Python 的左结合表达式；不重排成官方 4096 链。
      const double modified = static_cast<double>(base_) * multiplier_;
      rolls.push_back(FloorInteger(modified * random));
    }
    trace_.push_back({DamageSource::random, DamageStage::random, DamageSource::random, std::nullopt,
                      input_.policy.random_damage_multipliers.front(), input_.policy.random_damage_multipliers.back(),
                      "Pokemon damage random roll range."});
    return {std::move(rolls), input_.defender.stats.hp, base_, std::move(trace_)};
  }
private:
  const DamageInput& input_;
  std::int64_t power_;
  std::int64_t attack_;
  std::int64_t defense_;
  std::int64_t base_ = 0;
  double multiplier_ = 1.0;
  double effectiveness_ = 1.0;
  std::vector<DamageTrace> trace_;
};
} // namespace

void ValidateDamagePolicy(const DamagePolicy& policy) { ValidatePolicy(policy); }

TypeChartSnapshot::TypeChartSnapshot(std::vector<TypeEfficacy> entries) : entries_(std::move(entries)) {
  for (std::size_t i = 0; i < entries_.size(); ++i) {
    const auto& entry = entries_[i];
    RequireEnum(entry.attacking, PokemonType::normal, PokemonType::fairy);
    RequireEnum(entry.defending, PokemonType::normal, PokemonType::fairy);
    if (entry.percent < 0) throw std::invalid_argument("type efficacy must not be negative");
    for (std::size_t j = 0; j < i; ++j) {
      if (entries_[j].attacking == entry.attacking && entries_[j].defending == entry.defending) {
        throw std::invalid_argument("duplicate type efficacy entry");
      }
    }
  }
}

std::int32_t TypeChartSnapshot::Efficacy(PokemonType attacking, PokemonType defending) const {
  for (const auto& entry : entries_) {
    if (entry.attacking == attacking && entry.defending == defending) return entry.percent;
  }
  throw UnsupportedRule("type efficacy knowledge is missing");
}

DamagePolicy DamagePolicyForGeneration(std::int32_t generation) {
  if (generation < 1 || generation > 9) throw UnsupportedRule("unsupported generation");
  DamagePolicy result;
  result.terrain_boost_multiplier = generation >= 8 ? 1.3 : generation >= 6 ? 1.5 : 1.0;
  if (generation <= 3) result.sandstorm_rock_spdef_multiplier.reset();
  if (generation <= 8) result.snow_ice_defense_multiplier.reset();
  result.critical_hit_multiplier = generation <= 5 ? 2.0 : 1.5;
  return result;
}

std::int32_t GenerationForVersionGroup(std::int32_t version_group) {
  constexpr std::array generations{1, 1, 2, 2, 3, 3, 3, 4, 4, 4, 5, 3, 3, 5, 6, 6,
                                   7, 7, 7, 8, 8, 8, 8, 8, 9, 9, 9, 1, 1, 9, 9};
  if (version_group < 1 || static_cast<std::size_t>(version_group) > generations.size()) {
    throw UnsupportedRule("unsupported version group");
  }
  return generations[static_cast<std::size_t>(version_group - 1)];
}

std::string_view DamageSourceName(DamageSource value) {
  constexpr std::array<std::string_view, 28> names{
      "ability:technician", "ability:adaptability", "ability:thick_fat", "ability:filter", "ability:solid_rock", "ability:sniper",
      "item:life_orb", "item:choice_band", "item:choice_specs", "item:expert_belt", "item:eviolite",
      "stab", "type_effectiveness", "critical_hit", "spread_move", "protect_reduction",
      "weather:harsh_sunlight", "weather:rain", "weather:sandstorm", "weather:hail", "weather:snow",
      "terrain:electric_terrain", "terrain:psychic_terrain", "terrain:grassy_terrain", "terrain:misty_terrain",
      "screen:reflect", "screen:light_screen", "screen:aurora_veil"};
  if (value == DamageSource::random) return "random";
  RequireEnum(value, DamageSource::technician, DamageSource::aurora_veil);
  return names[static_cast<std::size_t>(value)];
}

std::string_view DamageStageName(DamageStage value) {
  constexpr std::array<std::string_view, 11> names{"base_power", "attack_stat", "defense_stat", "stab", "type_effectiveness",
                                                 "screen", "critical", "spread", "protect", "final_damage", "random"};
  RequireEnum(value, DamageStage::base_power, DamageStage::random);
  return names[static_cast<std::size_t>(value)];
}

DamageResult CalculateDamage(const DamageInput& input, const TypeChartSnapshot& knowledge) {
  ValidatePokemon(input.attacker);
  ValidatePokemon(input.defender);
  ValidatePolicy(input.policy);
  RequireEnum(input.move.type, PokemonType::normal, PokemonType::fairy);
  RequireEnum(input.move.category, DamageCategory::physical, DamageCategory::status);
  RequireEnum(input.weather, DamageWeather::none, DamageWeather::snow);
  RequireEnum(input.terrain, DamageTerrain::none, DamageTerrain::misty);
  if (input.move.category == DamageCategory::status) throw UnsupportedRule("status moves do not deal direct damage");
  if (input.move.power <= 0) throw std::invalid_argument("damaging moves must have positive power");
  Calculation calculation(input);
  calculation.Base();
  calculation.Typing(knowledge);
  calculation.BattleFlags();
  calculation.Environment();
  calculation.FinalEffects();
  return calculation.Finish();
}

} // namespace pbi
