#pragma once

#include "event_analysis_contract.hpp"
#include "pbi/event_analysis_batch.hpp"

namespace pbi::contract {
/// 一组未执行分析的完整原图/查询与原配置空间权重，结果不能从外部伪造。
struct ConfigurationEventGroupRequest {
  std::string configuration_id;
  Rational configuration_weight;
  EventAnalysisRequest analysis;
};
/// 配置事件正式聚合请求，完整原分母与未分析权重独立保留。
struct ConfigurationEventAnalysisRequest {
  std::vector<ConfigurationEventGroupRequest> groups;
  Integer total_configuration_count;
  Rational unresolved_configuration_weight;
};
/// @param value 正式configuration_event_analysis操作；@param available_nodes 本批全部图共享节点余量。
/// @param available_edges 本批全部图共享边余量；@param stop 同源取消。
/// @return 未执行任何查询的拥有请求，不在codec计算配置混合概率。
[[nodiscard]] ConfigurationEventAnalysisRequest ReadConfigurationEventAnalysisRequest(const Json& value, std::size_t available_nodes,
    std::size_t available_edges, CancellationToken stop);
/// @param request 全部完整图/查询与原权重；@param stop 同源取消。
/// @return 每组真实产品图分析及原完整配置分母的覆盖和精确加权结果。
[[nodiscard]] Json EvaluateConfigurationEventAnalysis(const ConfigurationEventAnalysisRequest& request, CancellationToken stop);
} // namespace pbi::contract
