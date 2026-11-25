#include "pbi/legacy_damage.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace pbi {
namespace {
/// @param left/right 原binary64乘数；@return 单独舍入的乘积，阻止ARM/x86编译器融合成与Python不同的FMA。
double Multiply(double left, double right) { volatile double value = left * right; return value; }
/// @param left/right 原binary64加数；@return 单独舍入的和，不跨阶段重排公式。
double Add(double left, double right) { volatile double value = left + right; return value; }
/// @param left/right 原binary64被除数/非零除数；@return 单独舍入商；除零显式invalid_argument。
double Divide(double left, double right) {
  if (right == 0) throw std::invalid_argument("legacy damage division by zero");
  volatile double value = left / right;
  return value;
}
/// 精确表示有限binary64，服务原Python int/round舍入，不改变历史浮点阶段。
struct BinaryFraction { Integer numerator; Integer denominator; };
/// @param significand 最多53位的原浮点尾数；@param offset 有限binary64给定的非负位偏移。
/// @return 独立构造的整数，不通过小整数原地移位触发Boost/GCC的SBO扩容别名路径。
Integer BinaryInteger(std::uint64_t significand, unsigned offset) {
  Integer result{0};
  for (unsigned bit = 0; bit < 53; ++bit) {
    if ((significand & (std::uint64_t{1} << bit)) != 0) boost::multiprecision::bit_set(result, offset + bit);
  }
  return result;
}
/// @param value 有限binary64；@return 只读值的精确二进制分数，非有限值拒绝。
BinaryFraction Exact(double value) {
  static_assert(std::numeric_limits<double>::is_iec559 && std::numeric_limits<double>::digits == 53);
  if (!std::isfinite(value)) throw std::overflow_error("legacy calculation is not finite");
  int exponent = 0;
  const auto fraction = std::frexp(std::abs(value), &exponent);
  // 有限binary64的frexp指数固定在此范围；明确界定移位大小，并按值构造，避免Boost原地扩容别名路径。
  if (exponent < -1073 || exponent > 1024) throw std::overflow_error("legacy binary64 exponent is out of range");
  const auto significand = static_cast<std::uint64_t>(std::ldexp(fraction, 53));
  const Integer magnitude = BinaryInteger(significand, exponent >= 53 ? static_cast<unsigned>(exponent - 53) : 0);
  const Integer denominator = BinaryInteger(1, exponent >= 53 ? 0 : static_cast<unsigned>(53 - exponent));
  return {std::signbit(value) ? Integer{-magnitude} : magnitude, denominator};
}
/// @param value 任意精度整数；@return 对应binary64，Python同样拒绝超出有限float范围的转换。
double Float(const Integer& value) {
  const auto result = value.convert_to<double>();
  if (!std::isfinite(result)) throw std::overflow_error("legacy integer exceeds finite float range");
  return result;
}
/// @param value 原链某一阶段浮点；@return Python int(value)的向零截断，保留超过int64的整数。
Integer Truncate(double value) {
  const auto exact = Exact(value);
  return exact.numerator / exact.denominator;
}
/// @param numerator/denominator 非负整数/正整数；@return 就近偶数舍入的新整数，不改变输入。
Integer NearestEven(const Integer& numerator, const Integer& denominator) {
  Integer quotient = numerator / denominator;
  const Integer remainder = numerator % denominator;
  const Integer doubled = remainder * 2;
  if (doubled > denominator || (doubled == denominator && quotient % 2 != 0)) ++quotient;
  return quotient;
}
/// @param numerator 原Python整数分子；@param denominator 非零整数分母；@return 正确舍入binary64商。
/// Python int/int不是先把两个大整数转float，直接如此转换会在百分比边界二次舍入。
double IntegerRatio(const Integer& numerator, const Integer& denominator) {
  if (denominator == 0) throw std::invalid_argument("legacy damage division by zero");
  if (numerator == 0) return 0;
  const bool negative = (numerator < 0) != (denominator < 0);
  Integer top = numerator < 0 ? -numerator : numerator;
  Integer bottom = denominator < 0 ? -denominator : denominator;
  int exponent = static_cast<int>(boost::multiprecision::msb(top)) - static_cast<int>(boost::multiprecision::msb(bottom));
  if (exponent >= 0) { if (top < (bottom << exponent)) --exponent; }
  else if ((top << -exponent) < bottom) --exponent;
  if (exponent > 1023) throw std::overflow_error("legacy integer division exceeds finite float range");
  const int shift = exponent < -1022 ? 1074 : 52 - exponent;
  if (shift >= 0) top <<= shift;
  else bottom <<= -shift;
  const Integer rounded = NearestEven(top, bottom);
  const auto result = std::ldexp(rounded.convert_to<double>(), exponent < -1022 ? -1074 : exponent - 52);
  if (!std::isfinite(result)) throw std::overflow_error("legacy integer division exceeds finite float range");
  return negative ? -result : result;
}
/// @param value 原uniform输出；@return Python round(value,2)，不能以round(value*100)/100替代0.855等边界。
double RoundHundredths(double value) {
  const auto exact = Exact(value);
  return IntegerRatio(NearestEven(Integer{exact.numerator * 100}, exact.denominator), Integer{100});
}
/// @param nature 旧原枚举或null；@return 五轴binary64倍率，特意保留Quiet无速度降低的历史事实。
std::array<double, 5> Nature(std::optional<LegacyNature> nature) {
  std::array<double, 5> result{1, 1, 1, 1, 1};
  if (!nature) return result;
  constexpr std::array<std::array<int, 2>, 25> changes{{{-1,-1},{0,1},{0,2},{0,3},{0,4},{1,0},{-1,-1},{1,2},{1,3},{1,4},
      {2,0},{2,1},{-1,-1},{2,3},{2,-1},{3,0},{3,1},{3,2},{-1,-1},{3,4},{4,0},{4,1},{4,2},{4,3},{-1,-1}}};
  const auto index = static_cast<std::size_t>(*nature);
  if (index >= changes.size()) throw std::invalid_argument("unknown legacy nature");
  const auto axes = changes[index];
  if (axes[0] >= 0) result[static_cast<std::size_t>(axes[0])] = 1.1;
  if (axes[1] >= 0) result[static_cast<std::size_t>(axes[1])] = 0.9;
  return result;
}
/// 单次责任链的三种伤害档位，按值传递避免修改输入快照或上一阶段对象。
struct DamageValues { Integer minimum; Integer maximum; Integer random; };
/// @param values 上一阶段拥有值；@param multiplier 原修正；@return 三档各自int截断后的新值。
DamageValues Scale(const DamageValues& values, double multiplier) {
  return {Truncate(Multiply(Float(values.minimum), multiplier)), Truncate(Multiply(Float(values.maximum), multiplier)),
      Truncate(Multiply(Float(values.random), multiplier))};
}
/// @param numerator 原binary64被除数；@return Python float //10，包括余数调整与商的吸附。
double FloorDivTen(double numerator) {
  const auto remainder = std::fmod(numerator, 10.0);
  auto quotient = Divide(numerator - remainder, 10.0);
  if (remainder < 0) quotient -= 1.0;
  if (quotient == 0) return std::copysign(0.0, Divide(numerator, 10.0));
  auto result = std::floor(quotient);
  if (quotient - result > 0.5) result += 1;
  return result;
}
/// @param damage 原整数伤害；@param hp 原整数HP；@return 原percent_decimal_places默认一位截断结果。
double Percent(const Integer& damage, const Integer& hp) {
  return Divide(FloorDivTen(Multiply(IntegerRatio(damage, hp), 10000.0)), 10.0);
}
} // namespace

