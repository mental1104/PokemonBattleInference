#include "pbi/turn.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// @param id 稳定配置 ID；@param speed 速度；@param power 招式威力；@param priority 优先级。
/// @param effect 可空已规范化机制；@param ability 特性；@return 已验证单招式满 HP/PP 节点。
BattlerState TurnBattler(std::int64_t id, std::int32_t speed, std::int32_t power = 40, std::int32_t priority = 0,
    std::optional<std::string> effect = std::nullopt, DamageAbility ability = DamageAbility::none) {
  const PokemonSpec spec{{id, "test", {50, {PokemonType::normal}, {100, 100, 100, 100, 100, speed}, ability, DamageItem::none, false, std::nullopt},
      {MoveSpec{{1, "attack", {PokemonType::normal, DamageCategory::physical, power}, 3, priority, 100, std::move(effect)}}}}};
  return BattlerState{{spec, 100, {MoveSlotState{{1, 3, 3, false, false, id * 1000 + 1}}}, StatStages{}, CombatantStatus{}, std::nullopt, std::nullopt, false, true}};
}
/// @return 可单独算出伤害且两方速度不同的稳定节点。
BattleState TurnState() { return BattleState{{TurnBattler(1, 100), TurnBattler(2, 90), InferenceRules{}, 1, {}, BattlePhase::action_selection}}; }
/// @return 当前 fixture 唯一所需属性知识，缺其他属性明确失败。
TypeChartSnapshot TurnKnowledge() { return TypeChartSnapshot{{{PokemonType::normal, PokemonType::normal, 100}}}; }
/// @param summary 所有实际事件路径；@param kind 业务种类；@param source 精确来源；@return 是否实际记录该事实。
bool HasEvent(const EventSummary& summary, BattleEventKind kind, std::string_view source) {
  for (const auto& path : summary.Paths()) for (const auto& event : path.events)
    if (const auto* business = std::get_if<BattleEvent>(&event); business && business->View().kind == kind && business->View().source_identifier == source) return true;
  return false;
}
/// @param resolver 正式执行器；@param state 当前节点；@return 双方选择首个合法行动后的真实回合。
TurnResolution ResolveFirst(const StandardTurnResolver& resolver, const BattleState& state) {
  return resolver.Resolve(state, GenerateLegalActions(state, BattleSide::attacker).front(), GenerateLegalActions(state, BattleSide::defender).front());
}
} // namespace

/// 正式回合复用伤害 Core，消耗最后一点 PP 后仍命中，输入与祖先保持不变。
TEST(Turn, RealDamagePpAndLastPpConsumption) {
  const StandardTurnResolver resolver{TurnKnowledge()};
  auto state = TurnState();
  state = state.WithBattler(BattleSide::attacker, state.View().attacker.WithMoveSlot(state.View().attacker.MoveSlot(1).WithCurrentPp(1)));
  const auto resolved = ResolveFirst(resolver, state);
  EXPECT_EQ(resolved.phases, stable_turn_phases); ASSERT_FALSE(resolved.transitions.empty());
  ValidateTransitions(resolved.transitions);
  for (const auto& transition : resolved.transitions) {
    const auto& next = transition.View().state;
    EXPECT_EQ(next.View().attacker.MoveSlot(1).View().current_pp, 0);
    EXPECT_EQ(next.View().defender.MoveSlot(1).View().current_pp, 2);
    EXPECT_LT(next.View().defender.View().current_hp, 100); EXPECT_LT(next.View().attacker.View().current_hp, 100);
    EXPECT_EQ(next.View().turn_number, 2); EXPECT_FALSE(next.View().attacker.View().is_first_turn);
    EXPECT_TRUE(HasEvent(transition.View().events, BattleEventKind::pp_changed, "move-use"));
  }
  EXPECT_EQ(state.View().attacker.MoveSlot(1).View().current_pp, 1); EXPECT_EQ(state.View().defender.View().current_hp, 100);
}

/// FakeOut 优先与施加畏缩影响真实后手，非首次回合明确阻断且不扣 PP。
TEST(Turn, FakeOutFlinchAndFirstTurnGate) {
  const StandardTurnResolver resolver{TurnKnowledge()};
  const BattleState state{{TurnBattler(1, 50, 40, 3, "fake_out"), TurnBattler(2, 100), InferenceRules{}, 1, {}, BattlePhase::action_selection}};
  const auto resolution = ResolveFirst(resolver, state);
  for (const auto& transition : resolution.transitions) {
    const auto& next = transition.View().state;
    EXPECT_EQ(next.View().attacker.View().current_hp, 100); EXPECT_EQ(next.View().defender.MoveSlot(1).View().current_pp, 3);
    EXPECT_FALSE(next.View().defender.View().status.Has(VolatileStatusKind::flinch));
    EXPECT_TRUE(HasEvent(transition.View().events, BattleEventKind::status_applied, "fake_out"));
    EXPECT_TRUE(HasEvent(transition.View().events, BattleEventKind::action_blocked, "flinch"));
  }
  const auto repeated = ResolveFirst(resolver, resolution.transitions.front().View().state);
  for (const auto& transition : repeated.transitions) {
    EXPECT_EQ(transition.View().state.View().attacker.MoveSlot(1).View().current_pp, 2);
    EXPECT_TRUE(HasEvent(transition.View().events, BattleEventKind::action_blocked, "fake_out"));
    EXPECT_LT(transition.View().state.View().attacker.View().current_hp, 100);
  }
}

