#pragma once
// ABI 私有适配模型；JSON 在这里转换为已验证 Core 值，不进入纯领域层。
#include "json_contract.hpp"
#include "pbi/state.hpp"
#include <variant>

namespace pbi::contract {
/// 新 HP；由领域方法检查范围。
struct HpUpdate { std::int32_t value; };
/// 指定招式剩余 PP。
struct PpUpdate { std::int64_t move_id; std::int32_t value; };
/// 指定招式的禁用标记。
struct DisabledUpdate { std::int64_t move_id; bool value; };
/// 同步更新整方讲究锁招，null 表示解除。
struct ChoiceUpdate { std::optional<std::int64_t> move_id; };
/// 替换完整等级快照。
struct StagesUpdate { StatStages value; };
/// 替换完整状态快照。
struct StatusUpdate { CombatantStatus value; };
/// 替换上一招记录，允许未配置的正 ID。
struct LastMoveUpdate { std::optional<std::int64_t> move_id; };
/// 替换道具消耗标记。
struct ItemUpdate { bool value; };
/// 清除首次回合标记。
struct FirstTurnUpdate {};
/// 按 ID 替换完整槽位，保留运行时 slot_id 合同。
struct SlotUpdate { MoveSlotState value; };
using BattlerChange = std::variant<HpUpdate, PpUpdate, DisabledUpdate, ChoiceUpdate, StagesUpdate, StatusUpdate, LastMoveUpdate, ItemUpdate, FirstTurnUpdate, SlotUpdate>;
/// 作用于固定一侧的类型化更新。
struct BattlerUpdate { BattleSide side; BattlerChange change; };
/// 推进绝对回合并回到行动选择。
struct NextTurnUpdate {};
/// 替换回合阶段。
struct PhaseUpdate { BattlePhase value; };
/// 替换固定双方场地。
struct FieldUpdate { BattleFieldState value; };
/// 显式替换已验证推演规则。
struct RulesUpdate { InferenceRules value; };
using StateUpdate = std::variant<BattlerUpdate, NextTurnUpdate, PhaseUpdate, FieldUpdate, RulesUpdate>;
/// 状态更新后可选的实际伤害查询，复用同一纯 Core 与知识接口。
struct StateDamageQuery { BattleSide side; std::int64_t move_id; std::int32_t generation; DamagePolicy policy; TypeChartSnapshot knowledge; };
/// 一次原子状态计算；所有节点/指令/知识由请求独占。
struct BattleStateRequest { BattleState state; std::vector<StateUpdate> updates; std::optional<BattleState> reference; std::optional<StateDamageQuery> damage; };
/// 独立状态修正请求，不把麻痹偷偷接入旧行动排序。
struct StatusModifiersRequest { CombatantStatus status; std::int64_t speed; Rational paralysis; DamageCategory category; Rational base_multiplier; Rational burn_multiplier; };
/// @param value 完整正式招式配置；@return 复用状态合同验证的拥有值，不执行招式。
[[nodiscard]] MoveSpec ReadMoveSpecValue(const Json& value);
/// @param value 只读招式配置；@return 可重放的全部正式招式字段，不丢失 ID 或独立效果事实。
[[nodiscard]] Json MoveSpecJson(const MoveSpec& value);
/// @param value 只读完整状态 JSON；@return 已验证且拥有全部字段的领域状态，不执行更新或计算。
[[nodiscard]] BattleState ReadBattleStateValue(const Json& value);
/// @param state 只读完整领域状态；@return 全部正式状态字段，不计算速度/伤害，不产生业务副作用。
[[nodiscard]] Json StateJson(const BattleState& state);
/// @param value 只读 JSON 操作；@param remaining_rolls 批次余量；@return 已验证状态请求与实际策略槽位开销。
[[nodiscard]] std::pair<BattleStateRequest, std::size_t> ReadBattleStateRequest(const Json& value, std::size_t remaining_rolls);
/// @param value 只读 JSON 操作；@return 完全类型化的独立状态修正输入。
[[nodiscard]] StatusModifiersRequest ReadStatusModifiersRequest(const Json& value);
/// @param request 只读请求；@return 经过 Core 更新的完整快照、键等价判断和可选真实伤害。
[[nodiscard]] Json EvaluateBattleState(const BattleStateRequest& request);
/// @param request 只读独立状态修正输入；@return 精确倍率、速度与原 switch-out 清理快照。
[[nodiscard]] Json EvaluateStatusModifiers(const StatusModifiersRequest& request);
} // namespace pbi::contract
