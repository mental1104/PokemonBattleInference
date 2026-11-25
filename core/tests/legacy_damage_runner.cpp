#include "../src/legacy_damage_contract.hpp"
#include <iostream>

/// 无参数；逐行执行正式legacy codec/纯算法，只处理JSON边界，不生成随机数或调用旧Python。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << pbi::contract::EvaluateLegacyDamage(pbi::contract::ReadLegacyDamageRequest(pbi::contract::Json::parse(line))).dump() << '\n'; }
    catch (const std::exception& error) { std::cout << pbi::contract::Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