/// 实时目标特性在动态层结算，不把 Multiscale/InnerFocus 降为静默无效果。
TEST(Turn, MultiscaleAndInnerFocusDynamicEffects) {
  const StandardTurnResolver resolver{TurnKnowledge()};
  const BattleState multiscale{{TurnBattler(1, 100, 40, 1), TurnBattler(2, 90, 40, 0, {}, DamageAbility::multiscale),
      InferenceRules{}, 1, {}, BattlePhase::action_selection}};
  const auto reduced = ResolveFirst(resolver, multiscale);
  for (const auto& transition : reduced.transitions) {
    EXPECT_GE(transition.View().state.View().defender.View().current_hp, 86);
    EXPECT_TRUE(HasEvent(transition.View().events, BattleEventKind::ability_triggered, "ability:multiscale"));
  }
  const BattleState immune{{TurnBattler(1, 50, 40, 3, "fake_out"), TurnBattler(2, 100, 40, 0, {}, DamageAbility::inner_focus),
      InferenceRules{}, 1, {}, BattlePhase::action_selection}};
  const auto prevented = ResolveFirst(resolver, immune);
  ASSERT_EQ(prevented.unsupported_aspects.size(), 1);
  EXPECT_EQ(prevented.unsupported_aspects[0].capability, "intimidate_immunity");
  for (const auto& transition : prevented.transitions) {
    EXPECT_LT(transition.View().state.View().attacker.View().current_hp, 100);
    EXPECT_EQ(transition.View().state.View().defender.MoveSlot(1).View().current_pp, 2);
    EXPECT_TRUE(HasEvent(transition.View().events, BattleEventKind::status_prevented, "inner_focus"));
  }
}

/// 无 PP 的挣扎不改普通槽位，最大 HP 反伤允许真实同时濒死。
TEST(Turn, StruggleRecoilAndMutualKnockout) {
  const StandardTurnResolver resolver{TurnKnowledge()};
  auto state = TurnState();
  for (const auto side : {BattleSide::attacker, BattleSide::defender}) {
    const auto& battler = state.Battler(side);
    state = state.WithBattler(side, battler.WithCurrentHp(1).WithMoveSlot(battler.MoveSlot(1).WithCurrentPp(0)));
  }
  const auto result = ResolveFirst(resolver, state);
  ASSERT_EQ(result.transitions.size(), 1);
  const auto& terminal = result.transitions.front().View();
  EXPECT_EQ(terminal.state.View().attacker.View().current_hp, 0); EXPECT_EQ(terminal.state.View().defender.View().current_hp, 0);
  EXPECT_EQ(terminal.state.View().phase, BattlePhase::terminal); EXPECT_EQ(terminal.state.View().turn_number, 1);
  EXPECT_EQ(terminal.state.View().attacker.MoveSlot(1).View().current_pp, 0);
  EXPECT_TRUE(HasEvent(terminal.events, BattleEventKind::damage, "struggle-recoil"));
}

/// 正式执行器、玩家策略、BFS 与精确求解构成真实固定战斗，不依赖测试脚本。
TEST(Turn, FixedBattleRealClosedLoopAndTruncation) {
  auto state = TurnState();
  auto first = TurnBattler(1, 100, 200, 1);
  state = state.WithBattler(BattleSide::attacker, first).WithBattler(BattleSide::defender, state.View().defender.WithCurrentHp(20));
  const auto result = InferFixedBattle(state, TurnKnowledge());
  ASSERT_EQ(result.graph.Nodes().size(), 2); ASSERT_EQ(result.graph.Edges().size(), 1);
  const auto& solved = std::get<SolvedGraph>(result.solution);
  EXPECT_EQ(solved.win, Rational{1}); EXPECT_EQ(std::get<FiniteExpectedTurns>(solved.expected_turns).value, Rational{1});
  FixedBattleOptions limited;
  limited.graph_limits.max_nodes = 1;
  const auto incomplete = InferFixedBattle(state, TurnKnowledge(), limited);
  EXPECT_EQ(std::get<UnavailableGraph>(incomplete.solution).status, GraphSolveStatus::incomplete_graph);
}

/// 未知机制、非法行动、资源保护和取消均明确失败，不返回裁剪后归一化的伪概率。
TEST(Turn, ExplicitUnsupportedBudgetsAndCancellation) {
  const auto state = TurnState();
  const StandardTurnResolver resolver{TurnKnowledge()};
  const auto first = GenerateLegalActions(state, BattleSide::attacker).front();
  const auto second = GenerateLegalActions(state, BattleSide::defender).front();
  EXPECT_THROW(static_cast<void>(resolver.Resolve(state, first, second, TurnLimits{1, {}})), TurnResourceLimit);
  EXPECT_THROW(static_cast<void>(resolver.Resolve(state, second, first)), std::invalid_argument);
  CancellationSource cancellation; cancellation.Request();
  EXPECT_THROW(static_cast<void>(resolver.Resolve(state, first, second, {}, cancellation.Token())), TurnCancelled);
  const BattleState unknown{{TurnBattler(1, 100, 40, 0, "unimplemented_move"), TurnBattler(2, 90),
      InferenceRules{}, 1, {}, BattlePhase::action_selection}};
  EXPECT_THROW(static_cast<void>(ResolveFirst(resolver, unknown)), UnsupportedRule);
}
} // namespace pbi
