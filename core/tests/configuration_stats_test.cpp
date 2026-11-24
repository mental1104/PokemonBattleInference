#include "pbi/configuration_stats.hpp"
#include <gtest/gtest.h>
#include <limits>

namespace pbi {
namespace {
/// @return 同一基础种族值，便于独立验证 EV 总量和低等级能力等价类。
ConfigurationStatInput ControlledInput() {
  return {{80, 80, 80, 80, 80, 80}, 50,
          ControlledStatEnumeration{{ConfigurationStatField::hp, ConfigurationStatField::attack,
                                    ConfigurationStatField::defense}, {0, 252}, {ConfigurationNature{}}}, 100};
}
/// 验证 3*252 被过滤，且原始成员数没有把非法投入计入分母。
TEST(ConfigurationStats, FiltersTotalEvsBeforeCounting) {
  const auto result = EnumerateConfigurationStats(ControlledInput());
  EXPECT_EQ(result.raw_profile_count, 7);
  EXPECT_EQ(result.classes.size(), 7);
  EXPECT_EQ(result.classes.front().representative.evs, (BattleStats{}));
}
/// 验证最终能力归并保留输入首代表，预算仍计算归并前有效成员。
TEST(ConfigurationStats, MergesRoundedStatsButEnforcesRawBudget) {
  auto input = ControlledInput();
  input.level = 1;
  input.enumeration = ControlledStatEnumeration{{ConfigurationStatField::attack}, {3, 0, 1, 2}, {ConfigurationNature{}}};
  input.max_raw_profiles = 4;
  const auto result = EnumerateConfigurationStats(input);
  ASSERT_EQ(result.classes.size(), 1);
  EXPECT_EQ(result.raw_profile_count, 4);
  EXPECT_EQ(result.classes.front().member_count, 4);
  EXPECT_EQ(result.classes.front().representative.evs.attack, 0);
  input.max_raw_profiles = 3;
  EXPECT_THROW((void)EnumerateConfigurationStats(input), std::length_error);
}
/// 验证原预设单项 1.1 不会被强制改成另一项 0.9，且自定义 IV 生效。
TEST(ConfigurationStats, PreservesFullNatureSnapshotAndFirstPreset) {
  auto input = ControlledInput();
  ConfigurationStatProfile profile;
  profile.nature.multipliers[0] = 1.1;
  profile.ivs.speed = 0;
  input.enumeration = PresetStatEnumeration{{{profile, "first"}, {profile, "second"}}};
  const auto result = EnumerateConfigurationStats(input);
  ASSERT_EQ(result.classes.size(), 1);
  EXPECT_EQ(result.classes.front().label, "first");
  EXPECT_EQ(result.classes.front().member_count, 2);
  EXPECT_EQ(result.classes.front().actual.attack, 110);
  EXPECT_EQ(result.classes.front().actual.special_attack, 100);
  EXPECT_EQ(result.classes.front().actual.speed, 85);
}
/// 验证重复命令不静默去重、空维度失败和取消不返回部分空间。
TEST(ConfigurationStats, RejectsInvalidAxesAndHonorsCancellation) {
  auto input = ControlledInput();
  input.enumeration = ControlledStatEnumeration{{ConfigurationStatField::attack, ConfigurationStatField::attack}, {0}, {ConfigurationNature{}}};
  EXPECT_THROW((void)EnumerateConfigurationStats(input), std::invalid_argument);
  input.enumeration = PresetStatEnumeration{};
  EXPECT_THROW((void)EnumerateConfigurationStats(input), std::invalid_argument);
  CancellationSource source;
  EXPECT_TRUE(source.Request());
  EXPECT_THROW((void)EnumerateConfigurationStats(ControlledInput(), source.Token()), std::runtime_error);
}
/// 任意有限倍率保留原行为，非有限倍率及显式输出边界必须拒绝，不能静默截断。
TEST(ConfigurationStats, RejectsNonfiniteAndOverflowedNatureResults) {
  ConfigurationStatProfile profile;
  profile.nature.multipliers[0] = std::numeric_limits<double>::infinity();
  EXPECT_THROW((void)CalculateConfigurationStats({80, 80, 80, 80, 80, 80}, 50, profile), std::invalid_argument);
  profile.nature.multipliers[0] = 1e12;
  EXPECT_THROW((void)CalculateConfigurationStats({80, 80, 80, 80, 80, 80}, 50, profile), std::overflow_error);
}
} // namespace
} // namespace pbi
