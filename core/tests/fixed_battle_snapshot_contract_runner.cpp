#include "../src/fixed_battle_snapshot_contract.hpp"
#include <iostream>

/// 无参数；逐行只调用正式snapshot codec，保持输入/输出协议错误可观察。
/// @return 流故障非零；原语义拒绝由正式codec完整编码，不伪造成功节点。
int main() {
  std::string line;
  while(std::getline(std::cin,line)) {
    try {
      const auto value=pbi::contract::Json::parse(line);
      const auto request=pbi::contract::ReadFixedBattleSnapshotRequest(value,65536,{});
      std::cout << pbi::contract::EvaluateFixedBattleSnapshot(request,{}).dump() << '\n';
    } catch(const std::exception& error) { std::cout << pbi::contract::Json{{"error",error.what()}}.dump() << '\n'; }
  }
  return std::cin.bad() || !std::cout ? 1 : 0;
}
