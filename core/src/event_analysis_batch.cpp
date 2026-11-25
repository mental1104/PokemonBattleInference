#include "pbi/event_analysis_batch.hpp"
#include <cctype>
#include <set>

namespace pbi {
namespace {
/// @param stop 同源取消；取消整体失败，不发布部分配置汇总。
void CheckStop(CancellationToken stop) { if (stop.Requested()) throw std::runtime_error("event batch analysis cancelled"); }
/// @param value 业务稳定身份；@return 非空且没有首尾ASCII空白。
bool Normalized(const std::string& value) {
  return !value.empty() && !std::isspace(static_cast<unsigned char>(value.front())) && !std::isspace(static_cast<unsigned char>(value.back()));
}
} // namespace

CounterfactualEventResult AnalyzeCounterfactualEvents(const CounterfactualEventRequest& request,
    const EventInferenceRunner& runner, CancellationToken cancellation) {
  CheckStop(cancellation);
  if (!runner || !Normalized(request.baseline_revision) || !Normalized(request.counterfactual_revision) ||
      request.baseline_revision == request.counterfactual_revision || request.rule_overrides.empty())
    throw std::invalid_argument("counterfactual event analysis requires distinct revisions and explicit overrides");
  std::set<std::string> identifiers;
  for (const auto& rule : request.rule_overrides) {
    if (!Normalized(rule.identifier) || !Normalized(rule.value) || !identifiers.insert(rule.identifier).second)
      throw std::invalid_argument("counterfactual rule overrides must have normalized unique identifiers and values");
  }
  auto baseline_artifact = runner({request.baseline_revision, {}});
  CheckStop(cancellation);
  auto counterfactual_artifact = runner({request.counterfactual_revision, request.rule_overrides});
  CheckStop(cancellation);
  if (baseline_artifact.calculation_revision != request.baseline_revision || counterfactual_artifact.calculation_revision != request.counterfactual_revision)
    throw std::invalid_argument("counterfactual runner returned an unexpected revision");
  if (baseline_artifact.inference_run_id == counterfactual_artifact.inference_run_id)
    throw std::invalid_argument("counterfactual analysis requires independent inference run IDs");
  auto baseline = AnalyzeBattleEvents(baseline_artifact, request.query, request.observer, cancellation);
  auto counterfactual = AnalyzeBattleEvents(counterfactual_artifact, request.query, request.observer, cancellation);
  const auto win_delta = counterfactual.baseline_win - baseline.baseline_win;
  const auto event_delta = counterfactual.event_probability - baseline.event_probability;
  const auto joint_delta = counterfactual.event_win_joint_probability - baseline.event_win_joint_probability;
  const auto solves = baseline.cost.exact_solver_runs + counterfactual.cost.exact_solver_runs;
  return {request, std::move(baseline), std::move(counterfactual), win_delta, event_delta, joint_delta, true, {2, 2, solves}};
}

ConfigurationEventSummary AggregateConfigurationEvents(std::vector<ConfigurationEventGroup> groups,
    Integer total_configuration_count, Rational unresolved_weight, CancellationToken cancellation) {
  CheckStop(cancellation);
  if (total_configuration_count <= 0 || Integer{groups.size()} > total_configuration_count)
    throw std::invalid_argument("configuration event group count exceeds the positive full-space count");
  if (unresolved_weight < Rational{0} || unresolved_weight > Rational{1}) throw std::invalid_argument("unresolved configuration weight must be in [0, 1]");
  std::set<std::string> identifiers;
  Rational analyzed_weight{0}, possible_weight{0}, event_probability{0}, joint_probability{0};
  std::size_t possible_count = 0;
  for (const auto& group : groups) {
    CheckStop(cancellation);
    if (!Normalized(group.configuration_id) || !identifiers.insert(group.configuration_id).second)
      throw std::invalid_argument("configuration event IDs must be normalized and unique");
    if (group.configuration_weight <= Rational{0} || group.configuration_weight > Rational{1})
      throw std::invalid_argument("configuration event weight must be in (0, 1]");
    if (group.analysis.observer != groups.front().analysis.observer || group.analysis.query != groups.front().analysis.query)
      throw std::invalid_argument("configuration analyses must share observer and event query");
    analyzed_weight += group.configuration_weight;
    if (group.analysis.event_probability > Rational{0}) { ++possible_count; possible_weight += group.configuration_weight; }
    event_probability += group.configuration_weight * group.analysis.event_probability;
    joint_probability += group.configuration_weight * group.analysis.event_win_joint_probability;
  }
  if (analyzed_weight + unresolved_weight != Rational{1}) throw std::invalid_argument("analyzed and unresolved configuration weights must sum exactly to one");
  ConfigurationEventCoverage coverage{std::move(total_configuration_count), groups.size(), possible_count, analyzed_weight, possible_weight, std::move(unresolved_weight)};
  return {std::move(groups), std::move(coverage), event_probability, joint_probability};
}
} // namespace pbi
