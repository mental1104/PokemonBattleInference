#include "pbi/status_gates.hpp"
#include <gtest/gtest.h>

namespace pbi {
namespace {
/// 原睡眠失败后增加计数，成功后清空；表用尽始终复用末项。
TEST(StatusGates, SleepWakeTableAndCounterAreOriginal) {
  const auto rules = StatusGateRulesForGeneration(9);
  std::vector<Rational> probabilities;
  const StatusChance fail = [&](const Rational& chance) { probabilities.push_back(chance); return false; };
  const auto sleeping = CheckStatusActionGate(StatusActionGate::sleep, CombatantStatus{SleepStatus{8}}, false, rules, fail);
  EXPECT_EQ(sleeping.decision, StatusActionDecision::block);
  EXPECT_EQ(std::get<SleepStatus>(*sleeping.updated_status.Major()).turns_asleep, 9);
  EXPECT_EQ(probabilities, (std::vector<Rational>{Rational{1}}));
  EXPECT_EQ(sleeping.events, (std::vector<std::string>{"sleep_continues", "sleep_blocks_action"}));
  const auto awake = CheckStatusActionGate(StatusActionGate::sleep, sleeping.updated_status, false, rules, [](const Rational&) { return true; });
  EXPECT_FALSE(awake.updated_status.Major());
  EXPECT_EQ(awake.reason, "sleep_woke_up");
}
/// 解冻招式flag分支完全跳过随机端口；禁止override后恢复原概率判定。
TEST(StatusGates, ThawMoveOverrideDoesNotConsumeRandomness) {
  auto rules = StatusGateRulesForGeneration(1);
  unsigned consumed = 0;
  const StatusChance fail = [&](const Rational&) { ++consumed; return false; };
  const CombatantStatus status{FreezeStatus{}, {ConfusionStatus{3}, FlinchStatus{}}};
  auto result = CheckStatusActionGate(StatusActionGate::freeze, status, true, rules, fail);
  EXPECT_EQ(consumed, 0U); EXPECT_EQ(result.reason, "freeze_thawed_by_move");
  EXPECT_EQ(result.updated_status.Volatile(), status.Volatile());
  rules.allow_thaw_move_override = false;
  result = CheckStatusActionGate(StatusActionGate::freeze, status, true, rules, fail);
  EXPECT_EQ(consumed, 1U); EXPECT_EQ(result.decision, StatusActionDecision::block);
}
/// 默认原顺序在麻痹阻断后不再消费混乱/着迷随机；混乱单门禁是替换而非阻断。
TEST(StatusGates, DefaultPipelineStopsAtFirstBlockingGate) {
  const auto rules = StatusGateRulesForGeneration(9);
  const CombatantStatus status{ParalysisStatus{}, {ConfusionStatus{2}, InfatuationStatus{"target"}}};
  std::vector<Rational> probabilities;
  const StatusChance hit = [&](const Rational& probability) { probabilities.push_back(probability); return true; };
  auto result = CheckDefaultStatusActionGates(status, false, rules, hit);
  EXPECT_EQ(result.reason, "paralysis"); EXPECT_EQ(probabilities, (std::vector<Rational>{Rational{1, 4}}));
  result = CheckStatusActionGate(StatusActionGate::confusion, status, false, rules, hit);
  EXPECT_EQ(result.decision, StatusActionDecision::replace_with_self_hit);
  EXPECT_EQ(result.updated_status, status);
}
/// 全ALLOW管线保留醒来事件但清除单门禁reason，符合原pipeline而非单门禁结果。
TEST(StatusGates, PipelinePreservesEventsAndClearsAllowReason) {
  const CombatantStatus status{SleepStatus{1}};
  const auto result = CheckDefaultStatusActionGates(status, false, StatusGateRulesForGeneration(9), [](const Rational&) { return true; });
  EXPECT_EQ(result.decision, StatusActionDecision::allow); EXPECT_FALSE(result.reason);
  EXPECT_EQ(result.events, (std::vector<std::string>{"sleep_woke_up"}));
  EXPECT_EQ(std::get<SleepStatus>(*status.Major()).turns_asleep, 1);
}
/// 策略概率及原代际边界拒绝；合法零倍率和概率端点不被擅自收紧。
TEST(StatusGates, RejectsInvalidPoliciesAndEmptyPipeline) {
  auto rules = StatusGateRulesForGeneration(9);
  rules.paralysis_speed_multiplier = Rational{0}; rules.burn_physical_multiplier = Rational{0};
  EXPECT_NO_THROW(ValidateStatusGateRules(rules));
  rules.sleep_wake_chances.clear(); EXPECT_THROW(ValidateStatusGateRules(rules), std::invalid_argument);
  rules = StatusGateRulesForGeneration(9); rules.confusion_self_hit_chance = Rational{2};
  EXPECT_THROW(ValidateStatusGateRules(rules), std::invalid_argument);
  EXPECT_THROW((void)StatusGateRulesForGeneration(10), std::invalid_argument);
  EXPECT_THROW((void)CheckStatusActionGatePipeline({}, CombatantStatus{}, false, StatusGateRulesForGeneration(9), {}), std::invalid_argument);
}
} // namespace
} // namespace pbi
