#include "pbi/state.hpp"
#include <gtest/gtest.h>
#include <limits>
#include <type_traits>
#include <unordered_set>

namespace pbi {
namespace {
/// @param id 不变宝可梦 ID；@param name 展示名称；@return 四槽、讲究头带的测试配置。
PokemonSpec Spec(std::int64_t id, std::string name) {
  return PokemonSpec{{id, std::move(name),
      {50, {PokemonType::bug, PokemonType::steel}, {177, 200, 120, 67, 100, 85}, DamageAbility::none, DamageItem::choice_band, false, std::nullopt},
      {MoveSpec{{1, "bullet-punch", {PokemonType::steel, DamageCategory::physical, 40}, 30, 1, 100, std::nullopt}},
       MoveSpec{{2, "brick-break", {PokemonType::fighting, DamageCategory::physical, 75}, 15, 0, 100, " Brick-Break "}},
       MoveSpec{{3, "special", {PokemonType::bug, DamageCategory::special, 80}, 10, 0, std::nullopt, std::nullopt}},
       MoveSpec{{4, "swords-dance", {PokemonType::normal, DamageCategory::status, 0}, 20, 0, 100, std::nullopt}}}}};
}
/// @param spec 转移拥有的配置；@return 四招满 PP、满 HP 的动态测试节点。
BattlerState Battler(PokemonSpec spec) {
  std::vector<MoveSlotState> slots;
  for (const auto& move : spec.View().moves) slots.emplace_back(MoveSlotData{move.View().move_id, move.View().max_pp, move.View().max_pp});
  const auto hp = spec.View().pokemon.stats.hp;
  return BattlerState{{std::move(spec), hp, std::move(slots), StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @return 两侧 ID 可区分、具有全部原状态字段的只读测试局面。
BattleState Reference() {
  return BattleState{{Battler(Spec(212, "scizor")), Battler(Spec(700, "sylveon")), InferenceRules{}, 1, {}, BattlePhase::action_selection}};
}
} // namespace

/// 状态值规范化、不可变替换和原 switch-out 清理范围必须同时保留。
TEST(Status, CanonicalValuesAndImmutableUpdates) {
  const CombatantStatus original{MajorStatus{SleepStatus{2}}, {FlinchStatus{}, ConfusionStatus{3}, InfatuationStatus{"target"}, FlinchStatus{}}};
  const CombatantStatus reordered{MajorStatus{SleepStatus{2}}, {InfatuationStatus{"target"}, ConfusionStatus{3}, FlinchStatus{}}};
  EXPECT_EQ(original, reordered);
  const auto replaced = original.AddVolatile(ConfusionStatus{1});
  EXPECT_EQ(std::get<ConfusionStatus>(original.Volatile().front()).turns_remaining, 3);
  EXPECT_EQ(std::get<ConfusionStatus>(replaced.Volatile().front()).turns_remaining, 1);
  EXPECT_NE(original, replaced);
  const auto cleared = ClearStatusOnSwitchOut(replaced);
  EXPECT_TRUE(cleared.Has(MajorStatusKind::sleep));
  EXPECT_TRUE(cleared.Has(VolatileStatusKind::flinch));
  EXPECT_FALSE(cleared.Has(VolatileStatusKind::confusion));
  EXPECT_FALSE(cleared.Has(VolatileStatusKind::infatuation));
  EXPECT_FALSE(original.WithMajor(std::nullopt).Major());
  EXPECT_TRUE(original.ClearVolatile().Volatile().empty());
  EXPECT_THROW(static_cast<void>(CombatantStatus(MajorStatus{SleepStatus{-1}})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(CombatantStatus(MajorStatus{BadPoisonStatus{0}})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(CombatantStatus(std::nullopt, {ConfusionStatus{1}, ConfusionStatus{2}})), std::invalid_argument);
}

/// 独立状态 helper 保留精确速度/灼伤倍率；零速度、非二进制概率和输出溢出均有明确合同。
TEST(Status, ExactSpeedAndBurnModifiers) {
  const CombatantStatus paralysis{MajorStatus{ParalysisStatus{}}};
  EXPECT_EQ(ApplyParalysisSpeed(101, paralysis, ParalysisSpeedForGeneration(6)), 25);
  EXPECT_EQ(ApplyParalysisSpeed(101, paralysis, ParalysisSpeedForGeneration(7)), 50);
  EXPECT_EQ(ApplyParalysisSpeed(1, paralysis, Rational{1, 4}), 0);
  EXPECT_EQ(ApplyParalysisSpeed(101, CombatantStatus{}, Rational{1, 3}), 101);
  const CombatantStatus burn{MajorStatus{BurnStatus{}}};
  EXPECT_EQ(ApplyBurnDamageMultiplier(Rational{2, 7}, burn, DamageCategory::physical, Rational{1, 3}), (Rational{2, 21}));
  EXPECT_EQ(BurnPhysicalMultiplier(burn, DamageCategory::special, Rational{1, 3}), Rational{1});
  EXPECT_EQ(BurnPhysicalMultiplier(burn, DamageCategory::status, Rational{1, 3}), Rational{1});
  EXPECT_THROW(static_cast<void>(ApplyParalysisSpeed(-1, paralysis, Rational{1})), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(ApplyParalysisSpeed(std::numeric_limits<std::int64_t>::max(), paralysis, Rational{2})), std::overflow_error);
}

/// 名称和绝对回合不进入 StateKey，完整编码相等性支持实际 unordered_set 去重。
TEST(State, SemanticKeysIgnorePresentationAndAbsoluteTurn) {
  const auto original = Reference();
  const auto renamed = BattleState{{Battler(Spec(212, "巨钳螳螂")), Battler(Spec(700, "仙子伊布")), InferenceRules{}, 99, {}, BattlePhase::action_selection}};
  EXPECT_EQ(original, renamed);
  EXPECT_EQ(original.Key(), renamed.Key());
  EXPECT_EQ(original.NextTurn().Key(), original.Key());
  const std::unordered_set<StateKey, StateKeyHash> keys{original.Key(), renamed.Key()};
  EXPECT_EQ(keys.size(), 1);
  static_assert(std::is_same_v<decltype(original.View()), const BattleStateData&>);
}

/// 每个动态字段都影响未来转移，必须进入键；更新不得改写祖先和兄弟分支。
TEST(State, DynamicFieldsAndAncestorIsolation) {
  const auto original = Reference();
  const auto& first = original.View().attacker;
  const std::vector<BattlerState> variants{
      first.WithCurrentHp(176), first.WithMoveSlot(first.MoveSlot(2).WithCurrentPp(14)),
      first.WithMoveSlot(first.MoveSlot(2).WithDisabled(true)), first.WithChoiceLock(1),
      first.WithStages(StatStages{}.WithStage(StatStageField::attack, 1)), first.WithLastMove(165),
      first.WithItemConsumed(true), first.WithStatus(CombatantStatus{std::nullopt, {FlinchStatus{}}}), first.MarkFirstTurnComplete()};
  std::unordered_set<StateKey, StateKeyHash> keys{original.Key()};
  for (const auto& variant : variants) {
    const auto changed = original.WithBattler(BattleSide::attacker, variant);
    EXPECT_NE(changed, original); EXPECT_NE(changed.Key(), original.Key()); keys.insert(changed.Key());
  }
  keys.insert(original.WithPhase(BattlePhase::action_resolution).Key());
  EXPECT_EQ(keys.size(), 11);
  EXPECT_EQ(first.View().current_hp, 177); EXPECT_EQ(first.MoveSlot(2).View().current_pp, 15);
  EXPECT_FALSE(first.View().choice_lock_move_id); EXPECT_TRUE(first.View().is_first_turn);
  auto reordered_slots = first.View();
  std::swap(reordered_slots.move_slots[0], reordered_slots.move_slots[1]);
  EXPECT_NE(original.WithBattler(BattleSide::attacker, BattlerState{reordered_slots}).Key(), original.Key());
  EXPECT_NE(original.WithField({DamageWeather::snow, DamageTerrain::none, {}, {}}).Key(), original.Key());
}

/// 每个策略/配置字段也必须进入键，浮点 +0/-0 应和领域相等性保持一致。
TEST(State, RulesSpecificationsAndZeroCanonicalization) {
  const auto original = Reference();
  auto rules = original.View().rules.View();
  rules.max_turns = 101;
  auto changed = original.View(); changed.rules = InferenceRules{rules};
  EXPECT_NE(BattleState{changed}.Key(), original.Key());
  rules.max_turns = 100; rules.damage_policy.life_orb_damage_multiplier = 1.31;
  changed.rules = InferenceRules{rules}; EXPECT_NE(BattleState{changed}.Key(), original.Key());
  rules.damage_policy.life_orb_damage_multiplier = 1.3; rules.move_execution_policy.struggle_recoil_fraction = Rational{1, 3};
  changed.rules = InferenceRules{rules}; EXPECT_NE(BattleState{changed}.Key(), original.Key());
  rules.move_execution_policy.struggle_recoil_fraction = Rational{1, 4}; rules.damage_policy.life_orb_damage_multiplier = 0.0;
  changed.rules = InferenceRules{rules}; const BattleState positive_zero{changed};
  rules.damage_policy.life_orb_damage_multiplier = -0.0; changed.rules = InferenceRules{rules};
  EXPECT_EQ(positive_zero, BattleState{changed}); EXPECT_EQ(positive_zero.Key(), BattleState{changed}.Key());
  auto spec = original.View().attacker.View().spec.View(); spec.pokemon.stats.speed += 1;
  auto battler = original.View().attacker.View(); battler.spec = PokemonSpec{spec};
  EXPECT_NE(original.WithBattler(BattleSide::attacker, BattlerState{battler}).Key(), original.Key());
  spec.name = "\xe3\x80\x80invalid";
  EXPECT_THROW(static_cast<void>(PokemonSpec{spec}), std::invalid_argument);
}

/// HP/PP/槽位/锁招和推演规则在进入图前即验证；不会自动修复非法组合。
TEST(State, RejectsInvalidValuesAndChoiceLocks) {
  const auto original = Reference();
  const auto& first = original.View().attacker;
  EXPECT_THROW(static_cast<void>(first.WithCurrentHp(178)), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(first.WithCurrentHp(-1)), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(first.MoveSlot(1).WithCurrentPp(31)), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(first.WithMoveSlot(first.MoveSlot(1).WithLocked(true))), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(first.WithChoiceLock(999)), std::invalid_argument);
  EXPECT_THROW(static_cast<void>(first.WithChoiceLock(1).WithItemConsumed(true)), std::invalid_argument);
  EXPECT_EQ(first.WithChoiceLock(1).WithMoveSlot(first.MoveSlot(1).WithCurrentPp(0).WithLocked(true)).View().choice_lock_move_id, 1);
  auto missing = first.View(); missing.move_slots.pop_back();
  EXPECT_THROW(static_cast<void>(BattlerState{missing}), std::invalid_argument);
  auto rules = original.View().rules.View(); rules.allow_mega_evolution = true;
  EXPECT_THROW(static_cast<void>(InferenceRules{rules}), UnsupportedRule);
  rules.allow_mega_evolution = false; rules.move_execution_policy.consume_pp_on_miss = false;
  EXPECT_THROW(static_cast<void>(InferenceRules{rules}), UnsupportedRule);
}

/// 相对方向、屏障和已消耗道具正确转换；PP/锁招检查不执行伤害也不消耗资源。
TEST(State, DamageSnapshotAndEffectiveSpeed) {
  auto input = Reference().View();
  input.field.attacker_side.reflect = true; input.field.defender_side.light_screen = true;
  input.defender = input.defender.WithItemConsumed(true);
  input.attacker = input.attacker.WithStatus(CombatantStatus{MajorStatus{ParalysisStatus{}}})
      .WithStages(StatStages{}.WithStage(StatStageField::speed, -1));
  const BattleState state{input};
  const auto damage = state.DamageInputFor(BattleSide::defender, 1, DamagePolicyForGeneration(9));
  EXPECT_EQ(damage.attacker.item, DamageItem::none); EXPECT_EQ(damage.defender.item, DamageItem::choice_band);
  EXPECT_TRUE(damage.defender_side.reflect); EXPECT_FALSE(damage.defender_side.light_screen);
  EXPECT_EQ(EffectiveActionSpeed(state.View().attacker), 56); // 旧排序不叠加独立麻痹 helper。
  EXPECT_EQ(input.defender.MoveSlot(1).View().current_pp, 30);
  const auto blocked = state.WithBattler(BattleSide::defender, state.View().defender.WithMoveSlot(state.View().defender.MoveSlot(1).WithDisabled(true)));
  EXPECT_THROW(static_cast<void>(blocked.DamageInputFor(BattleSide::defender, 1, DamagePolicyForGeneration(9))), std::invalid_argument);
}
} // namespace pbi
