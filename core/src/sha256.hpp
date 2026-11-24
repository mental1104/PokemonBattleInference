#pragma once

#include <string>

namespace pbi::detail {
/// 共享的内部SHA-256，供原case身份和原图groupID使用，不引入运行时/平台依赖。
/// @param text 完整原始字节，不规范化Unicode或JSON；@return 64位小写十六进制摘要。
/// @throws std::length_error 输入位数无法用FIPS180-4的uint64长度编码。
[[nodiscard]] std::string Sha256(const std::string& text);
} // namespace pbi::detail
