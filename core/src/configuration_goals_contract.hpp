#pragma once

#include "json_contract.hpp"
#include "pbi/configuration_goals.hpp"

namespace pbi::contract {
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
