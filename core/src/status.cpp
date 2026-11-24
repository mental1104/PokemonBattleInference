#include "pbi/status.hpp"
#include <algorithm>
#include <limits>
#include <stdexcept>
#include <utility>

namespace pbi {
CombatantStatus::CombatantStatus(std::optional<MajorStatus> major, std::vector<VolatileStatus> volatile_statuses)
    : major_(std::move(major)), volatile_(std::move(volatile_statuses)) {
  if (major_) {
    if (const auto* sleep = std::get_if<SleepStatus>(&*major_); sleep && sleep->turns_asleep < 0) {
      throw std::invalid_argument("turns_asleep must not be negative");
    }
    if (const auto* poison = std::get_if<BadPoisonStatus>(&*major_); poison && poison->toxic_counter < 1) {
      throw std::invalid_argument("toxic_counter must be positive");
    }
  }
  // frozenset 不保留输入顺序且去重完全相同的值；同种类不同值仍必须拒绝。
  std::stable_sort(volatile_.begin(), volatile_.end(), [](const auto& left, const auto& right) { return left.index() < right.index(); });
  volatile_.erase(std::unique(volatile_.begin(), volatile_.end()), volatile_.end());
  for (std::size_t index = 0; index < volatile_.size(); ++index) {
    if (const auto* confusion = std::get_if<ConfusionStatus>(&volatile_[index]);
        confusion && confusion->turns_remaining && *confusion->turns_remaining < 0) {
      throw std::invalid_argument("turns_remaining must not be negative");
    }
    if (index && volatile_[index - 1].index() == volatile_[index].index()) {
      throw std::invalid_argument("volatile statuses must have unique kinds");
    }
  }
}

bool CombatantStatus::Has(MajorStatusKind kind) const {
  const auto index = static_cast<std::size_t>(kind);
  if (index >= std::variant_size_v<MajorStatus>) throw std::invalid_argument("unsupported major status kind");
  return major_ && major_->index() == index;
}
bool CombatantStatus::Has(VolatileStatusKind kind) const {
  const auto index = static_cast<std::size_t>(kind);
  if (index >= std::variant_size_v<VolatileStatus>) throw std::invalid_argument("unsupported volatile status kind");
  return std::any_of(volatile_.begin(), volatile_.end(), [index](const auto& status) { return status.index() == index; });
}
CombatantStatus CombatantStatus::WithMajor(std::optional<MajorStatus> status) const { return CombatantStatus{std::move(status), volatile_}; }
CombatantStatus CombatantStatus::AddVolatile(VolatileStatus status) const {
  auto values = volatile_;
  std::erase_if(values, [&status](const auto& value) { return value.index() == status.index(); });
  values.push_back(std::move(status));
  return CombatantStatus{major_, std::move(values)};
}
CombatantStatus CombatantStatus::ClearVolatile(VolatileStatusKind kind) const {
  static_cast<void>(Has(kind));
  auto values = volatile_;
  std::erase_if(values, [kind](const auto& value) { return value.index() == static_cast<std::size_t>(kind); });
  return CombatantStatus{major_, std::move(values)};
}
CombatantStatus CombatantStatus::ClearVolatile() const { return CombatantStatus{major_}; }

Rational ParalysisSpeedForGeneration(std::int32_t generation) {
  if (generation < 1 || generation > 9) throw UnsupportedRule("unsupported generation");
  return Rational{1, generation <= 6 ? 4 : 2};
}
std::int64_t ApplyParalysisSpeed(std::int64_t speed, const CombatantStatus& status, const Rational& multiplier) {
  if (speed < 0 || multiplier < Rational{0}) throw std::invalid_argument("speed and multiplier must not be negative");
  if (!status.Has(MajorStatusKind::paralysis)) return speed;
  const Integer value = Integer{speed} * multiplier.numerator() / multiplier.denominator();
  if (value > std::numeric_limits<std::int64_t>::max()) throw std::overflow_error("speed exceeds int64 range");
  return value.convert_to<std::int64_t>();
}
Rational BurnPhysicalMultiplier(const CombatantStatus& status, DamageCategory category, const Rational& policy_multiplier) {
  if (policy_multiplier < Rational{0}) throw std::invalid_argument("burn multiplier must not be negative");
  if (category != DamageCategory::physical && category != DamageCategory::special && category != DamageCategory::status) {
    throw UnsupportedRule("unsupported damage category");
  }
  return status.Has(MajorStatusKind::burn) && category == DamageCategory::physical ? policy_multiplier : Rational{1};
}
Rational ApplyBurnDamageMultiplier(const Rational& base, const CombatantStatus& status,
                                   DamageCategory category, const Rational& policy_multiplier) {
  return base * BurnPhysicalMultiplier(status, category, policy_multiplier);
}
CombatantStatus ClearStatusOnSwitchOut(const CombatantStatus& status) {
  return status.ClearVolatile(VolatileStatusKind::confusion).ClearVolatile(VolatileStatusKind::infatuation);
}
} // namespace pbi
