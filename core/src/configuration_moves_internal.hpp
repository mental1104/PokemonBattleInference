#pragma once
#include "pbi/configuration_moves.hpp"

namespace pbi::detail {
/// 同一move provider的私有composition入口；普通单维API仍固定原standard语义，不新增冲突输入字段。
/// @param input 原合法候选/命令；@param factory 本次单侧generator的唯一工厂；@param stop 同源取消。
/// @return 原完整组合/权重/覆盖，算法只保留一份。
[[nodiscard]] ConfigurationMoveSpace EnumerateConfigurationMovesWithFactory(const ConfigurationMoveInput& input,
    ConfigurationEffectFactory factory, CancellationToken stop);
} // namespace pbi::detail
