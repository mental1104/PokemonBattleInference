#pragma once

#include "configuration_goals_contract.hpp"
#include "pbi/configuration_spread_search.hpp"

namespace pbi::contract {
/// 正式EV/IV/性格反推请求，只有未预先求解的知识和目标，复用模板目标上下文。
struct ConfigurationSpreadSearchRequest {
  ConfigurationSpreadSearchInput input;
  DamagePolicy policy;
  TypeChartSnapshot knowledge;
  std::int32_t generation;
};
/// @param value 正式configuration_spread_search输入；@param stop 同源取消。
/// @return 严格读取的拥有请求，不在codec分组性格、搜索EV或计算满足性。
[[nodiscard]] ConfigurationSpreadSearchRequest ReadConfigurationSpreadSearchRequest(const Json& value, CancellationToken stop);
/// @param request 完整已读取知识/目标；@param stop 同源取消。
/// @return 原实际WithSpeed搜索的完整候选、六项独立区间和双类不可达证据。
[[nodiscard]] Json EvaluateConfigurationSpreadSearch(const ConfigurationSpreadSearchRequest& request, CancellationToken stop);
} // namespace pbi::contract
