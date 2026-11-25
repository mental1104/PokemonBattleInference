#include "pbi/fixed_battle_snapshot.hpp"
#include <gtest/gtest.h>
#include <limits>

namespace pbi {
namespace {
/// @param id 配置身份；@param speed 速度；@return Ghost目标/Normal招式与1000PP的真实合法配置。
BattlerState SnapshotBattler(std::int64_t id, std::int32_t speed) {
  const PokemonSpec spec{{id, "immune", {50, {PokemonType::ghost}, {100, 100, 100, 100, 100, speed}, DamageAbility::none, DamageItem::none, false, std::nullopt},
      {MoveSpec{{id, "normal", {PokemonType::normal, DamageCategory::physical, 40}, 1000, 0, 100, std::nullopt}}}}};
  return BattlerState{{spec, 100, {MoveSlotState{{id, 1000, 1000}}}, StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @return 只设置全图max_turns=1的正常根节点；即时snapshot按原语义不施加该全图预算。
BattleState SnapshotState() {
  InferenceRulesData rules;
  rules.max_turns = 1;
  rules.damage_policy.random_damage_multipliers = {1.0};
  return BattleState{{SnapshotBattler(1, 100), SnapshotBattler(2, 90), InferenceRules{rules}, 1, {}, BattlePhase::action_selection}};
}
/// @return 唯一实际需要的Normal打Ghost免疫事实，不引入测试用伤害替代器。
TypeChartSnapshot SnapshotKnowledge() { return TypeChartSnapshot{{{PokemonType::normal, PokemonType::ghost, 0}}}; }
} // namespace

/// 每次只调用真实resolver重放已选局部边；第五层身份超过uint64，HP免疫且PP实际消耗。
TEST(FixedBattleSnapshot, RealReplayKeepsLargeIdentityAndIgnoresGlobalGraphBudget) {
  const auto initial = SnapshotState();
  const auto knowledge = SnapshotKnowledge();
  std::vector<ExplorationPathStep> cursor;
  auto result = ExpandFixedBattleSnapshot(initial, knowledge, ActionPolicy::uniform_random, ActionPolicy::uniform_random, cursor);
  for (std::size_t depth = 0; depth < 6; ++depth) {
    ASSERT_EQ(result.projection.transition_groups.size(), 1);
    const auto& group = result.projection.transition_groups.front();
    EXPECT_TRUE(group.expanded);
    ASSERT_EQ(group.outcomes.size(), 1);
    const auto& outcome = group.outcomes.front();
    cursor.push_back({result.projection.node.id, outcome.edge_id, outcome.target_node_id});
    result = ExpandFixedBattleSnapshot(initial, knowledge, ActionPolicy::uniform_random, ActionPolicy::uniform_random, cursor);
  }
  EXPECT_GT(result.projection.node.id.value, Integer{std::numeric_limits<std::uint64_t>::max()});
  EXPECT_EQ(result.projection.node.state.View().turn_number, 7);
  EXPECT_EQ(result.projection.node.state.View().attacker.View().current_hp, 100);
  EXPECT_EQ(result.projection.node.state.View().attacker.MoveSlot(1).View().current_pp, 994);
  EXPECT_EQ(initial.View().attacker.MoveSlot(1).View().current_pp, 1000);
  EXPECT_EQ(result.report_steps.size(), 6);
  EXPECT_EQ(result.projection.cumulative_probability, Rational{1});
}

/// 同一原始配置不能接受伪造的source、不可用局部边或错误目标，失败不回送部分战报。
TEST(FixedBattleSnapshot, RejectsDiscontinuousUnavailableAndWrongTargetCursor) {
  const auto initial = SnapshotState();
  const auto knowledge = SnapshotKnowledge();
  for (const auto& step : std::vector<ExplorationPathStep>{{{1}, {0}, {10000}}, {{0}, {999}, {10000}}, {{0}, {0}, {10001}}}) {
    const std::vector cursor{step};
    EXPECT_THROW(static_cast<void>(ExpandFixedBattleSnapshot(initial, knowledge, ActionPolicy::uniform_random, ActionPolicy::uniform_random, cursor)), std::invalid_argument);
  }
}

/// 协作令牌贯穿snapshot/真实resolver/分组，预取消不得返回根节点的部分成功。
TEST(FixedBattleSnapshot, CancellationIsAtomic) {
  CancellationSource source;
  static_cast<void>(source.Request());
  EXPECT_THROW(static_cast<void>(ExpandFixedBattleSnapshot(SnapshotState(), SnapshotKnowledge(), ActionPolicy::uniform_random,
      ActionPolicy::uniform_random, {}, {}, source.Token())), std::runtime_error);
}
} // namespace pbi
