#include "pbi/actions.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param id 不变宝可梦 ID；@return 两个槽位身份明确、优先级不同的只读测试战斗方。
BattlerState ActionBattler(std::int64_t id) {
  const PokemonSpec spec{{id, "test", {50, {PokemonType::normal}, {100, 100, 100, 100, 100, 100},
      DamageAbility::none, DamageItem::choice_band, false, std::nullopt},
      {MoveSpec{{1, "first", {PokemonType::normal, DamageCategory::physical, 40}, 5, 1, 100, std::nullopt}},
       MoveSpec{{2, "second", {PokemonType::normal, DamageCategory::physical, 50}, 5, -1, 100, std::nullopt}}}}};
  return BattlerState{{spec, 100, {MoveSlotState{{1, 5, 5, false, false, 91}}, MoveSlotState{{2, 5, 5, false, false, 92}}},
      StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @return 满 HP/PP 的稳定双侧战斗节点。
BattleState ActionState() { return BattleState{{ActionBattler(1), ActionBattler(2), InferenceRules{}, 1, {}, BattlePhase::action_selection}}; }
} // namespace

/// 使用运行时槽位顺序与身份，PP/禁用/讲究锁招失效都真实影响合法集合。
TEST(Actions, LegalSlotsPpAndChoiceLock) {
  const auto state = ActionState();
  const auto actions = GenerateLegalActions(state, BattleSide::attacker);
  ASSERT_EQ(actions.size(), 2);
  EXPECT_EQ(std::get<UseMoveAction>(actions[0]), (UseMoveAction{BattleSide::attacker, 1, 1, 91}));
  EXPECT_EQ(std::get<UseMoveAction>(actions[1]), (UseMoveAction{BattleSide::attacker, 2, -1, 92}));
  const auto locked = state.View().attacker.WithChoiceLock(2);
  auto changed = state.WithBattler(BattleSide::attacker, locked);
  EXPECT_EQ(GenerateLegalActions(changed, BattleSide::attacker).size(), 1);
  changed = changed.WithBattler(BattleSide::attacker, locked.WithMoveSlot(locked.MoveSlot(2).WithCurrentPp(0).WithLocked(true)));
  EXPECT_TRUE(std::holds_alternative<StruggleAction>(GenerateLegalActions(changed, BattleSide::attacker).front()));
  const auto first = state.View().attacker;
  changed = state.WithBattler(BattleSide::attacker, first.WithMoveSlot(first.MoveSlot(1).WithDisabled(true)));
  EXPECT_EQ(std::get<UseMoveAction>(GenerateLegalActions(changed, BattleSide::attacker).front()).move_id, 2);
  changed = state.WithBattler(BattleSide::attacker, first.WithCurrentHp(0));
  EXPECT_TRUE(std::holds_alternative<PassAction>(GenerateLegalActions(changed, BattleSide::attacker).front()));
  EXPECT_EQ(state.View().attacker.MoveSlot(2).View().current_pp, 5);
}

/// 玩家策略与战斗随机概率分离；重复、非法、零权重和非归一分布显式失败。
TEST(Actions, ExactPoliciesAndDistributionValidation) {
  const auto actions = GenerateLegalActions(ActionState(), BattleSide::defender);
  const auto uniform = SelectActions(actions, ActionPolicy::uniform_random);
  ASSERT_EQ(uniform.size(), 2); EXPECT_EQ(uniform[0].probability, (Rational{1, 2}));
  EXPECT_EQ(uniform[0].action, actions[0]); EXPECT_EQ(uniform[1].action, actions[1]);
  const auto first = SelectActions(actions, ActionPolicy::first_legal_action);
  ASSERT_EQ(first.size(), 1); EXPECT_EQ(first[0].probability, Rational{1});
  EXPECT_EQ(ActionSide(first[0].action), BattleSide::defender);
  const std::vector<ActionSelection> duplicate{{actions[0], Rational{1, 2}}, {actions[0], Rational{1, 2}}};
  EXPECT_THROW(ValidateActionDistribution(duplicate, actions), std::invalid_argument);
  const std::vector<ActionSelection> incomplete{{actions[0], Rational{1, 2}}};
  EXPECT_THROW(ValidateActionDistribution(incomplete, actions), std::invalid_argument);
  const std::vector<ActionSelection> illegal{{StruggleAction{BattleSide::defender}, Rational{1}}};
  EXPECT_THROW(ValidateActionDistribution(illegal, actions), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(SelectActions({}, ActionPolicy::uniform_random)), std::invalid_argument);
  EXPECT_EQ(std::get<UseMoveAction>(ValidateAction(UseMoveAction{BattleSide::attacker, 8})).slot_id, 8);
  EXPECT_THROW(static_cast<void>(ValidateAction(UseMoveAction{BattleSide::attacker, 0})), std::invalid_argument);
}
} // namespace pbi
