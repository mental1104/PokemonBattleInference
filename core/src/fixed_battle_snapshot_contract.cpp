#include "fixed_battle_snapshot_contract.hpp"
#include "projection_number_contract.hpp"
#include "state_graph_projection_contract.hpp"

namespace pbi::contract {
namespace {
/// @param stop 同源令牌；取消整体失败，不交付已完成前缀或半个展开组。
void Check(CancellationToken stop) {
  if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1,"fixed battle snapshot cancelled");
}
/// @param value 无损十进制或小JSON整数；@param stop 同源取消；@return 非负任意精度身份。
Integer Identity(const Json& value, CancellationToken stop) {
  const auto number=value.is_string()?ReadProjectionInteger(value,stop):Integer{ReadInteger(value)};
  if(number<0) throw RequestError(PBI_INVALID_INPUT_V1,"snapshot identity must be nonnegative");
  return number;
}
/// @param cursor 原用户路径；@return 相同顺序的十进制身份，不搜索代表前驱。
Json Cursor(const std::vector<ExplorationPathStep>& cursor) {
  auto steps=Json::array();
  for(const auto& step:cursor) steps.push_back({{"source_node_id",step.source_node_id.value.str()},
      {"edge_id",step.edge_id.value.str()},{"target_node_id",step.target_node_id.value.str()}});
  return {{"steps",std::move(steps)}};
}
} // namespace

FixedBattleSnapshotRequest ReadFixedBattleSnapshotRequest(const Json& value,std::size_t remaining_rolls,CancellationToken stop) {
  Check(stop);
  RequireSchema(value,{"kind","state","type_chart","attacker_policy","defender_policy","cursor"},{"turn_limits"});
  if(value.at("kind")!="fixed_battle_snapshot") throw RequestError(PBI_INVALID_INPUT_V1,"invalid snapshot operation kind");
  // 唯一正式回合reader拥有全部状态/静态知识/策略/回合执行保护，snapshot不引入第二份解码规则。
  Json turn{{"kind","battle_turn"},{"state",value.at("state")},{"type_chart",value.at("type_chart")},
      {"selection",{{"mode","policies"},{"attacker",value.at("attacker_policy")},{"defender",value.at("defender_policy")}}}};
  if(value.contains("turn_limits")) turn["turn_limits"]=value.at("turn_limits");
  auto parsed=ReadTurnRequest(turn,remaining_rolls);
  const auto& input=value.at("cursor");
  RequireSchema(input,{}, {"steps"});
  std::vector<ExplorationPathStep> cursor;
  if(input.contains("steps")) {
    if(!input.at("steps").is_array()) throw RequestError(PBI_INVALID_INPUT_V1,"snapshot cursor steps must be an array");
    for(const auto& step:input.at("steps")) {
      Check(stop);
      RequireFields(step,{"source_node_id","edge_id","target_node_id"});
      cursor.push_back({{Identity(step.at("source_node_id"),stop)},{Identity(step.at("edge_id"),stop)},{Identity(step.at("target_node_id"),stop)}});
    }
  }
  Check(stop);
  return {std::move(parsed),std::move(cursor)};
}

Json EvaluateFixedBattleSnapshot(const FixedBattleSnapshotRequest& request,CancellationToken stop) {
  try {
    Check(stop);
    const auto& policies=std::get<PolicyTurnActions>(request.turn.selection);
    const auto result=ExpandFixedBattleSnapshot(request.turn.state,request.turn.knowledge,policies.attacker,policies.defender,request.cursor,request.turn.limits,stop);
    auto projection=StateGraphProjectionJson(result.projection,stop);
    auto report=Json::array();
    for(const auto& step:result.report_steps) { Check(stop);report.push_back(BattleReportStepJson(step,stop)); }
    const auto cursor=Cursor(request.cursor);
    const auto terminal=projection.at("node").at("terminal");
    const std::string id="fixed-one-on-one-snapshot";
    const std::string revision="battle-inference.summary-exploration.v2";
    Json value{{"graph_id",id},{"calculation_revision",revision},{"cursor",cursor},
        {"node",std::move(projection["node"])},{"transition_groups",std::move(projection["transition_groups"])},
        {"cumulative_probability",projection.at("cumulative_probability")},{"breadcrumbs",cursor.at("steps")},{"terminal",terminal},
        {"battle_report",{{"graph_id",id},{"calculation_revision",revision},{"root_node_id","0"},
            {"current_node_id",result.projection.node.id.value.str()},{"depth",request.cursor.size()},
            {"cumulative_probability",projection.at("cumulative_probability")},{"steps",std::move(report)}}}};
    Check(stop);
    return {{"kind","fixed_battle_snapshot"},{"value",std::move(value)}};
  } catch(const SnapshotCursorError& error) {
    Check(stop);
    const auto code=error.Failure()==SnapshotCursorFailure::invalid_path?"fixed_battle_invalid_request":"fixed_battle_not_completely_solved";
    return {{"kind","fixed_battle_snapshot"},{"error",{{"http_status",422},{"code",code},{"message",error.what()}}}};
  } catch(const std::runtime_error&) { Check(stop);throw; }
}
} // namespace pbi::contract
