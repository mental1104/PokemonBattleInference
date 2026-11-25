#include "pbi/configuration_space.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @return 原透明reference最小合法输入；raw repository保守标记不提前修正。
ConfigurationPokemonInput ReferenceInput() {
  ConfigurationPokemonInput input;
  input.pokemon_id = 461; input.name = "weavile"; input.types = {PokemonType::ice};
  input.moves.candidates.push_back({8, "ice-punch", MoveSpec{{8, "Ice Punch", {PokemonType::ice, DamageCategory::physical, 75},
      15, 0, 100, "ice-punch"}}, "ice-punch", ConfigurationSupport::partial, "raw move"});
  input.moves.slot_counts = {1};
  input.stats = {{70, 120, 65, 45, 85, 125}, 50,
      ControlledStatEnumeration{{ConfigurationStatField::hp}, {0}, {ConfigurationNature{}}}, 1};
  input.abilities = {{"pressure", ConfigurationSupport::unsupported, "raw ability"}};
  input.items = {std::nullopt};
  input.factory = ConfigurationEffectFactory::transparent_inference;
  input.repository_mode = ConfigurationRepositoryMode::factory_reconciled;
  return input;
}
/// 原provider接受overall supported中性占位；严格任务同事实仍拒绝真实行为缺口。
TEST(ConfigurationContext, ReferencePressureDoesNotRelaxStrictAdmission) {
  const auto input = ReferenceInput();
  const auto result = GeneratePokemonConfigurationSpace(input);
  ASSERT_EQ(result.classes.size(), 1);
  EXPECT_EQ(result.classes.front().ability, "pressure");
  EXPECT_EQ(result.raw_configuration_count, 1);
  const auto strict = DescribeConfigurationAdmission({ConfigurationEffectSource::ability, "pressure", "pressure", "raw ability",
      true, false, input.factory, input.repository_mode});
  EXPECT_FALSE(strict.Selectable());
  EXPECT_EQ(strict.status, ConfigurationAdmissionStatus::partial);
  EXPECT_EQ(strict.missing_mechanism_identifiers, (std::vector<std::string>{"real_ability_behavior"}));
}
/// 显式新context返回原profile.name诊断；不因核心支持某回合效果而放宽原provider。
TEST(ConfigurationContext, PartialInnerFocusStillHasNoReferenceCandidates) {
  auto input = ReferenceInput(); input.abilities = {{"inner-focus", ConfigurationSupport::supported, "raw ability"}};
  try { (void)GeneratePokemonConfigurationSpace(input); FAIL() << "partial factory must be excluded"; }
  catch (const std::invalid_argument& error) {
    EXPECT_STREQ(error.what(), "dimension 'ability' has no supported candidates for weavile");
  }
}
/// 工厂和repository是两个独立轴；仅透明工厂不能自动提升raw不支持候选。
TEST(ConfigurationContext, TransparentRawDoesNotSilentlyReconcileRepository) {
  auto input = ReferenceInput();
  input.moves.candidates.front().support = ConfigurationSupport::supported;
  input.repository_mode = ConfigurationRepositoryMode::raw;
  EXPECT_THROW((void)GeneratePokemonConfigurationSpace(input), std::invalid_argument);
  input.abilities.front().support = ConfigurationSupport::supported;
  EXPECT_EQ(GeneratePokemonConfigurationSpace(input).classes.size(), 1);
  input.factory = ConfigurationEffectFactory::standard;
  EXPECT_THROW((void)GeneratePokemonConfigurationSpace(input), std::invalid_argument);
}
} // namespace
} // namespace pbi
