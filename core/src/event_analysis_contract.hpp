#pragma once

#include "graph_contract.hpp"
#include "pbi/event_analysis.hpp"

namespace pbi::contract {
/// 正式事件查询请求，接受完整图与类型化路径元数据，不接受预计算事件概率。
struct EventAnalysisRequest {
  EventAnalysisArtifact artifact;
  EventQuery query;
  BattleSide observer;
};
/// @param value 正式event_analysis请求；@param available_nodes 本批原图节点余量。
/// @param available_edges 本批原图边余量；@param stop 同源取消。
/// @return 类型化拥有请求，预算仅限制既有ABI输入，不改纯产品自动机的原查询语义。
[[nodiscard]] EventAnalysisRequest ReadEventAnalysisRequest(const Json& value, std::size_t available_nodes,
    std::size_t available_edges, CancellationToken stop);
/// @param result Core真实完整事件结果；@param stop 同源取消；@return 与单图/配置组一致的唯一完整投影。
[[nodiscard]] Json EventAnalysisResultJson(const EventAnalysisResult& result, CancellationToken stop);
/// @param request 已验证原图/查询；@param stop 同源取消；@return 全部精确概率/分布/覆盖/实际成本。
[[nodiscard]] Json EvaluateEventAnalysis(const EventAnalysisRequest& request, CancellationToken stop);
} // namespace pbi::contract
