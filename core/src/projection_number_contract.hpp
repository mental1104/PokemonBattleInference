#pragma once

#include "json_contract.hpp"
#include "pbi/cancellation.hpp"

namespace pbi::contract {
/// projection专用无损整数读取；不复用旧通用1024位保护而缩小原长游标合法范围。
/// @param value 十进制文本，符号/数字语法保持旧helper；@param stop 同源协作取消。
/// @return 独立任意精度整数；只受本协议整体请求字节预算约束，逐块解析可取消。
/// @throws RequestError 类型/语法非法、超过整个请求字节上限或已取消。
[[nodiscard]] inline Integer ReadProjectionInteger(const Json& value, CancellationToken stop) {
  if (!value.is_string()) throw RequestError(PBI_INVALID_INPUT_V1, "fraction components must be decimal strings");
  const auto& text = value.get_ref<const std::string&>();
  if (text.size() > PBI_V1_MAX_REQUEST_BYTES) throw RequestError(PBI_RESOURCE_LIMIT_V1, "projection integer exceeds request byte budget");
  const std::size_t first = !text.empty() && text.front() == '-' ? 1 : 0;
  if (first == text.size()) throw RequestError(PBI_INVALID_INPUT_V1, "invalid decimal integer");
  Integer result = 0;
  std::uint32_t chunk = 0;
  std::uint32_t power = 1;
  std::size_t digits = 0;
  for (std::size_t index = first; index < text.size(); ++index) {
    if ((index - first) % 1024 == 0 && stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "projection number read cancelled");
    if (text[index] < '0' || text[index] > '9') throw RequestError(PBI_INVALID_INPUT_V1, "invalid decimal integer");
    chunk = chunk * 10 + static_cast<std::uint32_t>(text[index] - '0');
    power *= 10;
    if (++digits == 9) {
      result = result * power + chunk;
      chunk = 0; power = 1; digits = 0;
    }
  }
  if (digits != 0) result = result * power + chunk;
  if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "projection number read cancelled");
  return first ? Integer{-result} : result;
}

/// projection专用精确分数读取；旧v1其他operation的默认1024位合同保持不变。
/// @param value numerator/denominator十进制文本对象；@param stop 同源协作取消。
/// @return 符号和最大公约数规范化后的精确值，负分母不泄漏底层异常。
[[nodiscard]] inline Rational ReadProjectionFraction(const Json& value, CancellationToken stop) {
  RequireFields(value, {"numerator", "denominator"});
  const auto numerator = ReadProjectionInteger(value.at("numerator"), stop);
  const auto denominator = ReadProjectionInteger(value.at("denominator"), stop);
  if (denominator == 0) throw RequestError(PBI_INVALID_INPUT_V1, "fraction denominator must not be zero");
  if (denominator < 0) return Rational{Integer{-numerator}, Integer{-denominator}};
  return Rational{numerator, denominator};
}
} // namespace pbi::contract
