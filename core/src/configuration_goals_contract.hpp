#pragma once

#include "json_contract.hpp"
#include "pbi/configuration_goals.hpp"

namespace pbi::contract {
/// @param value 共享Pokemon快照；@param level 原统一等级；@return 原静态目标实际消费的完整字段。
[[nodiscard]] ConfigurationGoalPokemon ReadConfigurationGoalPokemon(const Json& value, std::int32_t level);
/// @param value 原准备完成的伤害目标；@param level 原统一等级；@return 模板和EV搜索共用的同一目标读取结果。
[[nodiscard]] ConfigurationDamageGoal ReadConfigurationDamageGoal(const Json& value, std::int32_t level);
/// @param goals 完整伤害证据；@param generation 固定代际；@return 两搜索入口一致的目标/完整伤害投影。
[[nodiscard]] Json ConfigurationGoalResultsJson(const std::vector<ConfigurationDamageGoalResult>& goals, std::int32_t generation);
/// @param goals 全部速度证据；@return 不重算比较和margin的完整投影。
[[nodiscard]] Json ConfigurationSpeedGoalResultsJson(const std::vector<ConfigurationSpeedGoalResult>& goals);
/// @param stats Core六项实际能力；@return 同一稳定六字段输出。
[[nodiscard]] Json ConfigurationStatsJson(const BattleStats& stats);
/// 独立模板目标操作，保留准备后知识与原模板/双类目标命令，不修改.7既有操作。
struct ConfigurationTemplatesRequest {
  ConfigurationTemplateSolveInput input;
  DamagePolicy policy;
  TypeChartSnapshot knowledge;
  std::int32_t generation;
};
/// @param value 唯一正式configuration_templates操作；@param stop 同源取消。
/// @return 完整严格读取的拥有请求，不在codec筛选候选或计算能力/满足性。
[[nodiscard]] ConfigurationTemplatesRequest ReadConfigurationTemplatesRequest(const Json& value, CancellationToken stop);
/// @param request 已验证知识/命令；@param stop 同源取消；@return 原模板WithSpeed完整候选/首失败证据。
[[nodiscard]] Json EvaluateConfigurationTemplates(const ConfigurationTemplatesRequest& request, CancellationToken stop);
} // namespace pbi::contract
