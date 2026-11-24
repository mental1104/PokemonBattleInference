#include "pbi/turn.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <tuple>

namespace pbi {
namespace {
/// 当前已注册的三个具体招式效果；普通固定伤害不需要虚构 identifier。
enum class MoveEffect { none, ice_punch, fake_out, brick_break };
/// @param identifier 状态模型已规范化的机制标识；@return 真实已实现效果，未知非空值明确 unsupported。
MoveEffect Effect(const std::optional<std::string>& identifier) {
  if (!identifier) return MoveEffect::none;
  if (*identifier == "ice_punch") return MoveEffect::ice_punch;
  if (*identifier == "fake_out") return MoveEffect::fake_out;
  if (*identifier == "brick_break") return MoveEffect::brick_break;
  throw UnsupportedRule("unsupported turn move effect identifier");
}
/// @param side 稳定战斗侧；@return 另一侧，调用方必须先验证有限枚举。
BattleSide Opposite(BattleSide side) { return side == BattleSide::attacker ? BattleSide::defender : BattleSide::attacker; }
/// @param side 已验证战斗侧；@return 原随机事件身份使用的静态名称。
std::string SideText(BattleSide side) { return side == BattleSide::attacker ? "attacker" : "defender"; }
/// @param action 类型化合法行动；@return 普通招式 ID，挣扎和 Pass 无关联 ID。
std::optional<std::int64_t> MoveId(const BattleAction& action) {
  if (const auto* move = std::get_if<UseMoveAction>(&action)) return move->move_id;
  return std::nullopt;
}
/// @param action 类型化合法行动；@return 业务事件的来源，不按展示名称猜测机制。
std::string ActionSource(const BattleAction& action) {
  if (std::holds_alternative<UseMoveAction>(action)) return "move";
  if (std::holds_alternative<StruggleAction>(action)) return "struggle";
  return "pass";
}
/// @param action 类型化行动；@return 原行动排序优先级，Pass 保持最后。
std::int32_t Priority(const BattleAction& action) {
  if (const auto* move = std::get_if<UseMoveAction>(&action)) return move->priority;
  return std::holds_alternative<StruggleAction>(action) ? 0 : -10000;
}
/// @param value 原 binary64 随机/动态伤害值；@return floor 后非负 int64，非法/越界明确失败。
std::int64_t FloorDamage(double value) {
  constexpr double boundary = 9223372036854775808.0;
  const auto result = std::floor(value);
  if (!std::isfinite(result) || result < 0 || result >= boundary) throw std::overflow_error("turn damage exceeds nonnegative int64 range");
  return static_cast<std::int64_t>(result);
}
/// 仅当前调用拥有的阶段分支；概率可以小于一，整组最终完成后才验证归一。
struct Branch { Rational probability; BattleState state; EventSummary events; std::optional<std::string> source; };
/// 同一次回合的协作取消与中间内存预算，不在超额时偷偷截断或归一化。
class TurnControl {
public:
  /// @param limits 当前调用保护；@param stop 同一调用的取消令牌；零预算明确失败。
  TurnControl(TurnLimits limits, pbi::CancellationToken stop) : limits_(limits), stop_(stop) {
    if ((limits_.max_branches && *limits_.max_branches == 0) || (limits_.max_event_paths && *limits_.max_event_paths == 0))
      throw std::invalid_argument("turn limits must be greater than 0");
    Check(0, 0);
  }
  /// @param branches 当前阶段实际分支；@param paths 当前阶段实际历史；取消或超额立即失败。
  void Check(std::size_t branches, std::size_t paths) const {
    if (stop_.Requested()) throw TurnCancelled{};
    if (limits_.max_branches && branches > *limits_.max_branches) throw TurnResourceLimit("turn branch budget exceeded");
    if (limits_.max_event_paths && paths > *limits_.max_event_paths) throw TurnResourceLimit("turn event path budget exceeded");
  }
  /// @param first 前序历史；@param second 后序历史；@return 预算内完整串联结果，不产生半套路径。
  [[nodiscard]] EventSummary Join(const EventSummary& first, const EventSummary& second) const {
    if (second.Paths().size() > std::numeric_limits<std::size_t>::max() / first.Paths().size())
      throw TurnResourceLimit("turn event path count overflow");
    Check(1, first.Paths().size() * second.Paths().size());
    return first.Concatenate(second);
  }
private:
  TurnLimits limits_;
  pbi::CancellationToken stop_;
};
/// 阶段分支的局部拥有容器，Append 的 mutation 和完整预算检查从调用点可见。
class Branches {
public:
  /// @param control 借用至本容器销毁的同一回合保护器。
  explicit Branches(const TurnControl& control) : control_(control) {}
  /// @param branch 转移拥有的一条实际分支；超过完整阶段预算时不添加该分支。
  void Append(Branch branch) {
    if (branch.events.Paths().size() > std::numeric_limits<std::size_t>::max() - paths_ || values_.size() == std::numeric_limits<std::size_t>::max())
      throw TurnResourceLimit("turn branch count overflow");
    const auto paths = paths_ + branch.events.Paths().size();
    control_.Check(values_.size() + 1, paths); paths_ = paths; values_.push_back(std::move(branch));
  }
  /// @return 转移全部阶段分支的所有权，本容器随后不再使用。
  [[nodiscard]] std::vector<Branch> Take() { return std::move(values_); }
private:
  const TurnControl& control_;
  std::vector<Branch> values_;
  std::size_t paths_ = 0;
};
/// @param summary 既有历史；@param event 当前真实业务事实；@param control 预算/取消。
/// @return 在所有替代历史末尾追加该确定事实后的新摘要。
EventSummary AddEvent(const EventSummary& summary, BattleEventData event, const TurnControl& control) {
  return control.Join(summary, EventSummary{{{{BattleEvent{std::move(event)}}, Rational{1}}}});
}
/// @param summary 既有历史；@param event 真实随机结果；@param control 预算/取消。
/// @return 追加随机结果的完整新历史。
EventSummary AddRandom(const EventSummary& summary, TransitionEvent event, const TurnControl& control) {
  return control.Join(summary, EventSummary{{{{std::move(event)}, Rational{1}}}});
}
/// @param state 只读父节点；@param side 扣血目标；@param damage 非负真实伤害档位。
/// @return HP 在零处截断的新节点，不修改父节点。
BattleState DamageHp(const BattleState& state, BattleSide side, std::int64_t damage) {
  if (damage < 0) throw std::invalid_argument("damage roll must be nonnegative");
  const auto& battler = state.Battler(side);
  const auto hp = battler.View().current_hp;
  const auto after = damage >= hp ? 0 : hp - static_cast<std::int32_t>(damage);
  return state.WithBattler(side, battler.WithCurrentHp(after));
}
/// @param before 伤害阶段之前；@param after 同阶段之后；@param action 原类型化行动。
/// @param summary 既有随机历史；@param control 保护；@return 目标后行动方顺序的完整 HP/濒死事实。
EventSummary HpEvents(const BattleState& before, const BattleState& after, const BattleAction& action,
    EventSummary summary, const TurnControl& control) {
  const auto actor = ActionSide(action);
  for (const auto side : {Opposite(actor), actor}) {
    const auto previous = before.Battler(side).View().current_hp;
    const auto current = after.Battler(side).View().current_hp;
    if (previous == current) continue;
    const auto source = side == actor && std::holds_alternative<StruggleAction>(action) ? "struggle-recoil" : ActionSource(action);
    if (current < previous) summary = AddEvent(summary, {.kind = BattleEventKind::damage, .turn_number = before.View().turn_number,
        .actor = actor, .target = side, .move_id = MoveId(action), .source_identifier = source, .value = Integer{previous - current}}, control);
    summary = AddEvent(summary, {.kind = BattleEventKind::hp_changed, .turn_number = before.View().turn_number, .actor = actor,
        .target = side, .move_id = MoveId(action), .source_identifier = source, .before = Integer{previous}, .after = Integer{current}}, control);
    if (previous > 0 && current == 0) summary = AddEvent(summary, {.kind = BattleEventKind::fainted,
        .turn_number = before.View().turn_number, .actor = side, .source_identifier = source}, control);
  }
  return summary;
}
/// 一次正式回合的静态机制分发，只读知识与控制器在整个执行期间保持有效。
class TurnExecution {
public:
  /// @param knowledge 借用本次不可变知识；@param control 借用同一回合的预算和取消状态。
  TurnExecution(const TypeChartSnapshot& knowledge, const TurnControl& control) : knowledge_(knowledge), control_(control) {}
  /// @param state 行动选择节点；@param actions 已验证的固定双方行动。
  /// @return 真实完整回合的精确分布，按首次 StateKey 顺序归并。
  [[nodiscard]] std::vector<BattleTransition> Run(const BattleState& state, const std::array<BattleAction, 2>& actions) const {
    control_.Check(0, 0);
    if (state.View().phase != BattlePhase::action_selection) throw std::invalid_argument("turn resolution must start at action selection");
    for (std::size_t id = 0; id < actions.size(); ++id) {
      const auto side = id == 0 ? BattleSide::attacker : BattleSide::defender;
      if (ActionSide(actions[id]) != side) throw std::invalid_argument("turn actions must be attacker then defender");
      const auto legal = GenerateLegalActions(state, side);
      if (std::find(legal.begin(), legal.end(), actions[id]) == legal.end()) throw std::invalid_argument("turn action is outside legal action set");
    }
    auto selected = state;
    auto summary = AddEvent(EventSummary{}, {.kind = BattleEventKind::turn_started, .turn_number = state.View().turn_number}, control_);
    for (const auto& action : actions) {
      const auto side = ActionSide(action);
      summary = AddEvent(summary, {.kind = BattleEventKind::move_selected, .turn_number = selected.View().turn_number, .actor = side,
          .target = std::holds_alternative<PassAction>(action) ? std::nullopt : std::optional{Opposite(side)},
          .move_id = MoveId(action), .source_identifier = ActionSource(action)}, control_);
      if (const auto* move = std::get_if<UseMoveAction>(&action)) {
        const auto& battler = selected.Battler(side);
        if (battler.View().spec.View().pokemon.item == DamageItem::choice_band && !battler.View().item_consumed && !battler.View().choice_lock_move_id)
          selected = selected.WithBattler(side, battler.WithChoiceLock(move->move_id));
      }
    }
    selected = selected.WithPhase(BattlePhase::action_resolution);
    const auto left = std::pair{Priority(actions[0]), EffectiveActionSpeed(selected.View().attacker)};
    const auto right = std::pair{Priority(actions[1]), EffectiveActionSpeed(selected.View().defender)};
    const auto tie = left == right;
    Branches completed{control_};
    for (int order = 0; order < (tie ? 2 : 1); ++order) {
      const bool attacker_first = tie ? order == 0 : left > right;
      const std::array<BattleAction, 2> ordered = attacker_first ? actions : std::array<BattleAction, 2>{actions[1], actions[0]};
      auto history = summary;
      std::optional<std::string> source;
      if (tie) {
        history = AddRandom(history, TransitionEvent{{TransitionEventType::speed_tie,
            "turn-" + std::to_string(selected.View().turn_number) + "-action-order", SideText(ActionSide(ordered[0])) + "-first"}}, control_);
        source = "turn.speed-tie";
      }
      for (std::size_t index = 0; index < ordered.size(); ++index) {
        const auto& action = ordered[index]; const auto side = ActionSide(action);
        history = AddEvent(history, {.kind = BattleEventKind::action_ordered, .turn_number = selected.View().turn_number, .actor = side,
            .target = std::holds_alternative<PassAction>(action) ? std::nullopt : std::optional{Opposite(side)}, .move_id = MoveId(action),
            .source_identifier = ActionSource(action), .value = Integer{index + 1}}, control_);
      }
      std::vector<Branch> branches{{tie ? Rational{1, 2} : Rational{1}, selected, std::move(history), std::move(source)}};
      for (const auto& action : ordered) branches = Execute(branches, action);
      for (auto& branch : branches) {
        const auto turn = branch.state.View().turn_number;
        branch.state = Finish(branch.state);
        branch.events = AddEvent(branch.events, {.kind = BattleEventKind::turn_ended, .turn_number = turn}, control_);
        completed.Append(std::move(branch));
      }
    }
    std::vector<BattleTransition> result;
    for (auto& branch : completed.Take()) result.emplace_back(BattleTransitionData{std::move(branch.probability), std::move(branch.state), std::move(branch.events), std::move(branch.source)});
    return MergeEquivalentTransitions(result);
  }
private:
  /// @param state 完成回合的只读状态；@return 清畏缩/首次标记，再进入下一回合或终局。
  [[nodiscard]] BattleState Finish(const BattleState& state) const {
    auto current = state.WithPhase(BattlePhase::end_of_turn);
    for (const auto side : {BattleSide::attacker, BattleSide::defender}) {
      const auto& battler = current.Battler(side);
      current = current.WithBattler(side, battler.WithStatus(battler.View().status.ClearVolatile(VolatileStatusKind::flinch)).MarkFirstTurnComplete());
    }
    if (current.View().attacker.View().current_hp == 0 || current.View().defender.View().current_hp == 0) return current.WithPhase(BattlePhase::terminal);
    return current.NextTurn();
  }
  /// @param state 已允许行动节点；@param action 普通招式或挣扎；@return 扣 PP/记录上一招后的新状态。
  [[nodiscard]] BattleState Consume(const BattleState& state, const BattleAction& action) const {
    const auto* move = std::get_if<UseMoveAction>(&action);
    if (!move) return state;
    const auto& battler = state.Battler(move->side); const auto& slot = battler.MoveSlot(move->move_id);
    if (slot.View().current_pp <= 0 || slot.View().disabled || (battler.View().choice_lock_move_id && *battler.View().choice_lock_move_id != move->move_id))
      throw std::invalid_argument("selected move became unavailable before pp consumption");
    return state.WithBattler(move->side, battler.WithMoveSlot(slot.WithCurrentPp(slot.View().current_pp - 1)).WithLastMove(move->move_id));
  }
  /// @param state 命中后的节点；@param action 原行动；@param before_pp 普通招式扣 PP 前的伤害快照。
  /// @return 完整局部伤害随机分布，最后一点 PP 仍可以完成本次攻击。
  [[nodiscard]] std::vector<BattleTransition> Damage(const BattleState& state, const BattleAction& action,
      std::optional<DamageInput> before_pp) const {
    const auto side = ActionSide(action); const auto target = Opposite(side);
    const auto* move = std::get_if<UseMoveAction>(&action);
    if (move && state.Battler(side).View().spec.Move(move->move_id).View().move.category == DamageCategory::status)
      return {BattleTransition{{Rational{1}, state, EventSummary{}, std::nullopt}}};
    std::vector<std::int64_t> rolls;
    bool multiscale = false;
    std::int32_t recoil = 0;
    if (move) {
      auto input = before_pp.value();
      for (auto* pokemon : {&input.attacker, &input.defender}) if (pokemon->ability == DamageAbility::multiscale || pokemon->ability == DamageAbility::inner_focus)
        pokemon->ability = DamageAbility::none; // 这两个能力由下面实时分发处理，静态直接入口仍保持 UNSUPPORTED。
      auto calculated = CalculateDamage(input, knowledge_); rolls = std::move(calculated.rolls);
      const auto& defender = state.Battler(target).View();
      const auto effectiveness = std::find_if(calculated.trace.begin(), calculated.trace.end(), [](const DamageTrace& value) { return value.key == DamageSource::type_effectiveness; });
      multiscale = defender.spec.View().pokemon.ability == DamageAbility::multiscale && defender.current_hp == defender.spec.View().pokemon.stats.hp
          && effectiveness != calculated.trace.end() && effectiveness->multiplier.value() > 0;
      if (multiscale) for (auto& damage : rolls) damage = damage == 0 || input.policy.multiscale_damage_multiplier == 0 ? 0
          : std::max<std::int64_t>(1, FloorDamage(static_cast<double>(damage) * input.policy.multiscale_damage_multiplier));
    } else {
      const auto& actor = state.Battler(side).View().spec.View().pokemon;
      const auto& defender = state.Battler(target).View().spec.View().pokemon;
      const auto& rules = state.View().rules.View();
      const auto base = CalculateBaseDamage({actor.level, rules.move_execution_policy.struggle_power, actor.stats.attack, defender.stats.defense});
      for (const auto multiplier : rules.damage_policy.random_damage_multipliers) rolls.push_back(FloorDamage(static_cast<double>(base) * multiplier));
      const Integer recoil_value = Integer{actor.stats.hp} * rules.move_execution_policy.struggle_recoil_fraction.numerator()
          / rules.move_execution_policy.struggle_recoil_fraction.denominator();
      recoil = std::max(1, recoil_value.convert_to<std::int32_t>());
    }
    control_.Check(rolls.size(), rolls.size());
    const Rational probability{Integer{1}, Integer{rolls.size()}};
    std::vector<BattleTransition> result;
    for (std::size_t index = 0; index < rolls.size(); ++index) {
      control_.Check(index + 1, index + 1);
      auto after = DamageHp(state, target, rolls[index]);
      if (!move) after = DamageHp(after, side, recoil);
      auto events = EventSummary{};
      if (multiscale) events = AddEvent(events, {.kind = BattleEventKind::ability_triggered, .turn_number = state.View().turn_number,
          .actor = target, .target = side, .move_id = MoveId(action), .source_identifier = "ability:multiscale"}, control_);
      events = AddRandom(events, TransitionEvent{{TransitionEventType::damage_roll,
          "turn-" + std::to_string(state.View().turn_number) + "-" + SideText(side) + (move ? "-move-" + std::to_string(move->move_id) : "-struggle") + "-damage",
          "roll-" + std::to_string(index), Integer{rolls[index]}}}, control_);
      events = HpEvents(state, after, action, std::move(events), control_);
      result.emplace_back(BattleTransitionData{probability, std::move(after), std::move(events), move ? "damage.random-roll" : "damage.struggle"});
    }
    return MergeEquivalentTransitions(result);
  }
  /// @param branch 真实伤害后的分支；@param action 原行动；@return FakeOut 请求及目标 InnerFocus 裁决后的分支。
  [[nodiscard]] Branch AfterDamage(Branch branch, const BattleAction& action) const {
    const auto* move = std::get_if<UseMoveAction>(&action);
    if (!move) return branch;
    const auto& configured = branch.state.Battler(move->side).View().spec.Move(move->move_id).View();
    if (Effect(configured.effect_identifier) != MoveEffect::fake_out) return branch;
    const auto target = Opposite(move->side); const auto& defender = branch.state.Battler(target);
    if (defender.View().current_hp == 0) return branch;
    double effectiveness = 1.0;
    for (const auto type : defender.View().spec.View().pokemon.types) effectiveness *= knowledge_.Efficacy(configured.move.type, type) / 100.0;
    if (effectiveness == 0) return branch;
    if (defender.View().spec.View().pokemon.ability == DamageAbility::inner_focus) {
      branch.events = AddEvent(branch.events, {.kind = BattleEventKind::ability_triggered, .turn_number = branch.state.View().turn_number,
          .actor = target, .target = move->side, .move_id = move->move_id, .source_identifier = "inner_focus"}, control_);
      branch.events = AddEvent(branch.events, {.kind = BattleEventKind::status_prevented, .turn_number = branch.state.View().turn_number,
          .actor = move->side, .target = target, .move_id = move->move_id, .source_identifier = "inner_focus"}, control_);
    } else {
      branch.state = branch.state.WithBattler(target, defender.WithStatus(defender.View().status.AddVolatile(FlinchStatus{})));
      branch.events = AddEvent(branch.events, {.kind = BattleEventKind::status_applied, .turn_number = branch.state.View().turn_number,
          .actor = move->side, .target = target, .move_id = move->move_id, .source_identifier = "fake_out"}, control_);
    }
    return branch;
  }
  /// @param inputs 当前阶段分支；@param action 本次固定行动；@return 完整命中/未命中及效果后的全局分支。
  [[nodiscard]] std::vector<Branch> Execute(std::span<const Branch> inputs, const BattleAction& action) const {
    Branches completed{control_}; const auto side = ActionSide(action); const auto target = Opposite(side);
    for (const auto& parent : inputs) {
      control_.Check(0, 0);
      const auto& actor = parent.state.Battler(side).View();
      if (actor.current_hp == 0 || parent.state.Battler(target).View().current_hp == 0 || std::holds_alternative<PassAction>(action)) {
        completed.Append(parent); continue;
      }
      const auto* move = std::get_if<UseMoveAction>(&action);
      const auto effect = move ? Effect(actor.spec.Move(move->move_id).View().effect_identifier) : MoveEffect::none;
      std::vector<std::string> blocked;
      if (actor.status.Has(VolatileStatusKind::flinch)) blocked.emplace_back("flinch");
      if (effect == MoveEffect::fake_out && !actor.is_first_turn) blocked.emplace_back("fake_out");
      if (!blocked.empty()) {
        auto branch = parent;
        for (const auto& source : blocked) branch.events = AddEvent(branch.events, {.kind = BattleEventKind::action_blocked,
            .turn_number = parent.state.View().turn_number, .actor = side, .target = target, .move_id = MoveId(action), .source_identifier = source}, control_);
        completed.Append(std::move(branch)); continue;
      }
      auto branch = parent;
      branch.events = AddEvent(branch.events, {.kind = BattleEventKind::move_used, .turn_number = parent.state.View().turn_number,
          .actor = side, .target = target, .move_id = MoveId(action), .source_identifier = ActionSource(action)}, control_);
      std::optional<DamageInput> before_pp;
      if (move && actor.spec.Move(move->move_id).View().move.category != DamageCategory::status)
        before_pp = parent.state.DamageInputFor(side, move->move_id, parent.state.View().rules.View().damage_policy);
      branch.state = Consume(branch.state, action);
      if (move) branch.events = AddEvent(branch.events, {.kind = BattleEventKind::pp_changed, .turn_number = parent.state.View().turn_number,
          .actor = side, .move_id = move->move_id, .source_identifier = "move-use", .before = Integer{parent.state.Battler(side).MoveSlot(move->move_id).View().current_pp},
          .after = Integer{branch.state.Battler(side).MoveSlot(move->move_id).View().current_pp}}, control_);
      const auto accuracy = move ? actor.spec.Move(move->move_id).View().accuracy : std::nullopt;
      const Rational hit_probability = accuracy ? Rational{*accuracy, parent.state.View().rules.View().move_execution_policy.accuracy_denominator} : Rational{1};
      const auto accuracy_branch = [&](bool hit) {
        auto checked = branch;
        checked.probability *= hit ? hit_probability : Rational{1} - hit_probability;
        if (hit_probability != Rational{1}) {
          checked.events = AddRandom(checked.events, TransitionEvent{{TransitionEventType::hit_check,
              "turn-" + std::to_string(branch.state.View().turn_number) + "-" + SideText(side) + "-move-" + std::to_string(move->move_id) + "-accuracy",
              hit ? "hit" : "miss"}}, control_);
          checked.source = "turn.accuracy";
        }
        checked.events = AddEvent(checked.events, {.kind = hit ? BattleEventKind::hit : BattleEventKind::miss,
            .turn_number = branch.state.View().turn_number, .actor = side, .target = target, .move_id = MoveId(action), .source_identifier = "accuracy"}, control_);
        return checked;
      };
      // 原结构化执行器先保存未命中，再依后继首次发现顺序保存命中伤害分支。
      if (hit_probability < Rational{1}) completed.Append(accuracy_branch(false));
      const auto hit = accuracy_branch(true);
      for (const auto& transition : Damage(hit.state, action, before_pp)) {
        const auto& value = transition.View();
        completed.Append(AfterDamage({hit.probability * value.probability, value.state,
            control_.Join(hit.events, value.events), value.source_key ? value.source_key : hit.source}, action));
      }
    }
    return completed.Take();
  }
  const TypeChartSnapshot& knowledge_;
  const TurnControl& control_;
};
} // namespace

StandardTurnResolver::StandardTurnResolver(TypeChartSnapshot knowledge) : knowledge_(std::move(knowledge)) {}

std::vector<UnsupportedAspect> StandardTurnResolver::CoverageLimitations(const BattleState& state) const {
  std::vector<UnsupportedAspect> result;
  for (const auto side : {BattleSide::attacker, BattleSide::defender}) {
    const auto& battler = state.Battler(side).View();
    for (const auto& move : battler.spec.View().moves) {
      const auto effect = Effect(move.View().effect_identifier);
      if (effect == MoveEffect::ice_punch) result.push_back({EffectSource::move, "ice_punch", "freeze_secondary_effect"});
      if (effect == MoveEffect::brick_break) result.push_back({EffectSource::move, "brick_break", "screen_break"});
    }
    if (battler.spec.View().pokemon.ability == DamageAbility::inner_focus) result.push_back({EffectSource::ability, "inner_focus", "intimidate_immunity"});
    if (battler.status.Major()) result.push_back({EffectSource::status, "major_status", "reference_default_turn_has_no_major_status_gates_or_residual_damage"});
    if (battler.status.Has(VolatileStatusKind::confusion) || battler.status.Has(VolatileStatusKind::infatuation))
      result.push_back({EffectSource::status, "volatile_status", "reference_default_turn_has_no_confusion_or_infatuation_gate"});
  }
  std::vector<UnsupportedAspect> unique;
  for (auto& aspect : result) if (std::find(unique.begin(), unique.end(), aspect) == unique.end()) unique.push_back(std::move(aspect));
  return unique;
}

TurnResolution StandardTurnResolver::Resolve(const BattleState& state, BattleAction attacker_action, BattleAction defender_action,
    TurnLimits limits, pbi::CancellationToken stop) const {
  auto limitations = CoverageLimitations(state);
  const TurnControl control{limits, stop};
  auto transitions = TurnExecution{knowledge_, control}.Run(state, {ValidateAction(std::move(attacker_action)), ValidateAction(std::move(defender_action))});
  return {std::move(transitions), stable_turn_phases, std::move(limitations)};
}

std::vector<BattleTransition> StandardTurnResolver::Expand(const BattleState& state, ActionPolicy attacker_policy,
    ActionPolicy defender_policy, TurnLimits limits, pbi::CancellationToken stop) const {
  static_cast<void>(CoverageLimitations(state));
  const TurnControl control{limits, stop};
  const TurnExecution execution{knowledge_, control};
  const auto first = SelectActions(GenerateLegalActions(state, BattleSide::attacker), attacker_policy);
  const auto second = SelectActions(GenerateLegalActions(state, BattleSide::defender), defender_policy);
  Branches combined{control};
  for (const auto& attacker : first) for (const auto& defender : second) {
    control.Check(0, 0);
    const auto transitions = execution.Run(state, {attacker.action, defender.action});
    const Rational selection = attacker.probability * defender.probability;
    for (const auto& transition : transitions) {
      const auto& value = transition.View();
      const auto outcome = selection.numerator().str() + "/" + selection.denominator().str() + "|"
          + value.probability.numerator().str() + "/" + value.probability.denominator().str();
      auto summary = AddRandom(value.events, TransitionEvent{{TransitionEventType::custom, "application.joint-action-probability", outcome}}, control);
      combined.Append({selection * value.probability, value.state, std::move(summary), value.source_key ? value.source_key : std::optional<std::string>{"battle.policy-and-turn"}});
    }
  }
  std::vector<BattleTransition> result;
  for (auto& branch : combined.Take()) result.emplace_back(BattleTransitionData{std::move(branch.probability), std::move(branch.state), std::move(branch.events), std::move(branch.source)});
  return MergeEquivalentTransitions(result);
}

FixedBattleComputation InferFixedBattle(BattleState initial, TypeChartSnapshot knowledge, FixedBattleOptions options,
    const GraphProgressObserver& progress, CancellationToken stop) {
  const StandardTurnResolver resolver{std::move(knowledge)};
  auto limitations = resolver.CoverageLimitations(initial);
  auto graph = BuildBattleGraph(std::move(initial), [&](const BattleState& state) {
    return resolver.Expand(state, options.attacker_policy, options.defender_policy, options.turn_limits, stop);
  }, options.graph_limits, progress, options.progress_interval, stop);
  auto solution = SolveGraph(graph.Topology(), options.observer, options.max_equation_nodes, stop);
  return {std::move(graph), std::move(solution), std::move(limitations)};
}
} // namespace pbi
