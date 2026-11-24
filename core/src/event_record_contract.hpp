#pragma once

#include "json_contract.hpp"
#include "pbi/transitions.hpp"

namespace pbi::contract {
/// 正式turn/fixed_battle原始事件的唯一读取器，结构化业务事实必须与随机Identity完全一致。
/// @param value 完整拥有JSON事件对象；@return 领域拥有事件，不借用JSON或推测文案事实。
[[nodiscard]] PathEvent ReadPathEventValue(const Json& value);
/// 正式边的完整条件替代历史读取器，复用EventSummary的精确归一化与等价历史合并。
/// @param value 完整paths数组；@param stop 同源协作取消；@return 拥有完整事件的摘要。
[[nodiscard]] EventSummary ReadEventSummaryValue(const Json& value, CancellationToken stop);
/// projection专用事件摘要读取，复用同一事件事实校验，仅允许请求预算内的长数值。
/// @param value 完整paths数组；@param stop 同源取消；@return 精确拥有事件摘要，不剪裁历史或分数。
[[nodiscard]] EventSummary ReadProjectionEventSummaryValue(const Json& value, CancellationToken stop);
} // namespace pbi::contract
