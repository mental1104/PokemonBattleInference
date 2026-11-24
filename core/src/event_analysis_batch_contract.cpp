#include "event_analysis_batch_contract.hpp"

namespace pbi::contract {
namespace {
/// @param stop 同源令牌；取消时整次失败，不发布部分组汇总。
void CheckStop(CancellationToken stop) { if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "configuration event analysis cancelled"); }
} // namespace

ConfigurationEventAnalysisRequest ReadConfigurationEventAnalysisRequest(const Json& value, std::size_t available_nodes,
    std::size_t available_edges, CancellationToken stop) {
  CheckStop(stop);
  RequireSchema(value, {"kind", "groups", "total_configuration_count"}, {"unresolved_configuration_weight"});
  if (value.at("kind") != "configuration_event_analysis" || !value.at("groups").is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "invalid configuration event operation");
  ConfigurationEventAnalysisRequest request{{}, ReadDecimalInteger(value.at("total_configuration_count")),
      value.contains("unresolved_configuration_weight") ? ReadFraction(value.at("unresolved_configuration_weight")) : Rational{0}};
  for (const auto& group : value.at("groups")) {
    CheckStop(stop);
    RequireFields(group, {"configuration_id", "configuration_weight", "analysis"});
    auto analysis = ReadEventAnalysisRequest(group.at("analysis"), available_nodes, available_edges, stop);
    available_nodes -= analysis.artifact.graph.topology.Nodes().size();
    available_edges -= analysis.artifact.graph.topology.Edges().size();
    request.groups.push_back({group.at("configuration_id").get<std::string>(), ReadFraction(group.at("configuration_weight")), std::move(analysis)});
  }
  return request;
}

Json EvaluateConfigurationEventAnalysis(const ConfigurationEventAnalysisRequest& request, CancellationToken stop) {
  CheckStop(stop);
  std::vector<ConfigurationEventGroup> groups;
  for (const auto& group : request.groups) {
    CheckStop(stop);
    try {
      groups.push_back({group.configuration_id, group.configuration_weight,
          AnalyzeBattleEvents(group.analysis.artifact, group.analysis.query, group.analysis.observer, stop)});
    } catch (const std::runtime_error&) {
      CheckStop(stop);
      throw;
    }
  }
  const auto summary = AggregateConfigurationEvents(std::move(groups), request.total_configuration_count, request.unresolved_configuration_weight, stop);
  auto encoded = Json::array();
  for (const auto& group : summary.groups) {
    CheckStop(stop);
    encoded.push_back({{"configuration_id", group.configuration_id}, {"configuration_weight", FractionJson(group.configuration_weight)}, {"analysis", EventAnalysisResultJson(group.analysis, stop)}});
  }
  const auto& coverage = summary.coverage;
  return {{"kind", "configuration_event_analysis"}, {"groups", std::move(encoded)}, {"coverage", {{"total_configuration_count", coverage.total_configuration_count.str()},
      {"analyzed_configuration_count", coverage.analyzed_configuration_count}, {"event_possible_configuration_count", coverage.event_possible_configuration_count},
      {"analyzed_configuration_weight", FractionJson(coverage.analyzed_configuration_weight)}, {"event_possible_configuration_weight", FractionJson(coverage.event_possible_configuration_weight)},
      {"unresolved_configuration_weight", FractionJson(coverage.unresolved_configuration_weight)}}},
      {"weighted_metrics", {{"event_probability", FractionJson(summary.event_probability)}, {"event_win_joint_probability", FractionJson(summary.event_win_joint_probability)}}}};
}
} // namespace pbi::contract
