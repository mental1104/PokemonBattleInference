#include "pbi/damage.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @return 原冻结直接伤害快照，未包含任何实时HP或畏缩状态。
DamageInput Reference() {
  return {{50, {PokemonType::bug, PokemonType::steel}, {177, 182, 120, 67, 100, 85}, DamageAbility::none, DamageItem::none, false, std::nullopt},
      {50, {PokemonType::fairy}, {202, 85, 85, 130, 150, 80}, DamageAbility::none, DamageItem::none, false, std::nullopt},
      {PokemonType::steel, DamageCategory::physical, 40}, DamagePolicyForGeneration(9), DamageWeather::none, DamageTerrain::none, {}, false, false, false, false};
}
/// 显式静态入口保留两侧能力身份，原无动态hook的伤害值与16档不被多重鳞片减半。
TEST(ReferenceStaticDamage, AcceptsExplicitNoDynamicHookWithoutChangingDefault) {
  const TypeChartSnapshot chart{{{PokemonType::steel, PokemonType::fairy, 200}}};
  for (const auto attacker : {DamageAbility::multiscale, DamageAbility::inner_focus}) {
    for (const auto defender : {DamageAbility::multiscale, DamageAbility::inner_focus}) {
      auto input = Reference();
      input.attacker.ability = attacker; input.defender.ability = defender;
      const auto before = input;
      EXPECT_THROW((void)CalculateDamage(input, chart), UnsupportedRule);
      const auto result = CalculateReferenceStaticDamage(input, chart);
      EXPECT_EQ(result.rolls, (std::vector<std::int64_t>{99, 100, 101, 102, 104, 105, 106, 107, 108, 109, 111, 112, 113, 114, 115, 117}));
      EXPECT_EQ(result.trace.size(), 3);
      EXPECT_EQ(input.attacker, before.attacker);
      EXPECT_EQ(input.defender, before.defender);
      EXPECT_EQ(input.policy, before.policy);
    }
  }
}
/// 显式环境、接地、进化/道具和屏障事实不能在静态上下文中被清空或重新推测。
TEST(ReferenceStaticDamage, PreservesAllOtherExplicitStaticFacts) {
  auto input = Reference();
  input.attacker.types = {PokemonType::electric, PokemonType::flying};
  input.attacker.ability = DamageAbility::technician;
  input.attacker.item = DamageItem::life_orb;
  input.attacker.grounding = Grounding::grounded;
  input.defender.types = {PokemonType::water};
  input.defender.ability = DamageAbility::multiscale;
  input.defender.can_evolve = true;
  input.defender.item = DamageItem::eviolite;
  input.move.type = PokemonType::electric;
  input.terrain = DamageTerrain::electric;
  input.defender_side.reflect = true;
  const TypeChartSnapshot chart{{{PokemonType::electric, PokemonType::water, 200}}};
  const auto actual = CalculateReferenceStaticDamage(input, chart);
  auto strict = input;
  strict.defender.ability = DamageAbility::none;
  const auto expected = CalculateDamage(strict, chart);
  EXPECT_EQ(actual.rolls, expected.rolls);
  EXPECT_EQ(actual.base_damage, expected.base_damage);
  ASSERT_EQ(actual.trace.size(), expected.trace.size());
  for (std::size_t index = 0; index < actual.trace.size(); ++index) {
    EXPECT_EQ(actual.trace[index].key, expected.trace[index].key);
    EXPECT_EQ(actual.trace[index].multiplier, expected.trace[index].multiplier);
    EXPECT_EQ(actual.trace[index].reason, expected.trace[index].reason);
  }
}
/// 仅两种已知动态层能力在参考静态无hook；未知枚举、知识缺失和变化招式仍明确拒绝。
TEST(ReferenceStaticDamage, RejectsUnknownAbilityAndUnchangedInvalidInputs) {
  auto input = Reference();
  const TypeChartSnapshot chart{{{PokemonType::steel, PokemonType::fairy, 200}}};
  input.attacker.ability = static_cast<DamageAbility>(99);
  EXPECT_THROW((void)CalculateReferenceStaticDamage(input, chart), UnsupportedRule);
  input.attacker.ability = DamageAbility::inner_focus;
  EXPECT_THROW((void)CalculateReferenceStaticDamage(input, TypeChartSnapshot{{}}), UnsupportedRule);
  input.move.category = DamageCategory::status;
  EXPECT_THROW((void)CalculateReferenceStaticDamage(input, chart), UnsupportedRule);
}
} // namespace
} // namespace pbi
