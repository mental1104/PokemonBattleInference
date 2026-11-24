#pragma once

#include "pbi/configuration_stats.hpp"

namespace pbi {
/// 原反向配置目标：攻击方需要击倒，防守方要求严格存活。
enum class ConfigurationGoalKind { attack, defense };
/// 原目标验收只选择最低或最高伤害档，不把它误当成随机概率。
enum class ConfigurationDamageRollPolicy { minimum, maximum };
/// 原静态目标使用的战斗快照，没有当前HP、进化性或临时状态字段。
struct ConfigurationGoalPokemon {
  std::vector<PokemonType> types;
  BattleStats stats;
  DamageAbility ability = DamageAbility::none;
  DamageItem item = DamageItem::none;
};
/// 已完成合法性/version-aware知识读取的一条目标，不持有SQL模型或知识库句柄。
struct ConfigurationDamageGoal {
  std::string goal_id;
  ConfigurationGoalKind kind;
  ConfigurationGoalPokemon target;
  DamageMove move;
  std::int32_t required_turns;
  std::optional<ConfigurationDamageRollPolicy> roll_policy;
};
/// 完整目标证据；防守失败时remaining_hp按原实现允许负数。
struct ConfigurationDamageGoalResult {
  std::string goal_id;
  ConfigurationGoalKind kind;
  bool satisfied;
  DamageResult damage;
  std::int64_t selected_damage;
  std::int32_t repetitions;
  Integer total_damage;
  std::int32_t hp_threshold;
  Integer remaining_hp;
  std::int32_t effective_attack;
  std::int32_t effective_defense;
  ConfigurationDamageRollPolicy roll_policy;
};
/// 原速度目标只比较固定参照的实际Speed，没有战斗状态/天气/道具修正。
struct ConfigurationSpeedGoal {
  std::string goal_id;
  std::int32_t target_speed;
};
/// 严格速度线证据，margin为零表示同速，仍不满足。
struct ConfigurationSpeedGoalResult {
  std::string goal_id;
  bool satisfied;
  std::int32_t subject_speed;
  std::int32_t target_speed;
  std::int64_t speed_margin;
};
/// 模板/EV搜索共享的固定subject知识，当前实际能力由Core使用候选投入计算。
struct ConfigurationGoalSubject {
  BattleStats base;
  std::vector<PokemonType> types;
  std::int32_t level = 50;
  DamageAbility ability = DamageAbility::none;
  DamageItem item = DamageItem::none;
};
/// 输入组装解析的原内置模板或不可变snapshot，不提前计算实际能力。
struct ConfigurationGoalTemplate {
  std::string preset_key;
  ConfigurationStatProfile profile;
};
/// 原确定性模板求解输入，显式allowed顺序和重复处理均属于Core。
struct ConfigurationTemplateSolveInput {
  ConfigurationGoalSubject subject;
  std::vector<ConfigurationGoalTemplate> templates;
  std::vector<std::string> allowed_stat_presets;
  std::vector<ConfigurationDamageGoal> goals;
  std::size_t max_candidates = 3;
  std::vector<ConfigurationSpeedGoal> speed_goals{};
};
/// 一套同时满足全部目标的模板代表，不用不同配置分别满足不同目标。
struct ConfigurationTemplateCandidate {
  std::string preset_key;
  BattleStats stats;
  std::vector<ConfigurationDamageGoalResult> goals;
  std::vector<ConfigurationSpeedGoalResult> speed_goals{};
};
/// 可达时只返回成功候选；不可达时保留原第一个失败模板的全部目标证据。
struct ConfigurationTemplateSolution {
  std::vector<ConfigurationTemplateCandidate> candidates;
  std::vector<ConfigurationDamageGoalResult> rejected_goals;
  std::vector<ConfigurationSpeedGoalResult> rejected_speed_goals{};
  /// @return 是否存在一套配置同时满足所有目标。
  [[nodiscard]] bool Reachable() const noexcept { return !candidates.empty(); }
};
/// 原静态DamageContext目标求值器；共享任意精度公式、固定策略与相克知识。
/// Multiscale/InnerFocus在该原静态上下文没有动态钩子，不改变现有damage入口或真实回合。
class ConfigurationGoalEvaluator {
public:
  /// @param policy 拥有的原规则集伤害策略；@param knowledge 拥有的完整所需相克知识。
  /// @param cancellation 共用单向取消令牌，不创建线程或全局状态。
  ConfigurationGoalEvaluator(DamagePolicy policy, TypeChartSnapshot knowledge,
      CancellationToken cancellation = {});
  /// @param subject 已计算候选快照；@param level 统一等级；@param goal 完整已准备目标。
  /// @return 原攻击>=HP/防守<HP的逐项证据；取消整体抛异常。
  [[nodiscard]] ConfigurationDamageGoalResult Evaluate(const ConfigurationGoalPokemon& subject,
      std::int32_t level, const ConfigurationDamageGoal& goal) const;
  /// @param stats 当前候选完整实际能力；@param goals 已准备实际Speed参照。
  /// @return 原逐项严格速度线证据，不修改候选或应用原未纳入的速度修正。
  [[nodiscard]] std::vector<ConfigurationSpeedGoalResult> EvaluateSpeedGoals(
      const BattleStats& stats, const std::vector<ConfigurationSpeedGoal>& goals) const;
  /// @param input 原模板、固定subject与全部目标；@return 真正搜索的候选或首失败证据。
  [[nodiscard]] ConfigurationTemplateSolution SolveTemplates(const ConfigurationTemplateSolveInput& input) const;
private:
  /// 观察共享取消，不返回貌似成功的部分候选。
  void CheckCancellation() const;
  DamagePolicy policy_;
  TypeChartSnapshot knowledge_;
  CancellationToken cancellation_;
};
} // namespace pbi
