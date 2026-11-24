#pragma once

#include "json_contract.hpp"
#include "pbi/legacy_damage.hpp"

namespace pbi::contract {
/// 独立旧API的拥有请求；知识与raw随机事实显式注入，不在codec读取数据库或产生随机数。
struct LegacyDamageRequest { LegacyDamageInput input; TypeChartSnapshot knowledge; };
/// @param value 完整legacy_damage操作；@return 严格类型转换后的拥有请求，未知/非整数字段拒绝。
[[nodiscard]] LegacyDamageRequest ReadLegacyDamageRequest(const Json& value);
/// @param request 已验证拥有请求；@return 原七字段及独立准备证据，不改变现代damage合同。
[[nodiscard]] Json EvaluateLegacyDamage(const LegacyDamageRequest& request);
} // namespace pbi::contract
