#pragma once
#include "turn_contract.hpp"
#include "pbi/fixed_battle_snapshot.hpp"

namespace pbi::contract {
/// 当前一步只需要正式策略回合和用户路径，不保存全图求解/生成预算。
struct FixedBattleSnapshotRequest {
  TurnRequest turn;
  std::vector<ExplorationPathStep> cursor;
};
/// @param value 正式state/chart/policies/cursor边界；@param remaining_rolls 同批策略余量。
/// @param stop 同源取消；@return 完整拥有请求；不会读取PG或生成局部身份。
[[nodiscard]] FixedBattleSnapshotRequest ReadFixedBattleSnapshotRequest(const Json& value,
    std::size_t remaining_rolls, CancellationToken stop);
/// @param request 完整冻结初始状态与实际选择路径；@param stop 同源取消。
/// @return 原即时浏览完整DTO或明确422业务拒绝，不求解全局胜率或返回部分路径。
[[nodiscard]] Json EvaluateFixedBattleSnapshot(const FixedBattleSnapshotRequest& request, CancellationToken stop);
} // namespace pbi::contract
