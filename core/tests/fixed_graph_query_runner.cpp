#include "../src/fixed_graph_query_contract.hpp"
#include <iostream>

namespace {
/// 持有真实C ABI返回缓冲区，异常路径也按同一allocator释放。
struct Buffer {
 pbi_buffer_v1 value{};
 /// 析构无条件释放已拥有字节，不释放栈上的描述符。
 ~Buffer() { pbi_v1_buffer_release(&value); }
};
/// 无参数；@return 从真实ABI错误envelope读取版本，不在runner另写版本常量。
pbi::contract::Json Versions() {
 Buffer output;
 const std::string input = "{}";
 static_cast<void>(pbi_v1_compute(reinterpret_cast<const std::uint8_t*>(input.data()),input.size(),nullptr,&output.value));
 if (!output.value.data) throw std::runtime_error("missing native version envelope");
 const auto envelope=pbi::contract::Json::parse(output.value.data,output.value.data+output.value.size);
 return {{"engine_version",envelope.at("engine_version")},{"rules_version",envelope.at("rules_version")}};
}
} // namespace

/// 无参数；stdin逐行协议只调用正式reader/evaluator，versions只读取同库静态元数据。
/// @return 成功输入/稳定错误均逐行输出，不替代BFS/求解/导航/页游标算法。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      const auto value = pbi::contract::Json::parse(line);
      if (value.at("kind") == "versions") {
        std::cout << Versions().dump() << '\n';
      } else {
        const auto request = pbi::contract::ReadFixedGraphQueryRequest(value, 65536, 2000000, 8000000, {});
        std::cout << pbi::contract::EvaluateFixedGraphQuery(request, Versions().at("engine_version").get<std::string>(), Versions().at("rules_version").get<std::string>(), {}).dump() << '\n';
      }
    } catch (const std::exception& error) {
      std::cout << pbi::contract::Json{{"error", error.what()}}.dump() << '\n';
    }
  }
}
