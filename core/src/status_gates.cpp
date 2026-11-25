#include "pbi/status_gates.hpp"
#include <algorithm>
#include <array>
#include <limits>

namespace pbi {
namespace {
/// @param probability 精确策略概率；@param name 原字段名；不接受超出[0,1]。
void Probability(const Rational& probability, const char* name) {
  if (probability < Rational{0} || probability > Rational{1}) throw std::invalid_argument(std::string{name} + " must be between 0 and 1");
}
/// @param status 已验证完整原快照；@return 无事件/原因的允许结果。
StatusActionGateResult Allow(const CombatantStatus& status) { return {StatusActionDecision::allow, status, std::nullopt, {}}; }
/// @param gate 已验证有限门禁；@param status 原完整状态；@param thaw_move 原数据flag。
/// @param rules 已验证规则；@param chance 原RNG推进端口；@return 对应单门禁的新快照。
StatusActionGateResult Check(StatusActionGate gate, const CombatantStatus& status, bool thaw_move,
    const StatusGateRules& rules, const StatusChance& chance) {
  switch (gate) {
  case StatusActionGate::sleep:
    if (status.Has(MajorStatusKind::sleep)) {
      const auto sleep = std::get<SleepStatus>(*status.Major());
      const auto index = std::min<std::uint64_t>(static_cast<std::uint64_t>(sleep.turns_asleep), rules.sleep_wake_chances.size() - 1);
      if (chance(rules.sleep_wake_chances[index])) return {StatusActionDecision::allow, status.WithMajor(std::nullopt), "sleep_woke_up", {"sleep_woke_up"}};
      if (sleep.turns_asleep == std::numeric_limits<std::int64_t>::max()) throw std::overflow_error("sleep turn counter overflow");
      return {StatusActionDecision::block, status.WithMajor(SleepStatus{sleep.turns_asleep + 1}), "sleep", {"sleep_continues", "sleep_blocks_action"}};
    }
    break;
  case StatusActionGate::freeze:
    if (status.Has(MajorStatusKind::freeze)) {
      if (rules.allow_thaw_move_override && thaw_move) return {StatusActionDecision::allow, status.WithMajor(std::nullopt), "freeze_thawed_by_move", {"freeze_thawed_by_move"}};
      if (chance(rules.freeze_thaw_chance)) return {StatusActionDecision::allow, status.WithMajor(std::nullopt), "freeze_thawed", {"freeze_thawed"}};
      return {StatusActionDecision::block, status, "freeze", {"freeze_blocks_action"}};
    }
    break;
  case StatusActionGate::paralysis:
    if (status.Has(MajorStatusKind::paralysis) && chance(rules.full_paralysis_chance)) return {StatusActionDecision::block, status, "paralysis", {"paralysis_blocks_action"}};
    break;
  case StatusActionGate::infatuation:
    if (status.Has(VolatileStatusKind::infatuation) && chance(rules.infatuation_immobilize_chance)) return {StatusActionDecision::block, status, "infatuation", {"infatuation_blocks_action"}};
    break;
  case StatusActionGate::confusion:
    if (status.Has(VolatileStatusKind::confusion) && chance(rules.confusion_self_hit_chance)) return {StatusActionDecision::replace_with_self_hit, status, "confusion", {"confusion_self_hit"}};
    break;
  default: throw std::invalid_argument("unknown status action gate");
  }
  return Allow(status);
}
} // namespace

void ValidateStatusGateRules(const StatusGateRules& rules) {
  if (rules.sleep_wake_chances.empty()) throw std::invalid_argument("wake_chances must not be empty");
  for (const auto& probability : rules.sleep_wake_chances) Probability(probability, "wake_chances");
  Probability(rules.freeze_thaw_chance, "thaw_chance");
  if (rules.paralysis_speed_multiplier < Rational{0}) throw std::invalid_argument("speed_multiplier must not be negative");
  Probability(rules.full_paralysis_chance, "full_paralysis_chance");
  if (rules.burn_physical_multiplier < Rational{0}) throw std::invalid_argument("physical_damage_multiplier must not be negative");
  Probability(rules.burn_residual_fraction, "residual_damage_fraction");
  Probability(rules.poison_residual_fraction, "residual_damage_fraction");
  Probability(rules.bad_poison_base_fraction, "bad_poison_base_fraction");
  Probability(rules.confusion_self_hit_chance, "self_hit_chance");
  Probability(rules.infatuation_immobilize_chance, "immobilize_chance");
}
StatusGateRules StatusGateRulesForGeneration(std::int32_t generation) {
  StatusGateRules result; result.paralysis_speed_multiplier = ParalysisSpeedForGeneration(generation); return result;
}
StatusActionGateResult CheckStatusActionGate(StatusActionGate gate, const CombatantStatus& status,
    bool thaw_move, const StatusGateRules& rules, const StatusChance& chance) {
  ValidateStatusGateRules(rules); return Check(gate, status, thaw_move, rules, chance);
}
StatusActionGateResult CheckStatusActionGatePipeline(std::span<const StatusActionGate> gates, const CombatantStatus& status,
    bool thaw_move, const StatusGateRules& rules, const StatusChance& chance) {
  if (gates.empty()) throw std::invalid_argument("action gate pipeline must contain at least one gate");
  ValidateStatusGateRules(rules);
  auto current = status;
  std::vector<std::string> events;
  for (const auto gate : gates) {
    auto result = Check(gate, current, thaw_move, rules, chance);
    events.insert(events.end(), result.events.begin(), result.events.end());
    current = std::move(result.updated_status);
    if (result.decision != StatusActionDecision::allow) return {result.decision, std::move(current), std::move(result.reason), std::move(events)};
  }
  return {StatusActionDecision::allow, std::move(current), std::nullopt, std::move(events)};
}
StatusActionGateResult CheckDefaultStatusActionGates(const CombatantStatus& status, bool thaw_move,
    const StatusGateRules& rules, const StatusChance& chance) {
  constexpr std::array gates{StatusActionGate::sleep, StatusActionGate::freeze, StatusActionGate::paralysis, StatusActionGate::infatuation, StatusActionGate::confusion};
  return CheckStatusActionGatePipeline(gates, status, thaw_move, rules, chance);
}
} // namespace pbi
