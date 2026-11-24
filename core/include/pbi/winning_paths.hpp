#pragma once

#include "pbi/state_graph_projection.hpp"

namespace pbi {
/// 原图提供的SCC身份；空列表保持原cycle reference.component_id=null，不另造展示身份。
struct WinningPathComponent { ComponentId id; std::vector<ProjectionNodeId> nodes; ComponentKind kind = ComponentKind::acyclic; };
/// 拥有完整原正式图的读取模型，不需要开放BattleGraph私有构造器。
struct WinningPathGraph {
  std::vector<StateGraphProjectionNode> nodes;
  std::vector<StateGraphProjectionEdge> edges;
  ProjectionNodeId root{0};
  std::vector<WinningPathComponent> components = {};
  std::vector<GraphTruncation> truncations = {};
};
/// 单侧配置身份只消费机械spec枚举；透明raw特性仍按原UNKNOWN显示和归并。
struct WinningPathConfigurationSide {
  std::int64_t pokemon_id;
  std::string name;
  std::int32_t level;
  std::string ability_identifier;
  std::string item_identifier;
  std::vector<std::int64_t> move_ids;
};
/// 原JSON/SHA-256配置身份，名字不进入摘要，招式按ID排序。
struct WinningPathConfiguration {
  std::string configuration_key;
  WinningPathConfigurationSide attacker;
  WinningPathConfigurationSide defender;
};
/// 一条事件历史的联合行动；与节点projection要求双方MOVE_SELECTED的严格分组合同不同。
struct WinningJointActionAlternative {
  std::optional<std::int64_t> attacker_move_id;
  std::optional<std::int64_t> defender_move_id;
  std::optional<std::string> attacker_source_identifier;
  std::optional<std::string> defender_source_identifier;
  /// @return 原四字段冒号连接身份，不包含伤害或HP结果。
  [[nodiscard]] std::string StableKey() const;
  /// @param other 只读原事实；@return 四字段完整相等，不仅比较可能碰撞的展示键。
  bool operator==(const WinningJointActionAlternative& other) const = default;
};
/// 一条正式边全部替代历史的行动集合，回合来自source实际state而非路径深度。
struct WinningJointActionStep {
  std::int64_t turn_number;
  std::optional<WinningJointActionAlternative> exact;
  std::vector<WinningJointActionAlternative> alternatives;
  /// @return 原turn-N:及按stable_key排序的候选身份。
  [[nodiscard]] std::string StableKey() const;
};
/// 不包含伤害数值和自由文本的原七类关键事件摘要。
struct WinningPathKeyEvent {
  BattleEventKind kind;
  std::optional<BattleSide> actor;
  std::optional<BattleSide> target;
  std::optional<std::int64_t> move_id;
  std::optional<std::string> source_identifier;
  /// @param other 原事件身份；@return 所有字段相等。
  bool operator==(const WinningPathKeyEvent& other) const = default;
};
/// 只记录真正经过的正式边，代表路径按单条原walk概率最大选择，同概率保留首条。
struct WinningPathStep { ProjectionNodeId source; ProjectionEdgeId edge; ProjectionNodeId target; };
/// 同配置、同联合行动序列的完整原聚合，所有计数/离散伤害使用任意精度。
struct WinningPathGroup {
  std::string path_key;
  std::int64_t terminal_turn;
  Rational probability;
  Integer raw_path_count;
  Integer raw_history_count_estimate;
  std::vector<std::string> terminal_reasons;
  std::vector<ProjectionNodeId> terminal_node_ids;
  std::vector<WinningJointActionStep> actions;
  std::vector<WinningPathStep> representative_path;
  std::vector<Integer> damage_values;
  std::vector<std::int32_t> attacker_remaining_hp_values;
  std::vector<std::int32_t> defender_remaining_hp_values;
  std::vector<WinningPathKeyEvent> key_events;
};
/// 当前页而非所有页的行动前缀树，子节点按完整action stable_key排序。
struct WinningPathPrefixNode {
  std::string prefix_key;
  std::size_t depth;
  std::optional<WinningJointActionStep> action;
  Rational probability{0};
  Integer raw_path_count{0};
  std::vector<std::string> terminal_path_keys;
  std::vector<WinningPathPrefixNode> children;
};
/// 有限DFS中的回边引用；不把循环walk无限展开，也不把有限覆盖冒称完整胜率。
struct WinningPathCycleReference {
  ProjectionNodeId source;
  ProjectionEdgeId edge;
  ProjectionNodeId target;
  std::size_t prefix_depth;
  std::optional<ComponentId> component;
};
/// 原唯一排序策略，未知策略必须在边界拒绝。
enum class WinningPathSort { shortest_high_probability };
/// 完整只读查询；offset来自Core私有cursor验证，不是Go生成的分页业务数据。
struct WinningPathQuery {
  std::string graph_id;
  std::string calculation_revision;
  BattleSide winner;
  std::size_t limit = 10;
  Integer offset = 0;
  WinningPathSort sort = WinningPathSort::shortest_high_probability;
  std::size_t max_traversed_walks = 100000;
};
/// 原完整结果；next_offset由Core codec编码为绑定图/版本/配置/胜者/排序的唯一cursor。
struct WinningPathGroupsResult {
  std::string graph_id;
  std::string calculation_revision;
  BattleSide winner;
  WinningPathSort sort;
  WinningPathConfiguration configuration;
  std::optional<Rational> winner_probability;
  Rational returned_probability;
  std::optional<Rational> returned_coverage;
  std::vector<WinningPathGroup> path_groups;
  WinningPathPrefixNode prefix_tree;
  std::vector<WinningPathCycleReference> cycle_references;
  std::optional<Integer> next_offset;
  bool has_more;
  bool query_complete;
  bool traversal_truncated;
};
/// @param graph 原连续节点正式图；@return 原配置完整DTO和唯一cfg-SHA身份。
/// @throws std::invalid_argument 缺少根或节点身份冲突。
[[nodiscard]] WinningPathConfiguration DescribeWinningPathConfiguration(const WinningPathGraph& graph);
/// @param graph 原正式构图器产物，借用期覆盖调用；@return 同一配置/SHA，不复制节点/边/事件。
[[nodiscard]] WinningPathConfiguration DescribeWinningPathConfiguration(const BattleGraph& graph);
/// 真实原用例：有限DFS、行动归并、精确图求解、稳定分页和当前页前缀。
/// @param graph 完整节点/边/原SCC/截断；@param query 唯一类型化查询。
/// @param stop 同源取消；@return 不重归一的完整原结果，循环/资源截断单独标记。
/// @throws std::invalid_argument 参数/图不合法；std::runtime_error 取消，不返回部分组。
[[nodiscard]] WinningPathGroupsResult ListWinningPathGroups(const WinningPathGraph& graph,
    const WinningPathQuery& query, CancellationToken stop = {});
/// 按需重建的正式typed图直接查询，不复制大图事件或经JSON往返。
/// @param graph 构图器拥有的完整正式图，只读借用至调用返回；@param query 同一原查询。
/// @param stop 同源取消；@return 同一算法的独立拥有小DTO，不保留graph借用。
[[nodiscard]] WinningPathGroupsResult ListWinningPathGroups(const BattleGraph& graph,
    const WinningPathQuery& query, CancellationToken stop = {});
} // namespace pbi
