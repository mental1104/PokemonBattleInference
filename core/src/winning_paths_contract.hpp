#pragma once
#include "state_graph_projection_contract.hpp"
#include "pbi/winning_paths.hpp"

namespace pbi::contract {
/// 完整原图和查询；不透明cursor仅由Core解码，不接受Go算出的配置身份或分页offset。
struct WinningPathsRequest { WinningPathGraph graph; WinningPathQuery query; };
/// @param value owning codec已校验schema的小查询对象，含graph_id/revision/winner及原可选分页字段。
/// @param configuration 同一正式typed图的Core配置身份；@param stop 同源取消。
/// @return 唯一完整query/cursor绑定，不需要图JSON或复制事件；字段语义与rawgraph入口相同。
[[nodiscard]] WinningPathQuery ReadWinningPathQueryValue(const Json& value, const WinningPathConfiguration& configuration,
    CancellationToken stop);
/// @param result 同一纯用例独立拥有结果；@param stop 同源取消；@return 唯一原完整wire，包括Core生成cursor。
[[nodiscard]] Json WinningPathGroupsJson(const WinningPathGroupsResult& result, CancellationToken stop);
/// @param value 正式winning_paths操作；@param available_nodes 本批剩余正式图节点预算。
/// @param available_edges 本批剩余正式图边预算；@param stop 同源取消。
/// @return 唯一原图和已绑定cursor查询，未知字段/旧游标冲突明确拒绝。
[[nodiscard]] WinningPathsRequest ReadWinningPathsRequest(const Json& value, std::size_t available_nodes,
    std::size_t available_edges, CancellationToken stop);
/// @param request 完整只读请求；@param stop 同源取消；@return 原完整用例DTO并带kind，所有业务计算仅调用同一纯Core。
[[nodiscard]] Json EvaluateWinningPaths(const WinningPathsRequest& request, CancellationToken stop);
} // namespace pbi::contract
