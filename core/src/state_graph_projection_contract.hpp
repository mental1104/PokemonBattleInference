#pragma once

#include "state_contract.hpp"
#include "pbi/state_graph_projection.hpp"

namespace pbi::contract {
/// 单节点分组查询的明确选择，只接受待展开组标识，不混合战报步骤参数。
struct ProjectionNodeQuery { std::vector<std::string> expanded_group_ids; };
/// 用户实际选中正式边的战报查询；边选择和深度都不依赖代表路径。
struct ProjectionStepQuery { ProjectionEdgeId edge_id; std::size_t depth; };
/// 一个原节点及其完整出边的拥有请求；step模式也允许只传所选原边以避免无关传输。
struct StateGraphProjectionRequest {
  StateGraphProjectionNode node;
  std::vector<StateGraphProjectionEdge> outgoing_edges;
  Rational cumulative_probability;
  std::variant<ProjectionNodeQuery, ProjectionStepQuery> query;
};
/// @param value 原完整图节点记录；@param stop 同源协作取消；@return 唯一拥有只读节点，不修改正式图。
[[nodiscard]] StateGraphProjectionNode ReadProjectionNodeValue(const Json& value, CancellationToken stop = {});
/// @param value 原完整图正式边记录；@param stop 同源取消；@return 唯一完整事件/精确概率读取结果。
[[nodiscard]] StateGraphProjectionEdge ReadProjectionEdgeValue(const Json& value, CancellationToken stop);
/// @param probability 非负精确概率；@return 唯一ties-to-even分数/decimal/percent展示，不用于概率计算。
[[nodiscard]] Json ExactProbabilityJson(const Rational& probability);
/// @param step Core真实正式边战报；@param stop 同源取消；@return 唯一完整战报DTO，任意精度身份/数值用文本。
[[nodiscard]] Json BattleReportStepJson(const BattleReportStep& step, CancellationToken stop = {});
/// @param value 正式state_graph_projection请求；@param available_edges 当前批可读取边数余量。
/// @param stop 协作取消；@return 完整类型请求，拒绝字段遗漏和元数据冲突。
[[nodiscard]] StateGraphProjectionRequest ReadStateGraphProjectionRequest(const Json& value,
    std::size_t available_edges, CancellationToken stop);
/// @param projection 同Core唯一读取结果；@param stop 同源取消。
/// @return 完整原application投影；任意精度事件数值保持十进制字符串供客户端无损解码。
[[nodiscard]] Json StateGraphProjectionJson(const BattleNodeProjection& projection, CancellationToken stop);
/// @param paths Core正式代表路径；@param stop 同源取消；@return 原完整代表路径DTO，身份使用无损十进制文本。
[[nodiscard]] Json RepresentativeBattlePathsJson(const std::vector<RepresentativeBattlePath>& paths, CancellationToken stop);
/// @param request 已验证拥有请求；@param stop 同源取消；@return 原子完成的节点投影，取消不返回部分结果。
[[nodiscard]] Json EvaluateStateGraphProjection(const StateGraphProjectionRequest& request, CancellationToken stop);
} // namespace pbi::contract
