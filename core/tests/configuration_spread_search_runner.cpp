#include "../src/configuration_spread_search_contract.hpp"
#include <iostream>

/// 无参数；逐行调用正式EV搜索codec和纯算法，不执行Python或接收预计算候选。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      const auto request = pbi::contract::ReadConfigurationSpreadSearchRequest(pbi::contract::Json::parse(line), {});
      std::cout << pbi::contract::EvaluateConfigurationSpreadSearch(request, {}).dump() << '\n';
    } catch (const std::exception& error) {
      std::cout << pbi::contract::Json{{"error", error.what()}}.dump() << '\n';
    }
  }
}
