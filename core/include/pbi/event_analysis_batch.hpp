#pragma once

#include "pbi/event_analysis.hpp"

namespace pbi {
/// 原执行端识别的显式规则覆盖；分析器不猜测identifier对应的战斗机制。
struct EventRuleOverride { std::string identifier; std::string value; };
/// 两次独立重算的原请求，禁止同revision、重复规则或空覆盖。
struct CounterfactualEventRequest {
  std::string baseline_revision;
  std::string counterfactual_revision;
  std::vector<EventRuleOverride> rule_overrides;
  EventQuery query;
  BattleSide observer = BattleSide::attacker;
};
/// 传给真实推演执行端的一次重算，基线规则覆盖为空。
struct EventInferenceRequest { std::string calculation_revision; std::vector<EventRuleOverride> rule_overrides; };
/// 同步真实重算端口；每调用必须返回独立拥有的完整图和唯一run ID，异常自然传播。
/// 重算期间如需协作取消，由端口捕获同一CancellationToken并传入真实构图器。
using EventInferenceRunner = std::function<EventAnalysisArtifact(const EventInferenceRequest&)>;
/// 原合同记录两次推演/构图与两个事件分析中的精确求解次数，不推测runner内部额外求解。
struct CounterfactualEventCost { std::size_t inference_runs; std::size_t graph_builds; std::size_t exact_solver_runs; };
/// 原反事实双结果和对照减基线差值；不把观察相关性自动解释为因果。
struct CounterfactualEventResult {
  CounterfactualEventRequest request;
  EventAnalysisResult baseline;
  EventAnalysisResult counterfactual;
  Rational win_probability_delta;
  Rational event_probability_delta;
  Rational event_win_joint_probability_delta;
  bool independent_revisions_verified;
  CounterfactualEventCost cost;
};
/// @param request 不同revision及显式规则覆盖；@param runner 原合同要求的真实独立重算端口。
/// @param cancellation 同源取消；@return 两次真实完整图分析及精确差值；身份不独立整体失败。
[[nodiscard]] CounterfactualEventResult AnalyzeCounterfactualEvents(const CounterfactualEventRequest& request,
    const EventInferenceRunner& runner, CancellationToken cancellation = {});

/// 一组已真实完成分析的配置与原完整空间权重，不等同战斗随机概率。
struct ConfigurationEventGroup {
  std::string configuration_id;
  Rational configuration_weight;
  EventAnalysisResult analysis;
};
/// 配置数量与原始配置分母权重的覆盖摘要，不因失败或未分析重新归一化。
struct ConfigurationEventCoverage {
  Integer total_configuration_count;
  std::size_t analyzed_configuration_count;
  std::size_t event_possible_configuration_count;
  Rational analyzed_configuration_weight;
  Rational event_possible_configuration_weight;
  Rational unresolved_configuration_weight;
};
/// 配置层覆盖与战斗层事件概率的完整原汇总，保留输入组顺序与逐组身份。
struct ConfigurationEventSummary {
  std::vector<ConfigurationEventGroup> groups;
  ConfigurationEventCoverage coverage;
  Rational event_probability;
  Rational event_win_joint_probability;
};
/// @param groups 已真实分析组，ID唯一且observer/query一致；@param total_configuration_count 原完整空间数量。
/// @param unresolved_weight 失败/截断/未分析原始权重；@param cancellation 同源取消。
/// @return 原完整分母上的精确混合指标和全部组；缺失权重或重复身份整体失败。
[[nodiscard]] ConfigurationEventSummary AggregateConfigurationEvents(std::vector<ConfigurationEventGroup> groups,
    Integer total_configuration_count, Rational unresolved_weight = Rational{0}, CancellationToken cancellation = {});
} // namespace pbi
