#pragma once

#include "pbi/state.hpp"
#include <span>
#include <variant>

namespace pbi {
/// 普通行动的完整身份；运行时 slot_id 与招式 ID 独立，不能按列表下标识别策略行动。
struct UseMoveAction {
  BattleSide side;
  std::int64_t move_id;
  std::int32_t priority = 0;
  std::int64_t slot_id = 0;
  /// @param other 只读行动；@return 四个身份字段是否全部相同。
  bool operator==(const UseMoveAction& other) const = default;
};
/// 没有可用普通槽位时的挣扎行动，不引用或消耗普通招式 PP。
struct StruggleAction {
  BattleSide side;
  /// @param other 只读行动；@return 所属侧是否相同。
  bool operator==(const StruggleAction& other) const = default;
};
/// 濒死方的内部占位行动，正常存活方不能主动选择。
struct PassAction {
  BattleSide side;
  /// @param other 只读行动；@return 所属侧是否相同。
  bool operator==(const PassAction& other) const = default;
};
/// 固定的三类领域行动，不用字符串或可空 move_id 混合互斥语义。
using BattleAction = std::variant<UseMoveAction, StruggleAction, PassAction>;
/// 一次玩家选招及其精确权重；这层概率与战斗随机概率分开。
struct ActionSelection {
  BattleAction action;
  Rational probability;
};
/// 当前真实支持的两种选择策略，与原 Python 的稳定策略身份一致。
enum class ActionPolicy { uniform_random, first_legal_action };

/// 从 PP、禁用、讲究锁招与 HP 生成稳定且非空的合法行动。
/// @param state 只读已验证战斗节点；@param side 需要选择的一方。
/// @return 按运行时槽位顺序排列的行动，濒死为 Pass，无可用招式为 Struggle。
[[nodiscard]] std::vector<BattleAction> GenerateLegalActions(const BattleState& state, BattleSide side);
/// 对具体行动进行身份和类型校验；不会执行或修改战斗。
/// @param action 只读行动，UseMove 的 slot_id=0 按原兼容合同规范化为 move_id。
/// @return 已规范化行动，非法侧/ID 抛 invalid_argument。
[[nodiscard]] BattleAction ValidateAction(BattleAction action);
/// @param action 只读且经过验证的行动；@return 稳定行动侧，非法枚举抛 invalid_argument。
[[nodiscard]] BattleSide ActionSide(const BattleAction& action);
/// @param legal_actions 稳定的非空合法行动集合；@param policy 选择策略。
/// @return 精确归一化策略分布，不包含命中/伤害/同速等随机概率。
[[nodiscard]] std::vector<ActionSelection> SelectActions(std::span<const BattleAction> legal_actions, ActionPolicy policy);
/// 校验自定义策略的归一化、重复和合法集合，不补齐或默默归一化非法分布。
/// @param selections 非空策略分布；@param legal_actions 当前非空合法行动集合。
/// @throws std::invalid_argument 概率不在 (0,1]、总和非一、行动重复或非法。
void ValidateActionDistribution(std::span<const ActionSelection> selections, std::span<const BattleAction> legal_actions);
} // namespace pbi
