#include "pbi/turn.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param id 配置身份；@param speed 稳定行动顺序；@param assumption 可空的显式原UNKNOWN透明假设。
/// @return 原机械UNKNOWN和原始能力元数据分离的已验证一侧，不将白名单视作已实现能力。
BattlerState Battler(std::int64_t id, std::int32_t speed, std::optional<TransparentNeutralAbility> assumption = std::nullopt) {
  const PokemonSpec spec{{id, "transparent-fixture", {50, {PokemonType::normal}, {100, 100, 100, 100, 100, speed}, DamageAbility::none, DamageItem::none, false, std::nullopt},
      {MoveSpec{{1, "attack", {PokemonType::normal, DamageCategory::physical, 80}, 3, 0, 100, std::nullopt}}}, assumption}};
  return BattlerState{{spec, 100, {MoveSlotState{{1, 3, 3, false, false, id * 1000 + 1}}}, StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @param attacker 攻方透明假设；@param defender 守方透明假设；@return 单随机档真实固定战斗初始状态。
BattleState State(std::optional<TransparentNeutralAbility> attacker = std::nullopt, std::optional<TransparentNeutralAbility> defender = std::nullopt) {
  auto rules = InferenceRules{}.View();
  rules.damage_policy.random_damage_multipliers = {1};
  return BattleState{{Battler(1, 100, attacker), Battler(2, 90, defender), InferenceRules{std::move(rules)}, 1, {}, BattlePhase::action_selection}};
}
/// 原None/none/pressure/pickpocket都经DamageAbility.UNKNOWN进入SpecKey，raw假设不得让Key分叉。
TEST(TransparentAbility, PreservesOriginalUnknownSpecAndStateKeys) {
  const auto baseline = State();
  const auto pressure = State(TransparentNeutralAbility::pressure);
  const auto pickpocket = State(TransparentNeutralAbility::pickpocket);
  EXPECT_EQ(baseline.Key(), pressure.Key());
  EXPECT_EQ(pressure.Key(), pickpocket.Key());
  EXPECT_EQ(baseline.View().attacker.View().spec, pressure.View().attacker.View().spec);
  EXPECT_EQ(pressure.View().attacker.View().spec, pickpocket.View().attacker.View().spec);
  EXPECT_EQ(TransparentNeutralAbilityIdentifier(*pressure.View().attacker.View().spec.View().transparent_ability), "pressure");
  EXPECT_EQ(TransparentNeutralAbilityIdentifier(*pickpocket.View().attacker.View().spec.View().transparent_ability), "pickpocket");
  EXPECT_FALSE(FindTransparentNeutralAbility("unimplemented-ability"));
  auto conflicting = pressure.View().attacker.View().spec.View();
  conflicting.pokemon.ability = DamageAbility::technician;
  EXPECT_THROW((void)PokemonSpec(conflicting), std::invalid_argument);
}
/// 透明占位不增加Pressure双倍PP或Pickpocket偷道具等原未实现行为；完整分支/事件保持原UNKNOWN。
TEST(TransparentAbility, KeepsActualTurnNeutralAndPreservesMissingCoverage) {
  const StandardTurnResolver resolver{TypeChartSnapshot{{{PokemonType::normal, PokemonType::normal, 100}}}};
  const auto baseline = State();
  const auto reference = State(TransparentNeutralAbility::pressure, TransparentNeutralAbility::pickpocket);
  const auto expected = resolver.Expand(baseline, ActionPolicy::first_legal_action, ActionPolicy::first_legal_action);
  const auto actual = resolver.Expand(reference, ActionPolicy::first_legal_action, ActionPolicy::first_legal_action);
  ASSERT_EQ(actual.size(), expected.size());
  for (std::size_t index = 0; index < actual.size(); ++index) {
    EXPECT_EQ(actual[index].View().probability, expected[index].View().probability);
    EXPECT_EQ(actual[index].View().state.Key(), expected[index].View().state.Key());
    ASSERT_EQ(actual[index].View().events.Paths().size(), expected[index].View().events.Paths().size());
    for (std::size_t path = 0; path < actual[index].View().events.Paths().size(); ++path) {
      EXPECT_EQ(actual[index].View().events.Paths()[path].events, expected[index].View().events.Paths()[path].events);
      EXPECT_EQ(actual[index].View().events.Paths()[path].probability, expected[index].View().events.Paths()[path].probability);
    }
    EXPECT_EQ(actual[index].View().state.View().attacker.MoveSlot(1).View().current_pp, 2);
    EXPECT_EQ(actual[index].View().state.View().defender.MoveSlot(1).View().current_pp, 2);
    EXPECT_TRUE(actual[index].View().state.View().attacker.View().spec.View().transparent_ability);
  }
  EXPECT_EQ(resolver.CoverageLimitations(reference), (std::vector<UnsupportedAspect>{{EffectSource::ability, "pressure", "real_ability_behavior"},
      {EffectSource::ability, "pickpocket", "real_ability_behavior"}}));
}
/// 完整固定BFS/SCC/精确解与原UNKNOWN一致，所有后继仍保留真实raw元数据。
TEST(TransparentAbility, KeepsCompleteFixedGraphAndExactSolution) {
  const TypeChartSnapshot knowledge{{{PokemonType::normal, PokemonType::normal, 100}}};
  const auto expected = InferFixedBattle(State(), knowledge);
  const auto actual = InferFixedBattle(State(TransparentNeutralAbility::pressure, TransparentNeutralAbility::pickpocket), knowledge);
  ASSERT_EQ(actual.graph.Nodes().size(), expected.graph.Nodes().size());
  ASSERT_EQ(actual.graph.Edges().size(), expected.graph.Edges().size());
  for (std::size_t index = 0; index < actual.graph.Nodes().size(); ++index) {
    EXPECT_EQ(actual.graph.Nodes()[index].key, expected.graph.Nodes()[index].key);
    EXPECT_TRUE(actual.graph.Nodes()[index].state.View().defender.View().spec.View().transparent_ability);
  }
  const auto& solved = std::get<SolvedGraph>(actual.solution);
  const auto& original = std::get<SolvedGraph>(expected.solution);
  EXPECT_EQ(solved.win, original.win); EXPECT_EQ(solved.loss, original.loss); EXPECT_EQ(solved.draw, original.draw);
  EXPECT_EQ(std::get<FiniteExpectedTurns>(solved.expected_turns).value, std::get<FiniteExpectedTurns>(original.expected_turns).value);
}
} // namespace
} // namespace pbi
