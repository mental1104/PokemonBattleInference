#include "../src/winning_paths_contract.hpp"
#include <iostream>

/// 无参数；逐行调用正式Core codec和同一纯winning用例，错误独立返回以便比较旧409文案。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      const auto request = pbi::contract::ReadWinningPathsRequest(pbi::contract::Json::parse(line), 1000000, 4000000, {});
      std::cout << pbi::contract::EvaluateWinningPaths(request, {}).dump() << '\n';
    } catch (const std::exception& error) { std::cout << pbi::contract::Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
