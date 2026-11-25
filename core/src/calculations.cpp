#include "pbi/calculations.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>
#include <vector>

namespace pbi {
namespace {

/// 对正分母做数学 floor；cpp_int 除法本身向零截断，负输入需要再减一。
/// @param numerator 已有所有权的整数分子，不修改调用方。
/// @param denominator 严格正分母。
/// @return 向下取整的新任意精度整数。
Integer FloorDivide(const Integer& numerator, const Integer& denominator) {
  Integer quotient = numerator / denominator;
  if (numerator < 0 && numerator % denominator != 0) {
    --quotient;
  }
  return quotient;
}

/// 在公开整数结果边界检查溢出，防止转换静默截断。
/// @param value 只读任意精度计算结果。
/// @return int64 结果；越界抛出 std::overflow_error。
std::int64_t ToInt64(const Integer& value) {
  if (value < std::numeric_limits<std::int64_t>::min() ||
      value > std::numeric_limits<std::int64_t>::max()) {
    throw std::overflow_error("stat result exceeds int64 range");
  }
  return value.convert_to<std::int64_t>();
}

/// 计算性格和 HP 分支之前共享的 floor 值。
/// @param input 只读原始能力配置。
/// @return floor((2*base + iv + floor(ev/4))*level/100)。
Integer BaseStat(const StatInput& input) {
  const Integer base = Integer{2} * input.base + input.iv +
                       FloorDivide(Integer{input.ev}, Integer{4});
  return FloorDivide(Integer{base * input.level}, Integer{100});
}

/// 将有限性格效果转换为十分制分子，拒绝未知规则。
/// @param effect 类型化标准性格效果。
/// @return 9、10 或 11；未知枚举值抛出 std::invalid_argument。
int NatureTenths(NatureEffect effect) {
  switch (effect) {
  case NatureEffect::decreased:
    return 9;
  case NatureEffect::neutral:
    return 10;
  case NatureEffect::increased:
    return 11;
  }
  throw std::invalid_argument("unsupported nature effect");
}

} // namespace

std::int64_t CalculateHp(const StatInput& input) {
  return ToInt64(Integer{BaseStat(input) + input.level + 10});
}

std::int64_t CalculateNonHp(const StatInput& input, NatureEffect nature) {
  const Integer raw = BaseStat(input) + 5;
  return ToInt64(FloorDivide(Integer{raw * NatureTenths(nature)}, Integer{10}));
}

std::int64_t ApplyStatStage(std::int64_t value, std::int32_t stage) {
  if (value <= 0) {
    throw std::invalid_argument("stat value must be a positive integer");
  }
  if (stage < -6 || stage > 6) {
    throw std::invalid_argument("stat stage must be between -6 and 6");
  }
  const Integer numerator = stage >= 0 ? 2 + stage : 2;
  const Integer denominator = stage >= 0 ? 2 : 2 - stage;
  const Integer result = Integer{value} * numerator / denominator;
  return ToInt64(result < 1 ? Integer{1} : result);
}

KoChance EstimateKoChance(std::span<const std::int64_t> rolls,
                          std::int32_t defender_hp) {
  if (rolls.empty()) {
    throw std::invalid_argument("rolls must not be empty");
  }
  if (defender_hp <= 0) {
    throw std::invalid_argument("defender_hp must be greater than 0");
  }
  // 排序后的每个槽仍保留其权重；二分统计有序对，避免 Python 的 O(n^2) 枚举。
  std::vector<std::int64_t> sorted(rolls.begin(), rolls.end());
  std::sort(sorted.begin(), sorted.end());
  const Integer count = sorted.size();
  const Integer ohko_hits = sorted.end() -
                            std::lower_bound(sorted.begin(), sorted.end(), defender_hp);
  Integer two_hits = 0;
  for (const auto first : sorted) {
    // 新伤害入口返回 int64 档位；差值和二击保证判定使用任意精度，避免边界溢出。
    const Integer threshold = Integer{defender_hp} - first;
    two_hits += sorted.end() -
                std::lower_bound(sorted.begin(), sorted.end(), threshold,
                    [](std::int64_t value, const Integer& limit) { return Integer{value} < limit; });
  }
  return {Rational{ohko_hits, count}, Rational{two_hits, Integer{count * count}},
          sorted.front() >= defender_hp, Integer{sorted.front()} * 2 >= defender_hp};
}

} // namespace pbi
