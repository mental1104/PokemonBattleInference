#include "pbi/fixed_battle_snapshot.hpp"

namespace pbi {
namespace {
/// @param stop 同源协作令牌；取消整体失败，不把已重放前缀当成完成结果。
void Check(CancellationToken stop) {
  if (stop.Requested()) throw std::runtime_error("fixed battle snapshot cancelled");
}
/// @param id 任意精度局部身份；@param state 拥有的即时状态；@return 原snapshot独立终局分类。
/// 此处不引入全图max_turns/cycle预算；原snapshot只按HP和明确terminal阶段分类。
StateGraphProjectionNode SnapshotNode(ProjectionNodeId id, BattleState state) {
  const auto& value = state.View();
  const bool first = value.attacker.View().current_hp == 0;
  const bool second = value.defender.View().current_hp == 0;
  GraphOutcome outcome = GraphOutcome::non_terminal;
  std::optional<GraphStopReason> reason;
  if (first && second) { outcome = GraphOutcome::draw; reason = BattleTermination::mutual_knockout; }
  else if (first) { outcome = GraphOutcome::defender_win; reason = BattleTermination::knockout; }
  else if (second) { outcome = GraphOutcome::attacker_win; reason = BattleTermination::knockout; }
  else if (value.phase == BattlePhase::terminal) { outcome = GraphOutcome::draw; reason = BattleTermination::no_legal_action; }
  return {std::move(id), std::move(state), outcome, reason};
}
/// @param node 当前拥有source；@param transitions 正式完整回合分布；@param stop 同源取消。
/// @return 保持原分布顺序的局部边，目标身份公式与原snapshot完全一致且不窄化。
std::vector<StateGraphProjectionEdge> SnapshotEdges(const StateGraphProjectionNode& node,
    std::span<const BattleTransition> transitions, CancellationToken stop) {
  std::vector<StateGraphProjectionEdge> result;
  result.reserve(transitions.size());
  for (std::size_t index = 0; index < transitions.size(); ++index) {
    Check(stop);
    const auto& value = transitions[index].View();
    result.push_back({{Integer{index}}, node.id, {(node.id.value + 1) * 10000 + index}, value.probability, value.events, value.source_key});
  }
  return result;
}
/// @param outcome 当前已分类节点；@return 是否属于原snapshot三种确定终局。
bool Terminal(GraphOutcome outcome) {
  return outcome == GraphOutcome::attacker_win || outcome == GraphOutcome::defender_win || outcome == GraphOutcome::draw;
}
/// @param cursor 原拥有步骤只读切片；在执行随机展开前按原ExplorationCursor合同校验完整连续性。
void ValidateCursor(std::span<const ExplorationPathStep> cursor) {
  Integer expected = 0;
  for (std::size_t depth = 0; depth < cursor.size(); ++depth) {
    const auto& step = cursor[depth];
    if (step.source_node_id.value < 0 || step.edge_id.value < 0 || step.target_node_id.value < 0) {
      throw SnapshotCursorError(SnapshotCursorFailure::invalid_path, "snapshot cursor identities must be nonnegative");
    }
    if (step.source_node_id.value != expected) {
      throw SnapshotCursorError(SnapshotCursorFailure::invalid_path, "exploration path is discontinuous at depth " + std::to_string(depth)
          + ": expected source " + expected.str() + ", got " + step.source_node_id.value.str());
    }
    expected = step.target_node_id.value;
  }
}
} // namespace

FixedBattleSnapshotResult ExpandFixedBattleSnapshot(const BattleState& initial, const TypeChartSnapshot& knowledge,
    ActionPolicy attacker_policy, ActionPolicy defender_policy, std::span<const ExplorationPathStep> cursor,
    TurnLimits turn_limits, CancellationToken stop) {
  Check(stop);
  ValidateCursor(cursor);
  const StandardTurnResolver resolver{knowledge};
  auto node = SnapshotNode({0}, initial);
  Rational cumulative{1};
  std::vector<BattleReportStep> report;
  report.reserve(cursor.size());
  for (std::size_t index = 0; index < cursor.size(); ++index) {
    Check(stop);
    // 原_replay直接展开每个选择步骤；确定终局只控制最后当前节点是否继续展示出边。
    const auto transitions = resolver.Expand(node.state, attacker_policy, defender_policy, turn_limits, stop);
    const auto edges = SnapshotEdges(node, transitions, stop);
    const auto& step = cursor[index];
    if (step.source_node_id != node.id) throw SnapshotCursorError(SnapshotCursorFailure::replay, "snapshot cursor source node does not match replayed path");
    if (step.edge_id.value >= Integer{edges.size()}) throw SnapshotCursorError(SnapshotCursorFailure::replay, "snapshot cursor edge_id is not available from current state");
    const auto ordinal = step.edge_id.value.convert_to<std::size_t>();
    const auto& edge = edges[ordinal];
    if (step.target_node_id != edge.target) throw SnapshotCursorError(SnapshotCursorFailure::replay, "snapshot cursor target node does not match replayed edge");
    auto detail = ProjectBattleGraphStep(node, edge, cumulative, index + 1, stop);
    cumulative = detail.cumulative_probability;
    report.push_back(std::move(detail));
    node = SnapshotNode(edge.target, transitions[ordinal].View().state);
  }
  Check(stop);
  std::vector<StateGraphProjectionEdge> outgoing;
  if (!Terminal(node.outcome)) {
    const auto transitions = resolver.Expand(node.state, attacker_policy, defender_policy, turn_limits, stop);
    outgoing = SnapshotEdges(node, transitions, stop);
  }
  const auto collapsed = ProjectBattleGraphNode(node, outgoing, cumulative, {}, stop);
  std::vector<std::string> ids;
  for (const auto& group : collapsed.transition_groups) ids.push_back(group.group_id);
  return {ProjectBattleGraphNode(node, outgoing, cumulative, ids, stop), std::move(report)};
}
} // namespace pbi
