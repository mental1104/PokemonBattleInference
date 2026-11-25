#pragma once
#include "state_graph_projection_contract.hpp"
#include "pbi/graph_explanation.hpp"

namespace pbi::contract {
/// @param value 原完整业务归因；@param stop 同源取消；@return 原explanation.v1全部字段，分数保留原decimal无percent。
[[nodiscard]] Json RootActionPairExplanationJson(const RootActionPairExplanation& value, CancellationToken stop);
} // namespace pbi::contract
