#include "pbi/profile.hpp"
#include <limits>

namespace pbi {
namespace {
/// @param value 既有公式的 int64 输出；@return 已检查的能力快照字段，不静默截断。
std::int32_t StatValue(std::int64_t value) {
  if (value < std::numeric_limits<std::int32_t>::min() || value > std::numeric_limits<std::int32_t>::max()) throw std::overflow_error("profile stat exceeds int32 range");
  return static_cast<std::int32_t>(value);
}
} // namespace
BattleStats CalculateStats(const StatProfile& profile) {
  for (const auto axis : {profile.decreased, profile.increased}) {
    if (static_cast<int>(axis) < 2 || static_cast<int>(axis) > 6) throw UnsupportedRule("unsupported nature stat axis");
  }
  const auto non_hp = [&profile](NatureAxis axis, std::int32_t base, std::int32_t iv, std::int32_t ev) {
    // 同轴性格为中性；客户端不再决定 9/10/11，也不复制取整公式。
    const auto nature = profile.decreased == profile.increased ? NatureEffect::neutral : axis == profile.decreased ? NatureEffect::decreased : axis == profile.increased ? NatureEffect::increased : NatureEffect::neutral;
    return StatValue(CalculateNonHp({base, iv, ev, profile.level}, nature));
  };
  return {StatValue(CalculateHp({profile.base.hp, profile.ivs.hp, profile.evs.hp, profile.level})),
      non_hp(NatureAxis::attack, profile.base.attack, profile.ivs.attack, profile.evs.attack),
      non_hp(NatureAxis::defense, profile.base.defense, profile.ivs.defense, profile.evs.defense),
      non_hp(NatureAxis::special_attack, profile.base.special_attack, profile.ivs.special_attack, profile.evs.special_attack),
      non_hp(NatureAxis::special_defense, profile.base.special_defense, profile.ivs.special_defense, profile.evs.special_defense),
      non_hp(NatureAxis::speed, profile.base.speed, profile.ivs.speed, profile.evs.speed)};
}
} // namespace pbi
