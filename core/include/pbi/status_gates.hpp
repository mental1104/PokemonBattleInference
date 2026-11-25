#pragma once
#include "pbi/status.hpp"
#include <functional>
#include <span>

namespace pbi {
/// 原五种独立出招门禁；不隐式注入既有StandardTurnResolver。
enum class StatusActionGate { sleep, freeze, paralysis, infatuation, confusion };
/// 阻断与混乱自伤替换是原管线的不同终止结果。
enum class StatusActionDecision { allow, block, replace_with_self_hit };
/// 原StatusRules的完整值；精确分数与睡眠末项重复语义不经浮点数。
struct StatusGateRules {
  std::vector<Rational> sleep_wake_chances{Rational{0}, Rational{1, 3}, Rational{1, 2}, Rational{1}};
  Rational freeze_thaw_chance{1, 5};
  bool allow_thaw_move_override = true;
  Rational paralysis_speed_multiplier{1, 2};
  Rational full_paralysis_chance{1, 4};
  Rational burn_physical_multiplier{1, 2};
  Rational burn_residual_fraction{1, 16};
  Rational poison_residual_fraction{1, 8};
  Rational bad_poison_base_fraction{1, 16};
  Rational confusion_self_hit_chance{1, 3};
  Rational infatuation_immobilize_chance{1, 2};
};
/// 原门禁返回的完整不可变新快照；允许结果的reason可空，不从events推断。
struct StatusActionGateResult {
  StatusActionDecision decision;
  CombatantStatus updated_status;
  std::optional<std::string> reason;
  std::vector<std::string> events;
};
/// 原BattleRandom.chance端口；调用者拥有随机过程，Core仅按原顺序消费精确概率。
using StatusChance = std::function<bool(const Rational&)>;
/// @param generation 原profile代际1…9；@return 原完整状态规则，不注入其他官方机制。
[[nodiscard]] StatusGateRules StatusGateRulesForGeneration(std::int32_t generation);
/// @param rules 完整策略；非法概率/负倍率/空睡眠表抛invalid_argument，合法零倍率允许。
void ValidateStatusGateRules(const StatusGateRules& rules);
/// @param gate 原有限门禁；@param status 只读完整状态；@param thaws_user_when_frozen 原MoveFlag事实。
/// @param rules 已准备完整规则；@param chance 原随机端口，调用会按原顺序推进外部RNG。
/// @return 原decision/status/reason/events；本函数不计算自伤伤害、不消耗PP。
[[nodiscard]] StatusActionGateResult CheckStatusActionGate(StatusActionGate gate, const CombatantStatus& status,
    bool thaws_user_when_frozen, const StatusGateRules& rules, const StatusChance& chance);
/// @param gates 非空有序原门禁；@param status 只读初始状态；@param thaws_user_when_frozen 原招式flag。
/// @param rules 完整策略；@param chance 调用者拥有的随机端口。
/// @return 按原顺序积累events、转交新状态并在首个非ALLOW处短路；全部允许时reason清空。
[[nodiscard]] StatusActionGateResult CheckStatusActionGatePipeline(std::span<const StatusActionGate> gates,
    const CombatantStatus& status, bool thaws_user_when_frozen, const StatusGateRules& rules, const StatusChance& chance);
/// @param status 只读初始状态；@param thaws_user_when_frozen 原招式flag；@param rules 完整策略。
/// @param chance 调用者RNG端口；@return 原sleep/freeze/paralysis/infatuation/confusion默认顺序结果。
[[nodiscard]] StatusActionGateResult CheckDefaultStatusActionGates(const CombatantStatus& status,
    bool thaws_user_when_frozen, const StatusGateRules& rules, const StatusChance& chance);
} // namespace pbi
