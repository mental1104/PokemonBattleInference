#include "pbi/fixed_battle_snapshot.hpp"
#include "../src/projection_number_contract.hpp"
#include "../src/state_graph_projection_contract.hpp"
#include "../src/turn_contract.hpp"
#include <iostream>

/// 无参数；逐行只解码完整真实策略回合与原cursor，调用唯一snapshot纯域后机械编码。
/// @return 输入/纯域失败仍逐行保留原诊断，输出流失败返回非零。
int main() {
  using namespace pbi;
  using namespace pbi::contract;
  std::string line;
  while (std::getline(std::cin,line)) {
    try {
      const auto value=Json::parse(line);
      const auto turn=ReadTurnRequest(value.at("turn"),65536);
      const auto policies=std::get<PolicyTurnActions>(turn.selection);
      std::vector<ExplorationPathStep> cursor;
      for (const auto& step:value.at("cursor")) cursor.push_back({{ReadProjectionInteger(step.at("source_node_id"),{})},
          {ReadProjectionInteger(step.at("edge_id"),{})},{ReadProjectionInteger(step.at("target_node_id"),{})}});
      const auto result=ExpandFixedBattleSnapshot(turn.state,turn.knowledge,policies.attacker,policies.defender,cursor,turn.limits);
      auto report=Json::array();
      for (const auto& step:result.report_steps) report.push_back(BattleReportStepJson(step));
      std::cout << Json{{"projection",StateGraphProjectionJson(result.projection,{})},{"report_steps",std::move(report)}}.dump() << '\n';
    } catch(const std::exception& error) { std::cout << Json{{"error",error.what()}}.dump() << '\n'; }
  }
  return std::cin.bad() || !std::cout ? 1 : 0;
}
