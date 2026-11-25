#include "../src/event_analysis_batch_contract.hpp"
#include <iostream>

/// 无参数；逐行调用唯一正式事件codec与真实产品自动机，错误不带部分概率。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      const auto value = pbi::contract::Json::parse(line);
      if (value.at("kind") == "counterfactual_fixture") {
        // 仅差分端口夹具：原端口允许测试runner返回固定独立artifact；不是公开ABI操作。
        // 真正两次InferFixedBattle重算已由event_analysis_batch_test单独验收。
        const auto baseline = pbi::contract::ReadEventAnalysisRequest(value.at("baseline"), PBI_V1_MAX_GRAPH_NODES, PBI_V1_MAX_GRAPH_EDGES, {});
        const auto counterfactual = pbi::contract::ReadEventAnalysisRequest(value.at("counterfactual"), PBI_V1_MAX_GRAPH_NODES, PBI_V1_MAX_GRAPH_EDGES, {});
        std::vector<pbi::EventRuleOverride> overrides;
        for (const auto& rule : value.at("rule_overrides")) overrides.push_back({rule.at("identifier").get<std::string>(), rule.at("value").get<std::string>()});
        std::size_t calls = 0;
        const pbi::CounterfactualEventRequest request{baseline.artifact.calculation_revision, counterfactual.artifact.calculation_revision,
            std::move(overrides), baseline.query, baseline.observer};
        const auto result = pbi::AnalyzeCounterfactualEvents(request, [&](const pbi::EventInferenceRequest& call) {
          ++calls;
          return call.calculation_revision == baseline.artifact.calculation_revision ? baseline.artifact : counterfactual.artifact;
        });
        std::cout << pbi::contract::Json{{"baseline", pbi::contract::EventAnalysisResultJson(result.baseline, {})},
            {"counterfactual", pbi::contract::EventAnalysisResultJson(result.counterfactual, {})},
            {"win_probability_delta", pbi::contract::FractionJson(result.win_probability_delta)}, {"event_probability_delta", pbi::contract::FractionJson(result.event_probability_delta)},
            {"event_win_joint_probability_delta", pbi::contract::FractionJson(result.event_win_joint_probability_delta)},
            {"independent_revisions_verified", result.independent_revisions_verified}, {"actual_runner_calls", calls},
            {"computation_cost", {{"inference_run_count", result.cost.inference_runs}, {"graph_build_count", result.cost.graph_builds}, {"exact_solver_run_count", result.cost.exact_solver_runs}}}}.dump() << '\n';
      } else if (value.at("kind") == "configuration_event_analysis") {
        const auto request = pbi::contract::ReadConfigurationEventAnalysisRequest(value, PBI_V1_MAX_GRAPH_NODES, PBI_V1_MAX_GRAPH_EDGES, {});
        std::cout << pbi::contract::EvaluateConfigurationEventAnalysis(request, {}).dump() << '\n';
      } else {
        const auto request = pbi::contract::ReadEventAnalysisRequest(value, PBI_V1_MAX_GRAPH_NODES, PBI_V1_MAX_GRAPH_EDGES, {});
        std::cout << pbi::contract::EvaluateEventAnalysis(request, {}).dump() << '\n';
      }
    } catch (const std::exception& error) {
      std::cout << pbi::contract::Json{{"error", error.what()}}.dump() << '\n';
    }
  }
}
