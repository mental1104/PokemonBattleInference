#pragma once

#include "pbi/battle_graph.hpp"
#include <span>

namespace pbi {
/// 只读投影/快照的任意精度节点身份，正式图索引不因此改为大整数。
struct ProjectionNodeId {
  Integer value;
  /// @param other 只读身份；@return 完整数值身份相等，不经size_t或浮点。
  bool operator==(const ProjectionNodeId& other) const = default;
};
/// 只读投影/快照的任意精度边身份，与节点身份保持不同类型。
struct ProjectionEdgeId {
  Integer value;
  /// @param other 只读身份；@return 完整数值身份相等。
  bool operator==(const ProjectionEdgeId& other) const = default;
  /// @param other 只读身份；@return 原整数排序，用于正式边稳定呈现。
  bool operator<(const ProjectionEdgeId& other) const { return value < other.value; }
};
/// 原正式图或即时快照的只读拥有节点；不需要伪造StateKey或可写BattleGraph。
struct StateGraphProjectionNode {
  ProjectionNodeId id;
  BattleState state;
  GraphOutcome outcome;
  std::optional<GraphStopReason> reason;
};
/// 原完整边记录的只读拥有值，事件历史/权重不因图身份格式转换而丢失。
struct StateGraphProjectionEdge {
  ProjectionEdgeId id;
  ProjectionNodeId source;
  ProjectionNodeId target;
  Rational probability;
  EventSummary events;
  std::optional<std::string> source_key;
};
/// @param node 原正式图节点；@return 独立拥有只读投影记录，不修改正式图或索引。
[[nodiscard]] StateGraphProjectionNode ProjectionRecord(const BattleGraphNode& node);
/// @param edge 原正式图边；@return 完整拥有事件/概率记录，标准小索引精确提升为Integer。
[[nodiscard]] StateGraphProjectionEdge ProjectionRecord(const BattleGraphEdge& edge);

/// 原节点投影的六类分组；排序顺序也是原界面公开顺序。
enum class TransitionGroupKind { action_selection, action_order, hit_check, damage_distribution, secondary_effect, composite };
/// 从MOVE_SELECTED事实读取的行动身份；action_type保留事件来源原文，兼容旧未知来源。
struct JointActionDetail {
  BattleSide side;
  std::string action_type;
  std::optional<std::int64_t> move_id;
  /// @param other 只读身份；@return 三个原始身份字段是否相同。
  bool operator==(const JointActionDetail& other) const = default;
};
/// 伤害档位与真实扣血事实配对；伤害值保持任意精度，不重新计算伤害公式。
struct DamageRandomMetadata {
  std::size_t raw_roll_index;
  Integer raw_roll_value;
  Integer final_damage;
  Integer actual_hp_loss;
  /// @param other 只读记录；@return 全部原始档位/伤害事实是否相同。
  bool operator==(const DamageRandomMetadata& other) const = default;
};
/// 原行动读取模型的四种执行结果，不把未执行等同于miss。
enum class ActionResolutionStatus { executed, blocked, cancelled, passed };
/// 一侧从业务事实得到的最终行动结果，不执行新回合或推测缺失命中值。
struct ActionResolutionDetail {
  JointActionDetail action;
  std::optional<Integer> order_position;
  ActionResolutionStatus status;
  std::optional<bool> hit;
  std::optional<std::string> reason;
  /// @param other 只读结果；@return 所有执行事实是否相同。
  bool operator==(const ActionResolutionDetail& other) const = default;
};
/// 状态效果的两类真实结果，与是否存在完整状态门禁实现无关。
enum class StatusEffectResult { applied, prevented };
/// 从STATUS_APPLIED/PREVENTED事件读取的效果摘要，不补充未发生事实。
struct StatusEffectSummary {
  StatusEffectResult result;
  std::optional<BattleSide> source_side;
  std::optional<BattleSide> target_side;
  std::optional<std::string> source_identifier;
  /// @param other 只读状态事实；@return 所有字段是否相同。
  bool operator==(const StatusEffectSummary& other) const = default;
};
/// 原紧凑结果保留同速随机和确定优先级/速度排序的区别。
enum class ActionOrderReason { speed_tie_random, priority_modifier_speed };
/// 仅把执行结果、最终伤害和目标相同的路径合并；离散档位不是连续区间。
struct CompactRandomResult {
  ProjectionNodeId target_node_id;
  std::vector<ActionResolutionDetail> action_resolutions;
  ActionOrderReason order_reason;
  std::optional<bool> critical_hit;
  std::vector<Integer> raw_roll_values;
  std::vector<Integer> final_damage_values;
  std::vector<Integer> actual_hp_losses;
  std::vector<StatusEffectSummary> status_effects;
  std::size_t path_count;
};
/// 一条替代路径的展示事实，隐藏内部联合行动概率事件但保留其他custom事件。
struct TransitionEventPathDetail {
  std::vector<TransitionEvent> random_results;
  std::vector<DamageRandomMetadata> damage_rolls;
  std::vector<BattleEvent> battle_events;
};
/// 原标签字段按首次出现去重，不能用排序集合改变界面呈现顺序。
struct TransitionLabelFields {
  std::vector<std::int64_t> selected_move_ids;
  std::vector<BattleSide> acting_sides;
  std::vector<BattleSide> target_sides;
  std::vector<std::string> result_keys;
  std::vector<std::string> source_identifiers;
};
/// 某联合行动中的正式状态边；三类概率分别为条件随机、联合和根到当前后继。
struct TransitionOutcome {
  ProjectionEdgeId edge_id;
  ProjectionNodeId target_node_id;
  Rational probability;
  Rational joint_probability;
  Rational cumulative_probability;
  TransitionLabelFields label_fields;
  std::vector<Integer> raw_random_values;
  std::vector<TransitionEvent> random_results;
  std::vector<DamageRandomMetadata> damage_rolls;
  std::vector<CompactRandomResult> compact_results;
  std::vector<std::vector<BattleEvent>> battle_event_paths;
  std::vector<TransitionEventPathDetail> event_paths;
};
/// 分组折叠时的伤害范围；无合法档位事实时四项全为空，不伪造零伤害。
struct TransitionGroupSummary {
  std::optional<Integer> minimum_damage;
  std::optional<Integer> maximum_damage;
  std::optional<Integer> minimum_hp_loss;
  std::optional<Integer> maximum_hp_loss;
};
/// 原稳定groupID和精确选招概率，只有明确展开的组包含outcomes。
struct TransitionGroup {
  std::string group_id;
  TransitionGroupKind kind;
  std::string label_key;
  Rational selection_probability;
  std::optional<JointActionDetail> attacker_action;
  std::optional<JointActionDetail> defender_action;
  std::size_t raw_result_count;
  std::size_t distinct_outcome_count;
  TransitionGroupSummary summary;
  bool expanded;
  std::vector<TransitionOutcome> outcomes;
};
/// 拥有的单节点读取结果；节点保留完整Core状态，JSON边界负责机械字段投影。
struct BattleNodeProjection {
  StateGraphProjectionNode node;
  Rational cumulative_probability;
  std::vector<TransitionGroup> transition_groups;
  bool has_outgoing_edges;
};
/// 按用户实际选择的一条正式边生成的战报步骤，不使用节点的代表前驱路径。
struct BattleReportStep {
  std::size_t depth;
  ProjectionNodeId source_node_id;
  ProjectionEdgeId edge_id;
  ProjectionNodeId target_node_id;
  Rational edge_probability;
  Rational cumulative_probability;
  std::vector<TransitionEventPathDetail> event_paths;
};
/// 为长cursor和循环路径提供原线性战报步骤；不做跨步骤事件笛卡尔积。
/// @param node 原source节点；@param edge 同图原正式边，必须从node出发。
/// @param cumulative_probability 根到source的精确累计值；@param depth 当前一步的正深度。
/// @param stop 同源协作取消；@return 拥有全部替代历史和精确新累计概率的一步战报。
/// @throws std::invalid_argument 边不属于source、概率非法或深度为零。
[[nodiscard]] BattleReportStep ProjectBattleGraphStep(const StateGraphProjectionNode& node, const StateGraphProjectionEdge& edge,
    const Rational& cumulative_probability, std::size_t depth, CancellationToken stop = {});

/// 原代表路径中一个正式节点的轻量展示，事件标签来自前驱正式边首历史的Identity。
struct RepresentativePathStep {
  ProjectionNodeId node_id;
  std::int64_t turn_number;
  BattlePhase phase;
  std::int32_t attacker_hp;
  std::int32_t defender_hp;
  GraphOutcome outcome;
  std::vector<std::string> events;
};
/// 每种已实际出现终局的首条代表路径，不替代用户真实浏览cursor。
struct RepresentativeBattlePath {
  std::string reference;
  GraphOutcome outcome;
  std::vector<RepresentativePathStep> steps;
};
/// 复用正式图的首次前驱关系生成原最多三条代表路径，选择与搜索均属于Core。
/// @param graph 已完整拥有的正式图；@param stop 同源取消，不返回部分终局路径。
/// @return 按attacker-win、defender-win、draw顺序的现存终局路径；不推测未出现终局。
[[nodiscard]] std::vector<RepresentativeBattlePath> ProjectRepresentativeBattlePaths(const BattleGraph& graph, CancellationToken stop = {});

/// 只读取一个原正式节点及其完整出边，避免把整幅图回送给ABI而缩小可浏览范围。
/// @param node 只读当前节点，状态/规则必须来自同一冻结图。
/// @param outgoing_edges 同节点全部出边的只读切片，保持原事件历史；不会修改或重新搜索图。
/// @param cumulative_probability 已由Core对游标算出的精确累计值，必须属于[0,1]。
/// @param expanded_group_ids 本次展开的规范化groupID；不存在但合法的ID保持原行为忽略。
/// @param stop 同源协作取消，取消抛runtime_error且不返回半套投影。
/// @return 独立拥有节点和分组，组身份/概率/条件归并都由本Core唯一计算。
/// @throws std::invalid_argument 元数据冲突、缺失或不能精确重建正式边概率。
[[nodiscard]] BattleNodeProjection ProjectBattleGraphNode(const StateGraphProjectionNode& node,
    std::span<const StateGraphProjectionEdge> outgoing_edges, const Rational& cumulative_probability = Rational{1},
    std::span<const std::string> expanded_group_ids = {}, CancellationToken stop = {});
} // namespace pbi
