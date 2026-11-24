#include "pbi/configuration_moves.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param id 合法唯一 ID；@param power 基础威力；@return 不含附加机制的完整合法候选。
ConfigurationMoveCandidate Candidate(std::int64_t id, std::int32_t power = 40) {
  return {id, std::to_string(id), MoveSpec{{id, "candidate", {PokemonType::normal, DamageCategory::physical, power}, 10, 0, 100, std::nullopt}}, std::nullopt};
}
/// 默认候选五招只枚举无序四招，显式 1/2 槽保持按槽数和 ID 的组合顺序。
TEST(ConfigurationMoves, UsesCanonicalUnorderedFourMoveSets) {
  ConfigurationMoveInput input;
  for (int id = 1; id <= 5; ++id) input.candidates.push_back(Candidate(id));
  const auto result = EnumerateConfigurationMoves(input);
  ASSERT_EQ(result.classes.size(), 5);
  EXPECT_EQ(result.raw_combination_count, 5);
  EXPECT_EQ(result.classes.front().moves.size(), 4);
  input.slot_counts = {2, 1};
  EXPECT_EQ(EnumerateConfigurationMoves(input).raw_combination_count, 15);
}
/// 相同行为 projection 归并为乘数，不同 projection 的同 ID 不能占两个槽。
TEST(ConfigurationMoves, CountsDuplicateProjectionsWithoutDuplicateMoveIds) {
  ConfigurationMoveInput input;
  input.candidates = {Candidate(1), Candidate(1), Candidate(1, 80), Candidate(2)};
  input.slot_counts = {2};
  const auto result = EnumerateConfigurationMoves(input);
  ASSERT_EQ(result.classes.size(), 2);
  EXPECT_EQ(result.raw_combination_count, 3);
  EXPECT_EQ(result.classes.front().member_count, 2);
  input.max_raw_combinations = 2;
  EXPECT_THROW((void)EnumerateConfigurationMoves(input), std::length_error);
}
/// 原 provider 区分命令排除、repository部分支持和factory缺失，不伪造可执行状态招式。
TEST(ConfigurationMoves, PreservesCoverageAndSupportedOnlyFiltering) {
  auto missing = Candidate(2);
  missing.effect_identifier = "unimplemented";
  auto partial = Candidate(3);
  partial.support = ConfigurationSupport::partial;
  auto status = Candidate(4);
  status.move = MoveSpec{{4, "status", {PokemonType::normal, DamageCategory::status, 0}, 10, 0, 100, std::nullopt}};
  ConfigurationMoveInput input{{Candidate(1), missing, partial, status, Candidate(5)}, {1, 2, 3, 4}, {1}};
  const auto result = EnumerateConfigurationMoves(input);
  ASSERT_EQ(result.classes.size(), 1);
  ASSERT_EQ(result.coverage.size(), 5);
  EXPECT_TRUE(result.coverage[0].included);
  EXPECT_EQ(result.coverage[1].factory_status, ConfigurationEffectStatus::unsupported);
  EXPECT_EQ(result.coverage[2].support, ConfigurationSupport::partial);
  EXPECT_FALSE(result.coverage[3].included);
  EXPECT_FALSE(result.coverage[4].factory_status);
}
/// 原 generator允许overall supported的招式；严格任务仍可独立读取缺失子能力拒绝。
TEST(ConfigurationMoves, KeepsFactoryCapabilityAndAdmissionDistinct) {
  auto move = Candidate(8);
  move.effect_identifier = "Ice Punch";
  const auto space = EnumerateConfigurationMoves({{move}, {}, {1}});
  ASSERT_EQ(space.classes.size(), 1);
  EXPECT_EQ(space.classes.front().moves.front().effect_identifier, "ice_punch");
  const auto coverage = DescribeConfigurationEffect(ConfigurationEffectSource::move, "ice-punch");
  EXPECT_EQ(coverage.status, ConfigurationEffectStatus::supported);
  EXPECT_EQ(coverage.missing_capabilities, (std::vector<std::string>{"freeze_secondary_effect"}));
  EXPECT_EQ(DescribeConfigurationEffect(ConfigurationEffectSource::ability, "inner_focus").status, ConfigurationEffectStatus::partial);
  EXPECT_EQ(DescribeConfigurationEffect(ConfigurationEffectSource::item, "life_orb").missing_capabilities.size(), 0);
}
} // namespace
} // namespace pbi
