#include "pbi/configuration_spread_search.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @return 与原25项完整知识相同的倍率，算法仍从注入数据而非测试预选候选计算。
std::vector<ConfigurationSearchNature> Natures() {
  return {{"hardy", "Hardy", {{1,1,1,1,1}}}, {"lonely", "Lonely", {{1.1,.9,1,1,1}}},
      {"brave", "Brave", {{1.1,1,1,1,.9}}}, {"adamant", "Adamant", {{1.1,1,.9,1,1}}},
      {"naughty", "Naughty", {{1.1,1,1,.9,1}}}, {"bold", "Bold", {{.9,1.1,1,1,1}}},
      {"docile", "Docile", {{1,1,1,1,1}}}, {"relaxed", "Relaxed", {{1,1.1,1,1,.9}}},
      {"impish", "Impish", {{1,1.1,.9,1,1}}}, {"lax", "Lax", {{1,1.1,1,.9,1}}},
      {"timid", "Timid", {{.9,1,1,1,1.1}}}, {"hasty", "Hasty", {{1,.9,1,1,1.1}}},
      {"serious", "Serious", {{1,1,1,1,1}}}, {"jolly", "Jolly", {{1,1,.9,1,1.1}}},
      {"naive", "Naive", {{1,1,1,.9,1.1}}}, {"modest", "Modest", {{.9,1,1.1,1,1}}},
      {"mild", "Mild", {{1,.9,1.1,1,1}}}, {"quiet", "Quiet", {{1,1,1.1,1,.9}}},
      {"bashful", "Bashful", {{1,1,1,1,1}}}, {"rash", "Rash", {{1,1,1.1,.9,1}}},
      {"calm", "Calm", {{.9,1,1,1.1,1}}}, {"gentle", "Gentle", {{1,.9,1,1.1,1}}},
      {"sassy", "Sassy", {{1,1,1,1.1,.9}}}, {"careful", "Careful", {{1,1,.9,1.1,1}}},
      {"quirky", "Quirky", {{1,1,1,1,1}}}};
}
/// @return 只提供固定subject/完整性格知识，未提供任何预构造候选。
ConfigurationSpreadSearchInput Input() {
  return {{{100, 100, 100, 100, 100, 100}, {PokemonType::normal}}, {}, {}, Natures(), 3};
}
/// @return 与原静态求值共用的单档真实伤害链及完整所需相克知识。
ConfigurationGoalEvaluator Evaluator() {
  auto policy = DamagePolicyForGeneration(9);
  policy.random_damage_multipliers = {1};
  return {std::move(policy), TypeChartSnapshot{{{PokemonType::normal, PokemonType::normal, 100}}}};
}
/// 纯速度必须真正反推性格/EV/IV区间，而非把预设改名；同速目标要求严格超过。
TEST(ConfigurationSpreadSearch, SearchesSpeedNatureAndIndependentIvRange) {
  auto input = Input();
  input.speed_goals = {{"speed", 120}};
  input.max_candidates = 1;
  const auto result = SearchConfigurationSpreads(input, Evaluator());
  ASSERT_EQ(result.candidates.size(), 1);
  const auto& candidate = result.candidates[0];
  EXPECT_EQ(candidate.nature_id, "jolly");
  EXPECT_EQ(candidate.candidate_id, "spread-1-jolly-0-0-0-0-0-0");
  EXPECT_EQ(candidate.stats.speed, 132);
  EXPECT_EQ(candidate.iv_ranges[5].minimum, 10);
  EXPECT_EQ(candidate.iv_ranges[5].maximum, 31);
  ASSERT_EQ(candidate.nature_options.size(), 4);
  EXPECT_EQ(candidate.nature_options[0].identifier, "jolly");
  EXPECT_EQ(candidate.nature_options[1].identifier, "timid");
}
/// HP与防御权衡由网格/二分实际搜索，全部代表都满足510总量并保留原独立范围。
TEST(ConfigurationSpreadSearch, SearchesDefensiveTradeoffsAndValidRanges) {
  auto input = Input();
  input.goals = {{"defense", ConfigurationGoalKind::defense, {{PokemonType::normal}, {100, 200, 100, 100, 100, 100}},
      {PokemonType::normal, DamageCategory::physical, 80}, 2, std::nullopt}};
  const auto result = SearchConfigurationSpreads(input, Evaluator());
  ASSERT_FALSE(result.candidates.empty());
  for (const auto& candidate : result.candidates) {
    const auto& value = candidate.evs;
    EXPECT_LE(value.hp + value.attack + value.defense + value.special_attack + value.special_defense + value.speed, 510);
    ASSERT_EQ(candidate.goals.size(), 1);
    EXPECT_TRUE(candidate.goals[0].satisfied);
    EXPECT_EQ(candidate.evs.speed, 0);
    EXPECT_EQ(candidate.ivs.speed, 31);
    EXPECT_EQ(candidate.iv_ranges[5].minimum, 0);
    EXPECT_LE(candidate.ev_ranges[2].minimum, value.defense);
    EXPECT_GE(candidate.ev_ranges[2].maximum, value.defense);
  }
}
/// 无解时返回原首性格零EV/6V基线，而非为空概率或偷偷放宽速度线。
TEST(ConfigurationSpreadSearch, ReturnsOriginalUnreachableBaselineEvidence) {
  auto input = Input();
  input.speed_goals = {{"impossible-speed", 1000000}};
  const auto result = SearchConfigurationSpreads(input, Evaluator());
  EXPECT_FALSE(result.Reachable());
  ASSERT_EQ(result.rejected_speed_goals.size(), 1);
  EXPECT_EQ(result.rejected_speed_goals[0].subject_speed, 120);
  EXPECT_FALSE(result.rejected_speed_goals[0].satisfied);
}
/// 残缺知识、跨类重复目标与已取消请求整体失败，不返回貌似完整的缩减空间。
TEST(ConfigurationSpreadSearch, RejectsIncompleteNatureKnowledgeAndCancellation) {
  auto input = Input();
  input.speed_goals = {{"speed", 120}};
  input.natures.pop_back();
  EXPECT_THROW((void)SearchConfigurationSpreads(input, Evaluator()), std::invalid_argument);
  CancellationSource stop;
  EXPECT_TRUE(stop.Request());
  EXPECT_THROW((void)SearchConfigurationSpreads(Input(), Evaluator(), stop.Token()), std::runtime_error);
  input = Input();
  input.speed_goals = {{"same", 120}, {"same", 130}};
  EXPECT_THROW((void)SearchConfigurationSpreads(input, Evaluator()), std::invalid_argument);
}
} // namespace
} // namespace pbi
