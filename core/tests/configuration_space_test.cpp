#include "pbi/configuration_space.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @return 包含同规范特性重复projection和两个道具的真实单侧命令。
ConfigurationPokemonInput SideInput() {
  ConfigurationPokemonInput input;
  input.pokemon_id = 149;
  input.name = "dragonite";
  input.types = {PokemonType::dragon, PokemonType::flying};
  input.moves.candidates.push_back({245, "extreme-speed", MoveSpec{{245, "Extreme Speed",
      {PokemonType::normal, DamageCategory::physical, 80}, 5, 2, 100, std::nullopt}}, std::nullopt});
  input.stats = {{91, 134, 95, 100, 100, 80}, 50,
      ControlledStatEnumeration{{ConfigurationStatField::hp}, {0, 1, 2, 3, 4}, {ConfigurationNature{}}}, 10};
  input.abilities = {{"multiscale"}, {"Multiscale"}, {"pressure"}};
  input.items = {"life-orb", std::nullopt};
  return input;
}
/// 先过滤与归并各维度，再按原始成员计数计算单侧保护，不以类数量冒充原始空间。
TEST(ConfigurationSpace, GeneratesLegalDimensionsAndConservesRawMembers) {
  auto input = SideInput();
  const auto result = GeneratePokemonConfigurationSpace(input);
  ASSERT_EQ(result.classes.size(), 4);
  EXPECT_EQ(result.raw_configuration_count, 20);
  ASSERT_EQ(result.coverage.size(), 6);
  EXPECT_FALSE(result.coverage[3].candidate.included);
  EXPECT_EQ(result.coverage[4].candidate.identifier, "none");
  Integer count{0};
  for (const auto& value : result.classes) count += value.member_count;
  EXPECT_EQ(count, result.raw_configuration_count);
  input.max_raw_configurations = 19;
  EXPECT_THROW((void)GeneratePokemonConfigurationSpace(input), std::length_error);
}
/// 原始均匀和等价类均匀是不同覆盖假设，均精确守恒但不能混用分母。
TEST(ConfigurationSpace, ComputesBothExactWeightAssumptions) {
  auto first = SideInput(), second = SideInput();
  const auto raw = GenerateConfigurationSpace(first, second);
  const auto classes = GenerateConfigurationSpace(first, second, ConfigurationWeightAssumption::uniform_equivalence_class);
  ASSERT_EQ(raw.pairs.size(), 16);
  ASSERT_EQ(classes.pairs.size(), 16);
  EXPECT_EQ(raw.raw_pair_count, 400);
  Rational total{0};
  bool nonuniform = false;
  for (std::size_t index = 0; index < raw.pairs.size(); ++index) {
    total += raw.pairs[index].weight;
    EXPECT_EQ(classes.pairs[index].weight, (Rational{1, 16}));
    if (raw.pairs[index].weight != classes.pairs[index].weight) nonuniform = true;
  }
  EXPECT_TRUE(nonuniform);
  EXPECT_EQ(total, Rational{1});
  EXPECT_THROW((void)GenerateConfigurationSpace(first, second, ConfigurationWeightAssumption::uniform_raw_configuration, 399), std::length_error);
}
/// 不同规则轴、空支持维度和已取消请求整体失败，永不返回缩减分母。
TEST(ConfigurationSpace, RejectsMismatchedRulesAndEmptySupportedDimensions) {
  auto first = SideInput(), second = SideInput();
  second.version_group_id = 31;
  EXPECT_THROW((void)GenerateConfigurationSpace(first, second), std::invalid_argument);
  first.abilities = {{"inner-focus"}};
  EXPECT_THROW((void)GeneratePokemonConfigurationSpace(first), std::invalid_argument);
  CancellationSource cancellation;
  EXPECT_TRUE(cancellation.Request());
  EXPECT_THROW((void)GeneratePokemonConfigurationSpace(SideInput(), cancellation.Token()), std::runtime_error);
}
} // namespace
} // namespace pbi
