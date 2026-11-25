#include "pbi/state_graph_projection.hpp"
#include "sha256.hpp"
#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cctype>
#include <tuple>

namespace pbi {
namespace {
constexpr std::string_view metadata_id = "application.joint-action-probability";
constexpr std::array<std::string_view, 6> group_names{
    "action-selection", "action-order", "hit-check", "damage-distribution", "secondary-effect", "composite"};
constexpr std::array<std::string_view, 2> side_names{"attacker", "defender"};
/// @param stop 同源只读令牌；取消时整体失败，不能返回部分分组或路径。
void Check(CancellationToken stop) {
  if (stop.Requested()) throw std::runtime_error("state graph projection cancelled");
}
/// @tparam Value 可比较的拥有值；@param values 要显式追加的容器；@param value 只读候选。
/// @return 是否首次加入；去重保持原Python首次出现顺序。
template<class Value> bool AppendUnique(std::vector<Value>& values, const Value& value) {
  if (std::find(values.begin(), values.end(), value) != values.end()) return false;
  values.push_back(value);
  return true;
}
/// @param event 随机事件；@return 是否是不可向界面展示的内部联合行动概率。
bool IsMetadata(const TransitionEvent& event) {
  return event.View().type == TransitionEventType::custom && event.View().event_id == metadata_id;
}
/// 联合行动概率与条件随机概率是独立事实，不能按事件路径条数等分。
struct JointProbability {
  Rational selection;
  Rational random;
  /// @param other 只读元数据；@return 两个精确值是否相同。
  bool operator==(const JointProbability& other) const = default;
};
/// @param text 原十进制整数，兼容Python int的ASCII空白和符号；@return 任意精度整数。
Integer DecimalInteger(std::string_view text) {
  const auto whitespace = [](unsigned char value) { return std::isspace(value) != 0; };
  while (!text.empty() && whitespace(text.front())) text.remove_prefix(1);
  while (!text.empty() && whitespace(text.back())) text.remove_suffix(1);
  bool negative = false;
  if (!text.empty() && (text.front() == '+' || text.front() == '-')) { negative = text.front() == '-'; text.remove_prefix(1); }
  if (text.empty()) throw std::invalid_argument("invalid joint action probability integer");
  Integer value = 0;
  for (const char character : text) {
    if (character < '0' || character > '9') throw std::invalid_argument("invalid joint action probability integer");
    value = value * 10 + (character - '0');
  }
  return negative ? -value : value;
}
/// @param text 原n/d精确编码；@return 属于(0,1]的概率，非法或零分母明确失败。
Rational MetadataFraction(std::string_view text) {
  const auto slash = text.find('/');
  if (slash == std::string_view::npos) throw std::invalid_argument("invalid joint action probability payload");
  const auto numerator = DecimalInteger(text.substr(0, slash));
  const auto denominator = DecimalInteger(text.substr(slash + 1));
  if (denominator == 0) throw std::invalid_argument("invalid joint action probability denominator");
  const Rational value{numerator, denominator};
  if (value <= Rational{0} || value > Rational{1}) throw std::invalid_argument("joint action probability must be in (0, 1]");
  return value;
}
/// @param path 只读完整事件历史；@return 唯一可选元数据，重复即使相同也拒绝。
std::optional<JointProbability> ReadJointProbability(std::span<const PathEvent> path) {
  std::optional<JointProbability> result;
  for (const auto& value : path) if (const auto* event = std::get_if<TransitionEvent>(&value); event && IsMetadata(*event)) {
    if (result) throw std::invalid_argument("event path must contain at most one joint action probability event");
    const std::string_view text = event->View().outcome_id;
    const auto separator = text.find('|');
    if (separator == std::string_view::npos) throw std::invalid_argument("invalid joint action probability payload");
    result = JointProbability{MetadataFraction(text.substr(0, separator)), MetadataFraction(text.substr(separator + 1))};
  }
  return result;
}
/// 双方选招身份按稳定侧排列，来源保持原文而不假装已执行合法性校验。
using JointSignature = std::array<JointActionDetail, 2>;
/// @param path 只读业务/随机历史；@return 双方均有唯一选招时返回完整身份，否则为空。
std::optional<JointSignature> Signature(std::span<const PathEvent> path) {
  std::array<std::optional<JointActionDetail>, 2> actions;
  for (const auto& value : path) if (const auto* event = std::get_if<BattleEvent>(&value)) {
    const auto& data = event->View();
    if (data.kind != BattleEventKind::move_selected || !data.actor) continue;
    auto& selected = actions.at(static_cast<std::size_t>(*data.actor));
    const JointActionDetail action{*data.actor, data.source_identifier.value_or("unknown"), data.move_id};
    if (selected && *selected != action) throw std::invalid_argument("event path contains conflicting selected actions");
    selected = action;
  }
  if (!actions[0] || !actions[1]) return std::nullopt;
  return JointSignature{*actions[0], *actions[1]};
}
/// 原分组键，包括可选联合行动；hash只用于最终稳定groupID，不做身份相等判定。
struct GroupKey {
  TransitionGroupKind kind;
  std::string discriminator;
  std::optional<JointSignature> actions;
  /// @param other 只读键；@return 完整语义身份相同。
  bool operator==(const GroupKey& other) const = default;
};
/// 一条正式边对某联合行动的贡献；路径借用只在本次同步投影期间有效。
struct Contribution {
  const StateGraphProjectionEdge* edge;
  std::vector<const WeightedEventPath*> paths;
  Rational selection;
  Rational random;
};
/// 首次出现顺序的单组累加器，后续按正式edgeID稳定排序。
struct Accumulator { GroupKey key; std::vector<Contribution> contributions; };
/// @param action 只读选招事实；@return 原groupID输入的稳定明文片段。
std::string ActionDiscriminator(const JointActionDetail& action) {
  return std::string{side_names.at(static_cast<std::size_t>(action.side))} + ':' + action.action_type + ':'
      + (action.move_id ? std::to_string(*action.move_id) : "none");
}
/// @param type 原随机类别；@return 原首分叉类别，custom只进入composite。
TransitionGroupKind KindForEvent(TransitionEventType type) {
  switch (type) {
  case TransitionEventType::speed_tie: return TransitionGroupKind::action_order;
  case TransitionEventType::hit_check: return TransitionGroupKind::hit_check;
  case TransitionEventType::damage_roll: return TransitionGroupKind::damage_distribution;
  case TransitionEventType::secondary_effect: return TransitionGroupKind::secondary_effect;
  case TransitionEventType::custom: return TransitionGroupKind::composite;
  }
  throw std::invalid_argument("invalid transition event type");
}
/// @param type 随机事件类型；@return 原事件枚举的稳定名字。
std::string_view RandomName(TransitionEventType type) {
  constexpr std::array<std::string_view, 5> names{"hit_check", "damage_roll", "speed_tie", "secondary_effect", "custom"};
  return names.at(static_cast<std::size_t>(type));
}
/// @param path 原历史；@return 首个非custom随机来源，业务事件和内部元数据不造成分组。
std::optional<std::pair<TransitionEventType, std::string>> FirstRandom(std::span<const PathEvent> path) {
  for (const auto& value : path) if (const auto* event = std::get_if<TransitionEvent>(&value)) {
    if (event->View().type != TransitionEventType::custom) return std::pair{event->View().type, event->View().event_id};
  }
  return std::nullopt;
}
/// @param edge 原正式边；@param strategy 是否存在多个原选招签名；@return 兼容旧非完整联合行动图的原机制键。
GroupKey LegacyKey(const StateGraphProjectionEdge& edge, bool strategy) {
  if (strategy) return {TransitionGroupKind::action_selection, "policy-selection", std::nullopt};
  std::vector<std::pair<TransitionEventType, std::string>> firsts;
  for (const auto& path : edge.events.Paths()) if (const auto first = FirstRandom(path.events)) AppendUnique(firsts, *first);
  if (firsts.size() == 1) return {KindForEvent(firsts[0].first), firsts[0].second, std::nullopt};
  if (firsts.empty()) return {TransitionGroupKind::composite, edge.source_key.value_or("deterministic-transition"), std::nullopt};
  std::ranges::sort(firsts, [](const auto& first, const auto& second) {
    return std::pair{RandomName(first.first), first.second} < std::pair{RandomName(second.first), second.second};
  });
  std::string discriminator;
  for (const auto& [type, source] : firsts) { if (!discriminator.empty()) discriminator += '|'; discriminator += std::string{RandomName(type)} + ':' + source; }
  return {TransitionGroupKind::composite, std::move(discriminator), std::nullopt};
}
/// @param groups 显式修改的本地组集合；@param key 完整拥有键；@param contribution 仅借用本次输入的贡献。
void AddContribution(std::vector<Accumulator>& groups, GroupKey key, Contribution contribution) {
  const auto found = std::ranges::find(groups, key, &Accumulator::key);
  if (found == groups.end()) groups.push_back({std::move(key), {std::move(contribution)}});
  else found->contributions.push_back(std::move(contribution));
}
/// @param edges 只读完整出边；@param stop 协作取消；@return 原联合行动或旧首分叉分组，精确核对每条正式边。
std::vector<Accumulator> Accumulate(std::span<const StateGraphProjectionEdge> edges, CancellationToken stop) {
  bool joint = false;
  for (const auto& edge : edges) for (const auto& path : edge.events.Paths()) { Check(stop); joint = joint || Signature(path.events).has_value(); }
  std::vector<Accumulator> groups;
  if (!joint) {
    using Selection = std::vector<std::tuple<std::optional<BattleSide>, std::optional<std::int64_t>, std::optional<std::string>>>;
    std::vector<Selection> signatures;
    for (const auto& edge : edges) for (const auto& path : edge.events.Paths()) {
      Check(stop);
      Selection signature;
      for (const auto& value : path.events) if (const auto* event = std::get_if<BattleEvent>(&value); event && event->View().kind == BattleEventKind::move_selected) {
        const auto& data = event->View(); signature.emplace_back(data.actor, data.move_id, data.source_identifier);
      }
      AppendUnique(signatures, signature);
    }
    for (const auto& edge : edges) {
      Contribution contribution{&edge, {}, Rational{1}, edge.probability};
      for (const auto& path : edge.events.Paths()) contribution.paths.push_back(&path);
      AddContribution(groups, LegacyKey(edge, signatures.size() > 1), std::move(contribution));
    }
    return groups;
  }
  for (const auto& edge : edges) {
    Check(stop);
    std::vector<std::pair<JointSignature, std::vector<const WeightedEventPath*>>> by_action;
    for (const auto& path : edge.events.Paths()) {
      const auto signature = Signature(path.events);
      if (!signature) throw std::invalid_argument("joint action projection requires both MOVE_SELECTED events on every path");
      const auto found = std::ranges::find(by_action, *signature, &decltype(by_action)::value_type::first);
      if (found == by_action.end()) by_action.push_back({*signature, {&path}}); else found->second.push_back(&path);
    }
    Rational edge_probability{0};
    for (const auto& [actions, paths] : by_action) {
      std::vector<std::optional<JointProbability>> probabilities;
      for (const auto* path : paths) { Check(stop); AppendUnique(probabilities, ReadJointProbability(path->events)); }
      if (probabilities.size() != 1) throw std::invalid_argument("joint action paths on one edge must share identical probability metadata");
      auto metadata = probabilities.front();
      if (!metadata) {
        if (by_action.size() != 1) throw std::invalid_argument("merged edge with multiple joint actions requires exact probability metadata");
        metadata = JointProbability{Rational{1}, edge.probability};
      }
      edge_probability += metadata->selection * metadata->random;
      const auto discriminator = ActionDiscriminator(actions[0]) + '|' + ActionDiscriminator(actions[1]);
      AddContribution(groups, {TransitionGroupKind::action_selection, discriminator, actions}, {&edge, paths, metadata->selection, metadata->random});
    }
    if (edge_probability != edge.probability) throw std::invalid_argument("joint action probability metadata must reproduce the formal edge probability");
  }
  return groups;
}
/// @param outcome 原伤害档位结果ID；@return 合法roll-N索引；旧自定义ID没有档位事实。
std::optional<std::size_t> RollIndex(std::string_view outcome) {
  if (!outcome.starts_with("roll-")) return std::nullopt;
  outcome.remove_prefix(5);
  if (outcome.empty()) return std::nullopt;
  std::size_t index = 0;
  const auto result = std::from_chars(outcome.data(), outcome.data() + outcome.size(), index);
  if (result.ec != std::errc{} || result.ptr != outcome.data() + outcome.size()) return std::nullopt;
  return index;
}
/// @param state 原source状态；@param randoms 非元数据随机事实；@param battles 原业务事实。
/// @return 顺序配对的档位/伤害/实际扣血；不重算任何伤害公式。
std::vector<DamageRandomMetadata> DamageMetadata(const BattleState& state, std::span<const TransitionEvent> randoms,
    std::span<const BattleEvent> battles) {
  std::vector<Integer> losses;
  for (const auto& event : battles) {
    const auto& data = event.View();
    if (data.kind == BattleEventKind::damage && data.value && data.source_identifier != "struggle-recoil") losses.push_back(*data.value);
  }
  const auto& multipliers = state.View().rules.View().damage_policy.random_damage_multipliers;
  std::vector<DamageRandomMetadata> result;
  std::size_t damage_index = 0;
  for (const auto& event : randoms) {
    const auto& data = event.View();
    if (data.type != TransitionEventType::damage_roll || !data.numeric_value) continue;
    const auto index = RollIndex(data.outcome_id);
    if (index && *index < multipliers.size()) {
      // 原Python round采用ties-to-even，不能用总是远离零的std::round替代。
      const double scaled = multipliers[*index] * 100;
      const double lower = std::floor(scaled);
      const double delta = scaled - lower;
      const auto rounded = lower + (delta > 0.5 || (delta == 0.5 && std::fmod(lower, 2) != 0) ? 1 : 0);
      result.push_back({*index, Integer{rounded}, *data.numeric_value, damage_index < losses.size() ? losses[damage_index] : *data.numeric_value});
    }
    ++damage_index;
  }
  return result;
}
/// @param node 只读source；@param path 完整历史；@return 隐去内部元数据、保留原顺序的全部展示事实。
TransitionEventPathDetail PathDetail(const StateGraphProjectionNode& node, const WeightedEventPath& path) {
  TransitionEventPathDetail result;
  for (const auto& value : path.events) {
    if (const auto* event = std::get_if<TransitionEvent>(&value)) { if (!IsMetadata(*event)) result.random_results.push_back(*event); }
    else result.battle_events.push_back(std::get<BattleEvent>(value));
  }
  result.damage_rolls = DamageMetadata(node.state, result.random_results, result.battle_events);
  return result;
}
/// @param events 原业务事实；@return 状态施加或阻止事件的完整有序摘要。
std::vector<StatusEffectSummary> StatusEffects(std::span<const BattleEvent> events) {
  std::vector<StatusEffectSummary> result;
  for (const auto& event : events) {
    const auto& data = event.View();
    if (data.kind == BattleEventKind::status_applied || data.kind == BattleEventKind::status_prevented) {
      result.push_back({data.kind == BattleEventKind::status_applied ? StatusEffectResult::applied : StatusEffectResult::prevented,
          data.actor, data.target, data.source_identifier});
    }
  }
  return result;
}
/// @param events 非元数据随机事实；@return 原旧投影的暴击标识解释，未建模时为空。
std::optional<bool> CriticalHit(std::span<const TransitionEvent> events) {
  std::vector<std::string> tokens;
  for (const auto& event : events) {
    auto text = event.View().event_id + ':' + event.View().outcome_id;
    std::ranges::transform(text, text.begin(), [](unsigned char value) { return static_cast<char>(std::tolower(value)); });
    tokens.push_back(std::move(text));
  }
  for (const auto& token : tokens) if (token.find("non-critical") != std::string::npos || token.find("no-crit") != std::string::npos) return false;
  for (const auto& token : tokens) if (token.find("critical") != std::string::npos || token.find(":crit") != std::string::npos) return true;
  return std::nullopt;
}
/// @param events 原业务事件；@return 从选择、使用、命中、阻断及濒死事实得到的原行动读取模型。
std::vector<ActionResolutionDetail> ActionDetails(std::span<const BattleEvent> events) {
  std::vector<ActionResolutionDetail> result;
  std::array<std::optional<Integer>, 2> positions;
  std::array<bool, 2> used{}, fainted{};
  std::array<std::optional<std::string>, 2> blocked;
  std::array<std::optional<bool>, 2> hits;
  for (const auto& event : events) {
    const auto& data = event.View();
    if (!data.actor) continue;
    const auto side = static_cast<std::size_t>(*data.actor);
    switch (data.kind) {
    case BattleEventKind::action_ordered: if (data.value) positions.at(side) = data.value; break;
    case BattleEventKind::move_used: used.at(side) = true; break;
    case BattleEventKind::action_blocked: blocked.at(side) = data.source_identifier.value_or("action-blocked"); break;
    case BattleEventKind::hit: hits.at(side) = true; break;
    case BattleEventKind::miss: hits.at(side) = false; break;
    case BattleEventKind::fainted: fainted.at(side) = true; break;
    default: break;
    }
  }
  for (const auto& event : events) {
    const auto& data = event.View();
    if (data.kind != BattleEventKind::move_selected || !data.actor) continue;
    const auto side = static_cast<std::size_t>(*data.actor);
    const auto type = data.source_identifier.value_or("unknown");
    auto status = ActionResolutionStatus::cancelled;
    std::optional<std::string> reason;
    if (type == "pass") status = ActionResolutionStatus::passed;
    else if (used.at(side)) status = ActionResolutionStatus::executed;
    else if (blocked.at(side)) { status = ActionResolutionStatus::blocked; reason = blocked.at(side); }
    else reason = fainted.at(side) ? "fainted-before-action" : (fainted[0] || fainted[1]) ? "battle-ended-before-action" : "not-executed";
    result.push_back({{*data.actor, type, data.move_id}, positions.at(side), status, hits.at(side), reason});
  }
  std::ranges::stable_sort(result, [](const auto& first, const auto& second) {
    return std::tuple{!first.order_position, first.order_position.value_or(Integer{0}), side_names.at(static_cast<std::size_t>(first.action.side))}
        < std::tuple{!second.order_position, second.order_position.value_or(Integer{0}), side_names.at(static_cast<std::size_t>(second.action.side))};
  });
  return result;
}
/// @param first 已有紧凑结果；@param second 新路径结果；@return 忽略原始档位和路径数后的原归并键相等性。
bool SameCompactKey(const CompactRandomResult& first, const CompactRandomResult& second) {
  return first.target_node_id == second.target_node_id && first.action_resolutions == second.action_resolutions
      && first.order_reason == second.order_reason && first.critical_hit == second.critical_hit
      && first.final_damage_values == second.final_damage_values && first.actual_hp_losses == second.actual_hp_losses
      && first.status_effects == second.status_effects;
}
/// @param paths 展示路径事实；@param target 正式目标ID；@param stop 协作取消；@return 原离散伤害结果的稳定有序归并。
std::vector<CompactRandomResult> CompactResults(std::span<const TransitionEventPathDetail> paths, ProjectionNodeId target, CancellationToken stop) {
  std::vector<CompactRandomResult> result;
  for (const auto& path : paths) {
    Check(stop);
    const bool tie = std::ranges::any_of(path.random_results, [](const auto& event) { return event.View().type == TransitionEventType::speed_tie; });
    CompactRandomResult value{target, ActionDetails(path.battle_events), tie ? ActionOrderReason::speed_tie_random : ActionOrderReason::priority_modifier_speed,
        CriticalHit(path.random_results), {}, {}, {}, StatusEffects(path.battle_events), 1};
    for (const auto& damage : path.damage_rolls) { value.raw_roll_values.push_back(damage.raw_roll_value); value.final_damage_values.push_back(damage.final_damage); value.actual_hp_losses.push_back(damage.actual_hp_loss); }
    const auto found = std::ranges::find_if(result, [&](const auto& existing) { return SameCompactKey(existing, value); });
    if (found == result.end()) result.push_back(std::move(value));
    else { for (const auto& roll : value.raw_roll_values) AppendUnique(found->raw_roll_values, roll); ++found->path_count; }
  }
  return result;
}
/// @param paths 全部有序展示路径；@return 原label字段的稳定去重，不重排随机来源。
TransitionLabelFields Labels(std::span<const TransitionEventPathDetail> paths) {
  TransitionLabelFields result;
  for (const auto& path : paths) for (const auto& event : path.battle_events) {
    const auto& data = event.View();
    if (data.kind == BattleEventKind::move_selected && data.move_id) AppendUnique(result.selected_move_ids, *data.move_id);
    if (data.actor) AppendUnique(result.acting_sides, *data.actor);
    if (data.target) AppendUnique(result.target_sides, *data.target);
    if (data.source_identifier) AppendUnique(result.source_identifiers, *data.source_identifier);
  }
  for (const auto& path : paths) for (const auto& event : path.random_results) AppendUnique(result.result_keys, event.View().outcome_id);
  return result;
}
/// @param node source节点；@param contribution 正式边贡献；@param selection 策略概率；@param random 条件概率。
/// @param cumulative 根到source概率；@param stop 协作取消；@return 完整拥有outcome，全部乘法精确。
TransitionOutcome ProjectOutcome(const StateGraphProjectionNode& node, const Contribution& contribution, const Rational& selection,
    const Rational& random, const Rational& cumulative, CancellationToken stop) {
  std::vector<TransitionEventPathDetail> paths;
  for (const auto* path : contribution.paths) { Check(stop); paths.push_back(PathDetail(node, *path)); }
  TransitionOutcome result{contribution.edge->id, contribution.edge->target, random, selection * random, cumulative * selection * random,
      Labels(paths), {}, {}, {}, CompactResults(paths, contribution.edge->target, stop), {}, std::move(paths)};
  for (const auto& path : result.event_paths) {
    for (const auto& random_event : path.random_results) AppendUnique(result.random_results, random_event);
    for (const auto& damage : path.damage_rolls) { result.damage_rolls.push_back(damage); AppendUnique(result.raw_random_values, damage.raw_roll_value); }
    result.battle_event_paths.push_back(path.battle_events);
  }
  return result;
}
/// @param summary 显式更新的本地范围；@param damage 单个原始事实；仅聚合现存值，不添加推测值。
void AddDamage(TransitionGroupSummary& summary, const DamageRandomMetadata& damage) {
  if (!summary.minimum_damage || damage.final_damage < *summary.minimum_damage) summary.minimum_damage = damage.final_damage;
  if (!summary.maximum_damage || damage.final_damage > *summary.maximum_damage) summary.maximum_damage = damage.final_damage;
  if (!summary.minimum_hp_loss || damage.actual_hp_loss < *summary.minimum_hp_loss) summary.minimum_hp_loss = damage.actual_hp_loss;
  if (!summary.maximum_hp_loss || damage.actual_hp_loss > *summary.maximum_hp_loss) summary.maximum_hp_loss = damage.actual_hp_loss;
}
/// @param node 原source；@param group 拥有累加器；@param cumulative 根到source精确概率。
/// @param expanded 合法展开ID；@param stop 协作取消；@return 原groupID、选招概率与按需outcomes。
TransitionGroup ProjectGroup(const StateGraphProjectionNode& node, Accumulator group, const Rational& cumulative,
    std::span<const std::string> expanded, CancellationToken stop) {
  std::ranges::stable_sort(group.contributions, [](const auto& first, const auto& second) { return first.edge->id < second.edge->id; });
  const std::string kind{group_names.at(static_cast<std::size_t>(group.key.kind))};
  const auto node_text = node.id.value.str();
  const auto id = "tg-" + node_text + '-' + kind + '-' + detail::Sha256(node_text + '|' + kind + '|' + group.key.discriminator).substr(0, 16);
  Rational selection{0};
  if (group.key.actions) {
    selection = group.contributions.front().selection;
    Rational random_total{0};
    for (const auto& contribution : group.contributions) {
      if (contribution.selection != selection) throw std::invalid_argument("one joint action group must use one selection probability");
      random_total += contribution.random;
    }
    if (random_total != Rational{1}) throw std::invalid_argument("conditional random outcomes of one joint action must sum exactly to 1");
  } else for (const auto& contribution : group.contributions) selection += contribution.edge->probability;
  if (selection <= Rational{0}) throw std::invalid_argument("transition group probability must be positive");
  TransitionGroup result{id, group.key.kind, "battle.transition." + kind, selection,
      group.key.actions ? std::optional{(*group.key.actions)[0]} : std::nullopt,
      group.key.actions ? std::optional{(*group.key.actions)[1]} : std::nullopt,
      0, group.contributions.size(), {}, std::ranges::find(expanded, id) != expanded.end(), {}};
  for (const auto& contribution : group.contributions) {
    Check(stop);
    result.raw_result_count += contribution.paths.size();
    for (const auto* path : contribution.paths) for (const auto& damage : PathDetail(node, *path).damage_rolls) AddDamage(result.summary, damage);
    if (result.expanded) result.outcomes.push_back(ProjectOutcome(node, contribution, selection,
        group.key.actions ? contribution.random : contribution.edge->probability / selection, cumulative, stop));
  }
  return result;
}
} // namespace

StateGraphProjectionNode ProjectionRecord(const BattleGraphNode& node) {
  return {{Integer{node.id.value}}, node.state, node.outcome, node.reason};
}
StateGraphProjectionEdge ProjectionRecord(const BattleGraphEdge& edge) {
  return {{Integer{edge.id.value}}, {Integer{edge.source.value}}, {Integer{edge.target.value}}, edge.probability, edge.events, edge.source_key};
}

std::vector<RepresentativeBattlePath> ProjectRepresentativeBattlePaths(const BattleGraph& graph, CancellationToken stop) {
  std::vector<RepresentativeBattlePath> result;
  constexpr std::array<std::string_view, 3> names{"attacker-win", "defender-win", "draw"};
  for (const auto outcome : {GraphOutcome::attacker_win, GraphOutcome::defender_win, GraphOutcome::draw}) {
    Check(stop);
    const auto target = std::ranges::find(graph.Nodes(), outcome, &BattleGraphNode::outcome);
    if (target == graph.Nodes().end()) continue;
    RepresentativeBattlePath path{"path:" + std::string{names.at(static_cast<std::size_t>(outcome))} + ":node-" + std::to_string(target->id.value), outcome, {}};
    for (const auto id : graph.RepresentativePath(target->id)) {
      Check(stop);
      const auto& node = graph.Nodes()[id.value];
      const auto& state = node.state.View();
      std::vector<std::string> events;
      if (node.predecessor_edge) {
        const auto& edge = graph.Edges()[node.predecessor_edge->value];
        // 图中的 EventSummary 拥有历史；具名只读 span 避免新版 Clang 将临时视图误判为拥有者。
        const auto event_paths = edge.events.Paths();
        for (const auto& value : event_paths.front().events) {
          Check(stop);
          const auto event = std::visit([](const auto& item) {
            if constexpr (std::is_same_v<std::decay_t<decltype(item)>, TransitionEvent>) return item;
            else return item.Identity();
          }, value);
          const auto& data = event.View();
          auto label = std::string{RandomName(data.type)} + ':' + data.outcome_id;
          if (data.numeric_value) label += ':' + data.numeric_value->str();
          events.push_back(std::move(label));
        }
      }
      path.steps.push_back({{Integer{id.value}}, state.turn_number, state.phase, state.attacker.View().current_hp,
          state.defender.View().current_hp, node.outcome, std::move(events)});
    }
    result.push_back(std::move(path));
  }
  Check(stop);
  return result;
}

BattleReportStep ProjectBattleGraphStep(const StateGraphProjectionNode& node, const StateGraphProjectionEdge& edge,
    const Rational& cumulative, std::size_t depth, CancellationToken stop) {
  Check(stop);
  if (node.id.value < 0 || edge.id.value < 0 || edge.target.value < 0 || depth == 0 || cumulative < Rational{0} || cumulative > Rational{1} || edge.source != node.id
      || edge.probability <= Rational{0} || edge.probability > Rational{1}) {
    throw std::invalid_argument("invalid graph traversal step");
  }
  BattleReportStep result{depth, edge.source, edge.id, edge.target, edge.probability, cumulative * edge.probability, {}};
  for (const auto& path : edge.events.Paths()) { Check(stop); result.event_paths.push_back(PathDetail(node, path)); }
  Check(stop);
  return result;
}

BattleNodeProjection ProjectBattleGraphNode(const StateGraphProjectionNode& node, std::span<const StateGraphProjectionEdge> edges,
    const Rational& cumulative, std::span<const std::string> expanded, CancellationToken stop) {
  Check(stop);
  if (node.id.value < 0 || cumulative < Rational{0} || cumulative > Rational{1}) throw std::invalid_argument("cumulative_probability must be in [0, 1]");
  for (const auto& id : expanded) {
    if (id.empty() || std::isspace(static_cast<unsigned char>(id.front())) || std::isspace(static_cast<unsigned char>(id.back()))) {
      throw std::invalid_argument("expanded_group_ids must contain normalized non-empty strings");
    }
  }
  for (const auto& edge : edges) {
    if (edge.id.value < 0 || edge.target.value < 0 || edge.source != node.id || edge.probability <= Rational{0} || edge.probability > Rational{1}) throw std::invalid_argument("outgoing edge must belong to the projected node");
  }
  auto accumulators = Accumulate(edges, stop);
  BattleNodeProjection result{node, cumulative, {}, !edges.empty()};
  Rational total_selection{0};
  bool has_joint = false;
  for (auto& accumulator : accumulators) {
    auto group = ProjectGroup(node, std::move(accumulator), cumulative, expanded, stop);
    if (group.attacker_action) { total_selection += group.selection_probability; has_joint = true; }
    result.transition_groups.push_back(std::move(group));
  }
  if (has_joint && total_selection != Rational{1}) throw std::invalid_argument("joint action selection probabilities must sum exactly to 1");
  std::ranges::sort(result.transition_groups, [](const auto& first, const auto& second) { return std::pair{first.kind, first.group_id} < std::pair{second.kind, second.group_id}; });
  Check(stop);
  return result;
}
} // namespace pbi