LegacyStats CalculateLegacyStats(const LegacyPokemonInput& input) {
  if (input.basepoint.size() < 6) throw std::invalid_argument("List must be greater than or equal to 6");
  const auto nature = Nature(input.nature);
  LegacyStats result;
  for (std::size_t index = 0; index < result.size(); ++index) {
    // 原router忽略individual_values而使用director默认31；EV/4先为浮点，不能调用现代分层floor。
    const Integer fixed = Integer{input.base[index]} * 2 + 31;
    const auto raw = Add(Float(fixed), IntegerRatio(Integer{input.basepoint[index]}, Integer{4}));
    const auto scaled = Divide(Multiply(raw, Float(Integer{input.level})), 100.0);
    result[index] = index == 0 ? Truncate(Add(Add(scaled, 10.0), Float(Integer{input.level})))
        : Truncate(Multiply(Add(scaled, 5.0), nature[index - 1]));
  }
  return result;
}

LegacyDamageResult CalculateLegacyDamage(const LegacyDamageInput& input, const TypeChartSnapshot& knowledge) {
  if (!std::isfinite(input.random_unit) || input.random_unit < 0 || input.random_unit > 1) throw std::invalid_argument("legacy random unit must be between zero and one");
  if (input.attacker.types.empty() || input.attacker.types.size() > 2 || input.defender.types.empty() || input.defender.types.size() > 2) throw std::invalid_argument("legacy Pokemon requires one or two types");
  const auto attacker = CalculateLegacyStats(input.attacker);
  const auto defender = CalculateLegacyStats(input.defender);
  const auto uniform = Add(0.85, Multiply(1.0 - 0.85, input.random_unit));
  const auto multiplier = RoundHundredths(uniform);
  Integer base{0};
  if (input.move.category != DamageCategory::status) {
    if (input.move.category != DamageCategory::physical && input.move.category != DamageCategory::special) throw std::invalid_argument("unknown legacy move category");
    const auto attack_index = input.move.category == DamageCategory::physical ? 1U : 3U;
    const auto defense_index = input.move.category == DamageCategory::physical ? 2U : 4U;
    const auto factor = Divide(Float(Integer{Integer{input.attacker.level} * 2 + 10}), 250.0);
    const auto attack = Multiply(factor, Float(attacker[attack_index]));
    const auto ratio = Divide(attack, Float(defender[defense_index]));
    base = Truncate(Add(Multiply(ratio, Float(Integer{input.move.power})), 2.0));
  }
  DamageValues values{Truncate(Multiply(Float(base), 0.85)), base, Truncate(Multiply(Float(base), multiplier))};
  if (std::ranges::find(input.attacker.types, input.move.type) != input.attacker.types.end()) values = Scale(values, 1.5);
  double efficacy = 1;
  for (const auto type : input.defender.types) efficacy = Multiply(efficacy, Divide(knowledge.Efficacy(input.move.type, type), 100.0));
  values = Scale(values, efficacy);
  return {"", values.minimum, values.maximum, values.random, Percent(values.minimum, defender[0]), Percent(values.maximum, defender[0]),
      Percent(values.random, defender[0]), attacker, defender, multiplier};
}
} // namespace pbi
