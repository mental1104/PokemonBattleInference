#include "../src/state_graph_projection_contract.hpp"
#include "../src/turn_contract.hpp"
#include <iostream>

/// @return 逐行真实Core请求结果；解析/执行失败保持明确error，不返回部分结果。
/// 无参数；stdin和stdout都是NDJSON测试传输，不创建文件、网络、后台任务或业务替代器。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      const auto value = pbi::contract::Json::parse(line);
      if (value.at("kind") == "fixed_battle") {
        const auto request = pbi::contract::ReadFixedBattleRequest(value, 256, 2000000, 8000000);
        std::cout << pbi::contract::EvaluateFixedBattle(request, {}, {}).dump() << '\n';
      } else {
        const auto request = pbi::contract::ReadStateGraphProjectionRequest(value, 262144, {});
        std::cout << pbi::contract::EvaluateStateGraphProjection(request, {}).dump() << '\n';
      }
    } catch (const std::exception& error) {
      std::cout << pbi::contract::Json{{"error", error.what()}}.dump() << '\n';
    }
  }
}
