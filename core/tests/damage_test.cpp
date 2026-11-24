#include "pbi/damage.hpp"
#include <gtest/gtest.h>
#include <limits>

namespace pbi {
namespace {
/// @return 与现有 Python 冻结样本一致的直接伤害输入，调用者独占所有字段。
DamageInput Reference() {
  return {{50, {PokemonType::bug, PokemonType::steel}, {177, 182, 120, 67, 100, 85},
           DamageAbility::none, DamageItem::none, false, std::nullopt},
          {50, {PokemonType::fairy}, {202, 85, 85, 130, 150, 80},
           DamageAbility::none, DamageItem::none, false, std::nullopt},
          {PokemonType::steel, DamageCategory::physical, 40}, DamagePolicyForGeneration(9),
          DamageWeather::none, DamageTerrain::none, {}, false, false, false, false};
}
} // namespace

/// 固定档位、精确 KO 与知识注入共同验证真实领域入口；不需要数据库。
TEST(Damage, ReferenceAndImmutableInput) {
  const auto input = Reference();
  const TypeChartSnapshot chart{{{PokemonType::steel, PokemonType::fairy, 200}}};
  const auto result = CalculateDamage(input, chart);
  EXPECT_EQ(result.base_damage, 39);
  EXPECT_EQ(result.rolls, (std::vector<std::int64_t>{99, 100, 101, 102, 104, 105, 106, 107,
                                                   108, 109, 111, 112, 113, 114, 115, 117}));
  EXPECT_EQ(EstimateKoChance(result.rolls, result.defender_hp).two_hit, Rational{123} / 128);
  ASSERT_EQ(result.trace.size(), 3);
  EXPECT_EQ(result.trace.front().key, DamageSource::stab);
  EXPECT_EQ(result.trace.back().stage, DamageStage::random);
  EXPECT_EQ(input.attacker.stats.attack, 182);
  EXPECT_EQ(input.policy.random_damage_multipliers.size(), 16);
}

/// 屏障按旧合同叠加；会心跳过屏障，并以狙击手改写来源而非增加第二个会心阶段。
TEST(Damage, OrderedScreensCriticalAndCustomRandom) {
  auto input = Reference();
  input.defender_side = {true, true, true};
  input.policy.random_damage_multipliers = {1.0, 0.0, 0.5};
  const TypeChartSnapshot chart{{{PokemonType::steel, PokemonType::fairy, 200}}};
  const auto screened = CalculateDamage(input, chart);
  EXPECT_EQ(screened.rolls, (std::vector<std::int64_t>{29, 0, 14}));
  ASSERT_EQ(screened.trace.size(), 5);
  EXPECT_EQ(screened.trace[2].key, DamageSource::reflect);
  EXPECT_EQ(screened.trace[3].key, DamageSource::aurora_veil);
  EXPECT_EQ(screened.trace.back().min_multiplier, 1.0);
  EXPECT_EQ(screened.trace.back().max_multiplier, 0.5);
  input.critical = true;
  input.attacker.ability = DamageAbility::sniper;
  const auto critical = CalculateDamage(input, chart);
  EXPECT_EQ(critical.rolls, (std::vector<std::int64_t>{263, 0, 131}));
  ASSERT_EQ(critical.trace.size(), 4);
  EXPECT_EQ(critical.trace[2].key, DamageSource::critical_hit);
  EXPECT_EQ(critical.trace[2].source, DamageSource::sniper);
}

/// 未知知识/动态规则必须显式失败，非法倍率与整数预算也不能返回伪伤害。
TEST(Damage, ExplicitFailuresAndNumericBudgets) {
  auto input = Reference();
  const TypeChartSnapshot chart{{{PokemonType::steel, PokemonType::fairy, 200}}};
  EXPECT_THROW(static_cast<void>(CalculateDamage(input, TypeChartSnapshot{{}})), UnsupportedDamageRule);
  EXPECT_THROW(static_cast<void>(TypeChartSnapshot({{PokemonType::steel, PokemonType::fairy, 100},
                                                    {PokemonType::steel, PokemonType::fairy, 200}})), std::invalid_argument);
  input.move.category = DamageCategory::status;
  EXPECT_THROW(static_cast<void>(CalculateDamage(input, chart)), UnsupportedDamageRule);
  input.move.category = DamageCategory::physical;
  input.attacker.ability = static_cast<DamageAbility>(99);
  EXPECT_THROW(static_cast<void>(CalculateDamage(input, chart)), UnsupportedDamageRule);
  input.attacker.ability = DamageAbility::none;
  input.policy.random_damage_multipliers = {};
  EXPECT_THROW(static_cast<void>(CalculateDamage(input, chart)), std::invalid_argument);
  input.policy.random_damage_multipliers = {-1.0};
  EXPECT_THROW(static_cast<void>(CalculateDamage(input, chart)), std::invalid_argument);
  input.policy.random_damage_multipliers = {std::numeric_limits<double>::infinity()};
  EXPECT_THROW(static_cast<void>(CalculateDamage(input, chart)), std::invalid_argument);
  input.policy.random_damage_multipliers = {1e100};
  EXPECT_THROW(static_cast<void>(CalculateDamage(input, chart)), std::overflow_error);
  input.policy.random_damage_multipliers = {1.0};
  input.defender.stats.defense = 0;
  EXPECT_THROW(static_cast<void>(CalculateDamage(input, chart)), std::invalid_argument);
}

/// 原 profile 只声明已建模的代际差异，版本组映射保持身份且拒绝未知值。
TEST(Damage, GenerationAndVersionGroupProfiles) {
  for (int generation = 1; generation <= 9; ++generation) {
    const auto policy = DamagePolicyForGeneration(generation);
    EXPECT_EQ(policy.critical_hit_multiplier, generation <= 5 ? 2.0 : 1.5);
    EXPECT_EQ(policy.terrain_boost_multiplier, generation <= 5 ? 1.0 : generation <= 7 ? 1.5 : 1.3);
    EXPECT_EQ(policy.sandstorm_rock_spdef_multiplier.has_value(), generation >= 4);
    EXPECT_EQ(policy.snow_ice_defense_multiplier.has_value(), generation == 9);
  }
  constexpr std::array expected{1, 1, 2, 2, 3, 3, 3, 4, 4, 4, 5, 3, 3, 5, 6, 6,
                                7, 7, 7, 8, 8, 8, 8, 8, 9, 9, 9, 1, 1, 9, 9};
  for (std::size_t index = 0; index < expected.size(); ++index) {
    EXPECT_EQ(GenerationForVersionGroup(static_cast<std::int32_t>(index + 1)), expected[index]);
  }
  EXPECT_THROW(static_cast<void>(GenerationForVersionGroup(32)), UnsupportedDamageRule);
  EXPECT_THROW(static_cast<void>(DamagePolicyForGeneration(0)), UnsupportedDamageRule);
}
} // namespace pbi
