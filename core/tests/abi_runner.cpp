// 逐行调用真实 C ABI 的差分入口；不复制解析、公式或 JSON 输出逻辑。
#include "pbi_core.h"
#include <cstdint>
#include <iostream>
#include <string>

/// 本行响应的 RAII 所有者；即使输出流失败或抛出也归还 C allocator。
struct ResultBuffer {
  pbi_buffer_v1 value{};
  /// 析构时只释放由 Core 返回的缓冲区，不释放描述符本身。
  ~ResultBuffer() { pbi_v1_buffer_release(&value); }
};

/// 无参数；stdin 每行一批 JSON，stdout 每行一份实际 ABI 响应。
/// @return 输入/输出流故障时非零，协议错误保留其 JSON 后继续下一行。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    ResultBuffer output;
    static_cast<void>(pbi_v1_compute(reinterpret_cast<const std::uint8_t*>(line.data()), line.size(), nullptr, &output.value));
    if (!output.value.data) return 1;
    std::cout.write(reinterpret_cast<const char*>(output.value.data), static_cast<std::streamsize>(output.value.size));
    std::cout << '\n';
  }
  return std::cin.bad() || !std::cout ? 1 : 0;
}
