#include "pbi/transitions.hpp"
#include <algorithm>
#include <array>
#include <stdexcept>
#include <unordered_map>

namespace pbi {
namespace {
/// @param value 只读 UTF-8 文本；@return 是否含至少一个非 Python whitespace 字符。
bool HasNonWhitespace(std::string_view value) {
  constexpr std::array<std::string_view, 29> spaces{"\t", "\n", "\v", "\f", "\r", "\x1c", "\x1d", "\x1e", "\x1f", " ",
      "\xc2\x85", "\xc2\xa0", "\xe1\x9a\x80", "\xe2\x80\x80", "\xe2\x80\x81", "\xe2\x80\x82", "\xe2\x80\x83", "\xe2\x80\x84", "\xe2\x80\x85", "\xe2\x80\x86", "\xe2\x80\x87", "\xe2\x80\x88", "\xe2\x80\x89", "\xe2\x80\x8a", "\xe2\x80\xa8", "\xe2\x80\xa9", "\xe2\x80\xaf", "\xe2\x81\x9f", "\xe3\x80\x80"};
  while (!value.empty()) {
    const auto found = std::find_if(spaces.begin(), spaces.end(), [value](std::string_view space) { return value.starts_with(space); });
    if (found == spaces.end()) return true;
    value.remove_prefix(found->size());
  }
  return false;
}
/// @param side 可空固定战斗侧；非法非空枚举抛 invalid_argument。
void ValidateSide(std::optional<BattleSide> side) {
  if (side && *side != BattleSide::attacker && *side != BattleSide::defender) throw std::invalid_argument("event side must be a BattleSide or null");
}
/// @param side 可空战斗侧；@return 原事件身份中的稳定值或 none。
std::string SideName(std::optional<BattleSide> side) {
  if (!side) return "none";
  return *side == BattleSide::attacker ? "attacker" : "defender";
}
/// @param value 可空任意精度整数；@return 事件身份中的十进制或 none。
std::string IntegerName(const std::optional<Integer>& value) { return value ? value->str() : "none"; }
} // namespace

TransitionEvent::TransitionEvent(TransitionEventData data) : data_(std::move(data)) {
  switch (data_.type) {
    case TransitionEventType::hit_check: case TransitionEventType::damage_roll: case TransitionEventType::speed_tie:
    case TransitionEventType::secondary_effect: case TransitionEventType::custom: break;
    default: throw std::invalid_argument("unsupported transition event type");
  }
  if (!HasNonWhitespace(data_.event_id) || !HasNonWhitespace(data_.outcome_id)) throw std::invalid_argument("transition event identifiers cannot be blank");
}

std::string_view BattleEventName(BattleEventKind kind) {
  constexpr std::array<std::string_view, 16> names{"turn-started", "move-selected", "action-ordered", "move-used", "action-blocked", "hit", "miss",
      "damage", "hp-changed", "pp-changed", "ability-triggered", "item-triggered", "status-applied", "status-prevented", "fainted", "turn-ended"};
  const auto index = static_cast<std::size_t>(kind);
  if (index >= names.size()) throw std::invalid_argument("unsupported battle event kind");
  return names[index];
}

BattleEvent::BattleEvent(BattleEventData data) : data_(std::move(data)) {
  static_cast<void>(BattleEventName(data_.kind));
  if (data_.turn_number <= 0) throw std::invalid_argument("event turn_number must be greater than 0");
  ValidateSide(data_.actor); ValidateSide(data_.target);
  if (data_.move_id && *data_.move_id <= 0) throw std::invalid_argument("event move_id must be greater than 0 or null");
  if (data_.source_identifier && !HasNonWhitespace(*data_.source_identifier)) throw std::invalid_argument("source_identifier cannot be blank");
  if (data_.before.has_value() != data_.after.has_value()) throw std::invalid_argument("before and after values must be provided together");
  if (!data_.value && data_.before) data_.value = *data_.after - *data_.before;
}

TransitionEvent BattleEvent::Identity() const {
  const auto kind = std::string{BattleEventName(data_.kind)};
  const auto identifier = "turn-" + std::to_string(data_.turn_number) + ":" + kind + ":" + SideName(data_.actor) + ":" + SideName(data_.target)
      + ":" + (data_.move_id ? std::to_string(*data_.move_id) : "none") + ":" + data_.source_identifier.value_or("none")
      + ":" + IntegerName(data_.before) + ":" + IntegerName(data_.after) + ":" + IntegerName(data_.value);
  return TransitionEvent{{TransitionEventType::custom, identifier, kind, data_.value}};
}

std::optional<Integer> BattleEvent::Delta() const {
  if (!data_.before) return std::nullopt;
  return Integer{*data_.after - *data_.before};
}

EventSummary::EventSummary(std::vector<WeightedEventPath> paths) {
  if (paths.empty()) throw std::invalid_argument("event summary must contain at least one path");
  Rational total{0};
  for (auto& path : paths) {
    if (path.probability <= Rational{0} || path.probability > Rational{1}) throw std::invalid_argument("event path probability must be in (0, 1]");
    total += path.probability;
    const auto existing = std::find_if(paths_.begin(), paths_.end(), [&](const WeightedEventPath& candidate) { return candidate.events == path.events; });
    if (existing == paths_.end()) paths_.push_back(std::move(path));
    else existing->probability += path.probability;
  }
  if (total != Rational{1}) throw std::invalid_argument("event path probabilities must sum exactly to 1");
}

EventSummary EventSummary::Concatenate(const EventSummary& following) const {
  std::vector<WeightedEventPath> result;
  for (const auto& first : paths_) for (const auto& second : following.paths_) {
    auto events = first.events;
    events.insert(events.end(), second.events.begin(), second.events.end());
    result.push_back({std::move(events), first.probability * second.probability});
  }
  return EventSummary{std::move(result)};
}

EventSummary EventSummary::MergeAlternatives(const EventSummary& other, const Rational& own_weight, const Rational& other_weight) const {
  if (own_weight <= Rational{0} || other_weight <= Rational{0}) throw std::invalid_argument("alternative parent weights must be positive");
  const Rational total = own_weight + other_weight;
  std::vector<WeightedEventPath> result;
  for (const auto& path : paths_) result.push_back({path.events, own_weight / total * path.probability});
  for (const auto& path : other.paths_) result.push_back({path.events, other_weight / total * path.probability});
  return EventSummary{std::move(result)};
}

BattleTransition::BattleTransition(BattleTransitionData data) : data_(std::move(data)) {
  if (data_.probability <= Rational{0} || data_.probability > Rational{1}) throw std::invalid_argument("transition probability must be in (0, 1]");
  if (data_.source_key && !HasNonWhitespace(*data_.source_key)) throw std::invalid_argument("transition source key cannot be blank");
}

void ValidateTransitions(std::span<const BattleTransition> transitions) {
  if (transitions.empty()) throw std::invalid_argument("transition distribution cannot be empty");
  Rational total{0};
  for (const auto& transition : transitions) total += transition.View().probability;
  if (total != Rational{1}) throw std::invalid_argument("transition probabilities must sum exactly to 1");
}

std::vector<BattleTransition> MergeEquivalentTransitions(std::span<const BattleTransition> transitions) {
  ValidateTransitions(transitions);
  std::unordered_map<StateKey, std::size_t, StateKeyHash> by_key;
  std::vector<BattleTransitionData> accumulated;
  for (const auto& transition : transitions) {
    const auto& value = transition.View();
    const auto key = value.state.Key();
    const auto [position, inserted] = by_key.emplace(key, accumulated.size());
    if (inserted) { accumulated.push_back(value); continue; }
    auto& existing = accumulated[position->second];
    existing.events = existing.events.MergeAlternatives(value.events, existing.probability, value.probability);
    existing.probability += value.probability;
    if (existing.source_key != value.source_key) existing.source_key.reset();
  }
  std::vector<BattleTransition> result;
  for (auto& value : accumulated) result.emplace_back(std::move(value));
  ValidateTransitions(result);
  return result;
}

std::vector<BattleTransition> NormalizeTransitionWeights(std::span<const BattleTransition> transitions) {
  if (transitions.empty()) throw std::invalid_argument("transition weights cannot be empty");
  Rational total{0};
  for (const auto& transition : transitions) total += transition.View().probability;
  std::vector<BattleTransition> normalized;
  for (const auto& transition : transitions) {
    auto value = transition.View(); value.probability /= total; normalized.emplace_back(std::move(value));
  }
  return MergeEquivalentTransitions(normalized);
}

std::vector<BattleTransition> BranchTransitions(std::span<const BattleTransition> parents,
    const TransitionExpander& expand, std::optional<std::string> source_key) {
  ValidateTransitions(parents);
  if (!expand) throw std::invalid_argument("transition branch expander cannot be empty");
  std::vector<BattleTransition> result;
  for (const auto& parent : parents) {
    const auto& first = parent.View();
    const auto children = expand(first.state); ValidateTransitions(children);
    for (const auto& child : children) {
      const auto& second = child.View();
      result.emplace_back(BattleTransitionData{first.probability * second.probability, second.state,
          first.events.Concatenate(second.events), source_key ? source_key : second.source_key ? second.source_key : first.source_key});
    }
  }
  return MergeEquivalentTransitions(result);
}
} // namespace pbi
