#pragma once

#include "pbi/exploration_cursor.hpp"
#include "pbi/turn.hpp"
#include <stdexcept>

namespace pbi {
/// 原cursor构造错误与实际路径重放错误属于不同HTTP类别，不按错误文案猜测。
enum class SnapshotCursorFailure { invalid_path, replay };
/// 同一失败保留原稳定文案与强类型类别，仍兼容纯域invalid_argument错误合同。
class SnapshotCursorError final : public std::invalid_argument {
public:
  /// @param failure 明确失败类别；@param message 原公开诊断，移动后由异常拥有。
  SnapshotCursorError(SnapshotCursorFailure failure, std::string message)
      : std::invalid_argument(std::move(message)), failure_(failure) {}
  /// @return 原失败类别；只读，不从诊断字符串恢复业务语义。
  [[nodiscard]] SnapshotCursorFailure Failure() const noexcept { return failure_; }
private:
  SnapshotCursorFailure failure_;
};
/// 即时快照的完整拥有结果；概率/局部节点ID/全部展开组与线性战报都由Core产生。
struct FixedBattleSnapshotResult {
  BattleNodeProjection projection;
  std::vector<BattleReportStep> report_steps;
};
/// 按原即时快照语义从根重放所选局部边，之后只展开当前节点的一层。
/// @param initial 只读已准备状态，不修改祖先或知识；@param knowledge 同一不可变属性表快照。
/// @param attacker_policy 玩家选择策略；@param defender_policy 对侧选择策略。
/// @param cursor 原source/edge/target身份序列，必须从节点0连续开始。
/// @param turn_limits 原完整回合显式资源保护，不用全图预算截断即时路径。
/// @param stop 同源协作取消；取消不返回部分战报或不完整归一分布。
/// @return 全部展开组和真实每步战报，不构建/求解全局状态图，不推测胜率。
/// @throws SnapshotCursorError 路径不连续、局部边不可用或目标身份不匹配，保留明确类别。
[[nodiscard]] FixedBattleSnapshotResult ExpandFixedBattleSnapshot(const BattleState& initial,
    const TypeChartSnapshot& knowledge, ActionPolicy attacker_policy, ActionPolicy defender_policy,
    std::span<const ExplorationPathStep> cursor, TurnLimits turn_limits = {}, CancellationToken stop = {});
} // namespace pbi
