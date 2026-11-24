#include "pbi/legacy_damage.hpp"
#include <gtest/gtest.h>
#include <limits>

namespace pbi {
namespace {
/// @return 只用于验证原binary64公式的固定构造事实，不依赖数据库或现代能力算法。
LegacyPokemonInput Pokemon() { return {53, {100,100,100,100,100,100}, {2,2,2,2,2,2}, LegacyNature::adamant, {PokemonType::normal}}; }
} // namespace

/// 原EV/4不先取整，性格前也不先floor；验证与现代StatInput不同的可观察旧行为。
TEST(LegacyDamage, FractionalEvAndQuietNature) {
  auto input = Pokemon();
  const auto result = CalculateLegacyStats(input);
  EXPECT_EQ(result[0], 185);
  EXPECT_EQ(result[1], 140);
  input.level = 100;
  input.nature = LegacyNature::quiet;
  const auto quiet = CalculateLegacyStats(input);
  EXPECT_EQ(quiet[3], 260);
  EXPECT_EQ(quiet[5], 236);
  input.basepoint.push_back(10000);
  EXPECT_EQ(CalculateLegacyStats(input), quiet);
  input.basepoint.resize(5);
  EXPECT_THROW(static_cast<void>(CalculateLegacyStats(input)), std::invalid_argument);
}

/// 原随机上下界与免疫必须进入真实链，非法随机/缺知识不能返回默认中性成功。
TEST(LegacyDamage, RandomBoundaryImmunityAndFailures) {
  LegacyDamageInput input{Pokemon(), Pokemon(), {80, PokemonType::normal, DamageCategory::physical}, 0};
  const TypeChartSnapshot chart{{{PokemonType::normal, PokemonType::normal, 100}, {PokemonType::normal, PokemonType::ghost, 0}}};
  EXPECT_EQ(CalculateLegacyDamage(input, chart).random_multiplier, 0.85);
  input.random_unit = 1;
  const auto upper = CalculateLegacyDamage(input, chart);
  EXPECT_EQ(upper.random_multiplier, 1);
  EXPECT_EQ(upper.random_damage, upper.max_damage);
  input.defender.types = {PokemonType::ghost};
  const auto immune = CalculateLegacyDamage(input, chart);
  EXPECT_EQ(immune.min_damage, 0);
  EXPECT_EQ(immune.max_damage_percent, 0);
  input.random_unit = std::numeric_limits<double>::quiet_NaN();
  EXPECT_THROW(static_cast<void>(CalculateLegacyDamage(input, chart)), std::invalid_argument);
}
} // namespace pbi
