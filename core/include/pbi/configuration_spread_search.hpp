#pragma once

#include "pbi/configuration_goals.hpp"

namespace pbi {
/// 原NATURES知识的一行，完整25项由知识边界注入，不在Go按目标选择性格。
struct ConfigurationSearchNature {
  std::string identifier;
  std::string label;
  ConfigurationNature modifier;
};
/// 对当前伤害/速度目标等价的一项可选性格，顺序遵循原偏好。
struct ConfigurationNatureOption {
  std::string identifier;
  std::string label;
};
/// 保持其余五项代表值不变时，该单项可独立调整的闭区间。
struct ConfigurationStatRange {
  std::int32_t minimum;
  std::int32_t maximum;
};
/// HP/Atk/Def/SpAtk/SpDef/Speed固定顺序，不能把六区间任意组合解释为联合可行。
using ConfigurationSpreadRanges = std::array<ConfigurationStatRange, 6>;
/// 实际WithSpeed反推输入，能力和目标均未预先枚举或筛选。
struct ConfigurationSpreadSearchInput {
  ConfigurationGoalSubject subject;
  std::vector<ConfigurationDamageGoal> goals;
  std::vector<ConfigurationSpeedGoal> speed_goals;
  std::vector<ConfigurationSearchNature> natures;
  std::size_t max_candidates = 10;
};
/// 原4EV网格反推并经全部目标复核的一套实际代表及独立安全区间。
struct ConfigurationSpreadCandidate {
  std::string candidate_id;
  std::string nature_id;
  std::string nature_label;
  std::vector<ConfigurationNatureOption> nature_options;
  BattleStats evs;
  BattleStats ivs;
  ConfigurationSpreadRanges ev_ranges;
  ConfigurationSpreadRanges iv_ranges;
  BattleStats stats;
  std::vector<ConfigurationDamageGoalResult> goals;
  std::vector<ConfigurationSpeedGoalResult> speed_goals;
};
/// 真正EV/IV/性格搜索结果，无解保留原首性格6V/零EV基线的双类目标证据。
struct ConfigurationSpreadSolution {
  std::vector<ConfigurationSpreadCandidate> candidates;
  std::vector<ConfigurationDamageGoalResult> rejected_goals;
  std::vector<ConfigurationSpeedGoalResult> rejected_speed_goals;
  /// @return 是否存在同一代表同时满足全部目标，不代表放宽任何约束。
  [[nodiscard]] bool Reachable() const noexcept { return !candidates.empty(); }
};
/// @param input 原完整固定知识、双类目标和25性格；@param evaluator 与模板共用的真实目标求值器。
/// @param cancellation 同源取消；@return 原网格二分、HP权衡、总量过滤、排序与独立EV/IV区间。
/// 不预先列举配置状态，不加入原需求外预算；原max_candidates仅截取最终排序候选。
[[nodiscard]] ConfigurationSpreadSolution SearchConfigurationSpreads(const ConfigurationSpreadSearchInput& input,
    const ConfigurationGoalEvaluator& evaluator, CancellationToken cancellation = {});
} // namespace pbi
