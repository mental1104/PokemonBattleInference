#include "pbi/actions.hpp"
#include <algorithm>
#include <stdexcept>
#include <type_traits>

namespace pbi {
BattleAction ValidateAction(BattleAction action) {
  std::visit([](auto& value) {
    if (value.side != BattleSide::attacker && value.side != BattleSide::defender)
      throw std::invalid_argument("action side must be a BattleSide");
    if constexpr (std::is_same_v<std::decay_t<decltype(value)>, UseMoveAction>) {
      if (value.move_id <= 0) throw std::invalid_argument("move_id must be greater than 0");
      if (value.slot_id == 0) value.slot_id = value.move_id;
      if (value.slot_id < 0) throw std::invalid_argument("action slot_id must be greater than 0");
    }
  }, action);
  return action;
}

BattleSide ActionSide(const BattleAction& action) {
  const auto checked = ValidateAction(action);
  return std::visit([](const auto& value) { return value.side; }, checked);
}

std::vector<BattleAction> GenerateLegalActions(const BattleState& state, BattleSide side) {
  const auto& battler = state.Battler(side).View();
  if (battler.current_hp == 0) return {PassAction{side}};
  std::vector<BattleAction> result;
  for (const auto& slot : battler.move_slots) {
    const auto& data = slot.View();
    if (data.current_pp == 0 || data.disabled ||
        (battler.choice_lock_move_id && data.move_id != *battler.choice_lock_move_id)) continue;
    result.emplace_back(UseMoveAction{side, data.move_id, battler.spec.Move(data.move_id).View().priority, data.slot_id});
  }
  if (result.empty()) result.emplace_back(StruggleAction{side});
  return result;
}

void ValidateActionDistribution(std::span<const ActionSelection> selections, std::span<const BattleAction> legal_actions) {
  if (selections.empty() || legal_actions.empty()) throw std::invalid_argument("action distribution and legal actions cannot be empty");
  Rational total{0};
  std::vector<BattleAction> seen;
  for (const auto& selection : selections) {
    const auto action = ValidateAction(selection.action);
    if (selection.probability <= Rational{0} || selection.probability > Rational{1})
      throw std::invalid_argument("action selection probability must be in (0, 1]");
    if (std::find(legal_actions.begin(), legal_actions.end(), action) == legal_actions.end())
      throw std::invalid_argument("action policy selected an action outside the legal action set");
    if (std::find(seen.begin(), seen.end(), action) != seen.end())
      throw std::invalid_argument("action distribution cannot contain duplicate actions");
    seen.push_back(action);
    total += selection.probability;
  }
  if (total != Rational{1}) throw std::invalid_argument("action probabilities must sum exactly to 1");
}

std::vector<ActionSelection> SelectActions(std::span<const BattleAction> legal_actions, ActionPolicy policy) {
  if (legal_actions.empty()) throw std::invalid_argument("action policy requires at least one legal action");
  std::vector<ActionSelection> result;
  switch (policy) {
    case ActionPolicy::first_legal_action:
      result.push_back({ValidateAction(legal_actions.front()), Rational{1}});
      break;
    case ActionPolicy::uniform_random: {
      const Rational probability{Integer{1}, Integer{legal_actions.size()}};
      for (const auto& action : legal_actions) result.push_back({ValidateAction(action), probability});
      break;
    }
    default: throw std::invalid_argument("unsupported action policy");
  }
  ValidateActionDistribution(result, legal_actions);
  return result;
}
} // namespace pbi
