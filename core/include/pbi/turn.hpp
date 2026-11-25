#pragma once

#include "pbi/actions.hpp"
#include "pbi/battle_graph.hpp"

namespace pbi {
/// 不能由具体机制重排的原十一阶段完整回合模板。
enum class TurnPhase { turn_start, action_selection, action_order, before_move, accuracy_check, before_damage,
  damage, after_damage, after_move, faint_check, turn_end };
inline constexpr std::array<TurnPhase, 11> stable_turn_phases{TurnPhase::turn_start, TurnPhase::action_selection,
    TurnPhase::action_order, TurnPhase::before_move, TurnPhase::accuracy_check, TurnPhase::before_damage,
    TurnPhase::damage, TurnPhase::after_damage, TurnPhase::after_move, TurnPhase::faint_check, TurnPhase::turn_end};
/// 已知部分机制的来源，不把原未支持子能力偷偷当成已实现。
enum class EffectSource { move, ability, item, status };
/// 可运行参考行为中尚未实现的明确子能力，用于结果解释和客户端提示。
struct UnsupportedAspect {
  EffectSource source;
  std::string identifier;
  std::string capability;
  /// @param other 只读机制缺口；@return 来源/标识/能力三字段是否相同，用于稳定去重。
  bool operator==(const UnsupportedAspect& other) const = default;
};
/// 单次完整回合的保护预算，null 表示纯 Core 调用方不限制；ABI 必须显式给出自己的有限预算。
struct TurnLimits {
  std::optional<std::size_t> max_branches;
  std::optional<std::size_t> max_event_paths;
};
/// 超过真实中间分支/事件历史预算时明确失败，绝不截出一部分后重新归一。
class TurnResourceLimit final : public std::runtime_error {
public:
  /// @param message 固定 ASCII 预算诊断，异常拥有副本。
  explicit TurnResourceLimit(const char* message) : std::runtime_error(message) {}
};
/// 回合阶段内的协作取消，适配层不能把它报告为计算失败或部分成功。
class TurnCancelled final : public std::runtime_error {
public:
  /// 无参数；只保存稳定 ASCII 诊断。
  TurnCancelled() : std::runtime_error("battle turn cancelled") {}
};
/// 正式回合输出，不变状态、精确转移、模板顺序及明确的参考机制限制。
struct TurnResolution {
  std::vector<BattleTransition> transitions;
  std::array<TurnPhase, 11> phases = stable_turn_phases;
  std::vector<UnsupportedAspect> unsupported_aspects;
};
/// 固定同一知识快照的正式回合执行器，有限静态机制分发不依赖运行时插件或平台服务。
class StandardTurnResolver {
public:
  /// @param knowledge 转移拥有的不可变属性相克快照，不在计算时访问数据库或网络。
  explicit StandardTurnResolver(TypeChartSnapshot knowledge);
  /// @param state 只读行动选择节点；@param attacker_action 合法攻击方行动；@param defender_action 合法防守方行动。
  /// @param limits 单次回合中间分支保护；@param stop 协作取消令牌。
  /// @return 真实完整回合与结构化事件，未知效果/非法行动/预算/取消明确失败。
  /// 保留原默认调用链：不擅自把独立睡眠/麻痹门禁、残余伤害或 LifeOrb 反伤接入。
  [[nodiscard]] TurnResolution Resolve(const BattleState& state, BattleAction attacker_action, BattleAction defender_action,
      TurnLimits limits = {}, pbi::CancellationToken stop = {}) const;
  /// @param state 当前完整节点；@param attacker_policy 攻击选招策略；@param defender_policy 防守选招策略。
  /// @param limits 每次展开共享的分支/路径预算；@param stop 协作取消令牌。
  /// @return 玩家选择×回合随机的完整分布，路径保留两层精确概率元数据供旧投影消费。
  [[nodiscard]] std::vector<BattleTransition> Expand(const BattleState& state, ActionPolicy attacker_policy,
      ActionPolicy defender_policy, TurnLimits limits = {}, pbi::CancellationToken stop = {}) const;
  /// @param state 全部双方配置；@return 当前参考实现明确尚未实现的子能力，不执行伤害。
  [[nodiscard]] std::vector<UnsupportedAspect> CoverageLimitations(const BattleState& state) const;
private:
  TypeChartSnapshot knowledge_;
};
/// 固定战斗的全部真实保护与策略，不将图保护上限解释为数学平局。
struct FixedBattleOptions {
  ActionPolicy attacker_policy = ActionPolicy::uniform_random;
  ActionPolicy defender_policy = ActionPolicy::uniform_random;
  BattleSide observer = BattleSide::attacker;
  GraphLimits graph_limits;
  TurnLimits turn_limits;
  std::optional<std::size_t> max_equation_nodes = std::nullopt;
  std::size_t progress_interval = 100;
};
/// 持有可按需浏览的完整图和精确求解结果，未完成解不携带伪造概率。
struct FixedBattleComputation {
  BattleGraph graph;
  GraphSolution solution;
  std::vector<UnsupportedAspect> unsupported_aspects;
};
/// 原任务轻量图和root额外事实；不改变现有完整图computation的内部布局。
struct SummaryFixedBattleComputation { FixedBattleComputation computation; std::vector<RootActionEventSummary> root_summaries; };
/// 将正式回合、玩家策略、不可变 BFS 和精确吸收解串成真实固定战斗闭环。
/// @param initial 初始完整节点；@param knowledge 转移拥有的静态知识；@param options 全部策略与预算。
/// @param progress 可空真实构图进度观察者；@param stop 同一次计算的只读取消令牌。
/// @return 拥有图/精确解/明确机制边界的结果；预算未知保持 incomplete，非法或取消明确失败。
[[nodiscard]] FixedBattleComputation InferFixedBattle(BattleState initial, TypeChartSnapshot knowledge,
    FixedBattleOptions options = {}, const GraphProgressObserver& progress = {}, CancellationToken stop = {});
/// 原任务summary同源真实回合闭环，达到图预算即停止全部frontier，完整探索入口保持原状。
/// @param initial 拥有初态；@param knowledge 拥有知识；@param options 明确策略/预算/原进度间隔。
/// @param progress 同步实际进度；@param stop 同源取消；@return 轻量图、原精确解和独立root历史。
[[nodiscard]] SummaryFixedBattleComputation InferSummaryFixedBattle(BattleState initial, TypeChartSnapshot knowledge,
    FixedBattleOptions options, const GraphProgressObserver& progress = {}, CancellationToken stop = {});
} // namespace pbi
