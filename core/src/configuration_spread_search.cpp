#include "pbi/configuration_spread_search.hpp"
#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <tuple>

namespace pbi {
namespace {
using Spread = std::array<std::int32_t, 6>;
constexpr Spread perfect_ivs{31, 31, 31, 31, 31, 31};
constexpr std::array<std::string_view, 25> preference{"adamant", "modest", "bold", "calm", "impish", "careful", "jolly", "timid",
    "brave", "quiet", "relaxed", "sassy", "hardy", "docile", "serious", "bashful", "quirky", "lonely", "naughty", "lax", "hasty", "naive", "mild", "rash", "gentle"};
/// @param value 六项能力拥有值；@return 固定轴数组。
Spread Values(const BattleStats& value) { return {value.hp, value.attack, value.defense, value.special_attack, value.special_defense, value.speed}; }
/// @param value 六项固定轴数组；@return 不保留借用的完整能力值。
BattleStats Stats(const Spread& value) { return {value[0], value[1], value[2], value[3], value[4], value[5]}; }
/// @param spread EV六项；@return 精确有界总投入。
std::int32_t Total(const Spread& spread) {
  std::int32_t total = 0;
  for (const auto value : spread) total += value;
  return total;
}
/// @param stop 同源令牌；取消时整体失败，不返回未完成候选。
void CheckStop(const CancellationToken& stop) {
  if (stop.Requested()) throw std::runtime_error("configuration spread search cancelled");
}
/// @param identifier 25项原知识ID；@return 原偏好索引，未知知识不回退为中性。
std::size_t Preference(std::string_view identifier) {
  const auto found = std::ranges::find(preference, identifier);
  if (found == preference.end()) throw UnsupportedRule("unknown configuration search nature identifier");
  return static_cast<std::size_t>(found - preference.begin());
}
/// 性格代表借用输入知识，只在本次搜索调用期间存活；options拥有对外值。
struct NatureGroup {
  const ConfigurationSearchNature* representative;
  std::vector<ConfigurationNatureOption> options;
};
/// @param input 原双类目标及完整性格知识；@return 按相关倍率归并并按原偏好排序的组。
std::vector<NatureGroup> NatureGroups(const ConfigurationSpreadSearchInput& input) {
  if (input.natures.size() != preference.size()) throw std::invalid_argument("configuration spread search requires all 25 natures");
  std::vector<std::size_t> relevant;
  for (const auto& goal : input.goals) {
    if (goal.kind != ConfigurationGoalKind::attack && goal.kind != ConfigurationGoalKind::defense) throw std::invalid_argument("unknown configuration goal kind");
    if (goal.move.category != DamageCategory::physical && goal.move.category != DamageCategory::special) throw UnsupportedRule("configuration spread goals require damaging moves");
    const auto field = goal.kind == ConfigurationGoalKind::attack
        ? (goal.move.category == DamageCategory::physical ? std::size_t{0} : std::size_t{2})
        : (goal.move.category == DamageCategory::physical ? std::size_t{1} : std::size_t{3});
    if (std::ranges::find(relevant, field) == relevant.end()) relevant.push_back(field);
  }
  if (!input.speed_goals.empty()) relevant.push_back(4);
  std::set<std::string> identifiers;
  std::map<std::vector<double>, std::vector<const ConfigurationSearchNature*>> grouped;
  for (const auto& nature : input.natures) {
    static_cast<void>(Preference(nature.identifier));
    if (!identifiers.insert(nature.identifier).second) throw std::invalid_argument("configuration search natures must be unique");
    for (const auto multiplier : nature.modifier.multipliers) {
      if (!std::isfinite(multiplier)) throw std::invalid_argument("configuration nature multipliers must be finite");
    }
    std::vector<double> key;
    for (const auto index : relevant) key.push_back(nature.modifier.multipliers[index]);
    grouped[std::move(key)].push_back(&nature);
  }
  std::vector<NatureGroup> result;
  for (auto& [key, definitions] : grouped) {
    static_cast<void>(key);
    std::ranges::sort(definitions, [](const auto* first, const auto* second) { return Preference(first->identifier) < Preference(second->identifier); });
    std::vector<ConfigurationNatureOption> options;
    for (const auto* nature : definitions) options.push_back({nature->identifier, nature->label});
    result.push_back({definitions.front(), std::move(options)});
  }
  std::ranges::sort(result, [](const auto& first, const auto& second) {
    return Preference(first.representative->identifier) < Preference(second.representative->identifier);
  });
  return result;
}
/// @param input 原固定subject；@param nature 代表性格；@param evs 当前EV；@param ivs 当前IV。
/// @return 同一已有Core能力公式计算的完整六项实际值。
BattleStats Actual(const ConfigurationSpreadSearchInput& input, const ConfigurationSearchNature& nature,
                   const Spread& evs, const Spread& ivs) {
  return CalculateConfigurationStats(input.subject.base, input.subject.level, {Stats(ivs), Stats(evs), nature.modifier});
}
/// @param input 固定subject机制；@param actual 已算能力；@return 同一目标求值器的轻量输入。
ConfigurationGoalPokemon Pokemon(const ConfigurationSpreadSearchInput& input, const BattleStats& actual) {
  return {input.subject.types, actual, input.subject.ability, input.subject.item};
}
/// @param goals 完整只读目标；@param kind 方向；@param category 分类；@return 指向输入的稳定子集。
std::vector<const ConfigurationDamageGoal*> Subset(const std::vector<ConfigurationDamageGoal>& goals,
    ConfigurationGoalKind kind, DamageCategory category) {
  std::vector<const ConfigurationDamageGoal*> result;
  for (const auto& goal : goals) if (goal.kind == kind && goal.move.category == category) result.push_back(&goal);
  return result;
}
/// @param maximum 仍可投入的最大EV；@param predicate 单调真实目标验收；@return 首个4EV网格可行值或无解。
template<class Predicate> std::optional<std::int32_t> MinimumGrid(std::int32_t maximum, Predicate&& predicate) {
  if (maximum < 0) return std::nullopt;
  const auto last = maximum / 4;
  if (!predicate(last * 4)) return std::nullopt;
  std::int32_t low = 0, high = last;
  while (low < high) {
    const auto middle = low + (high - low) / 2;
    if (predicate(middle * 4)) high = middle;
    else low = middle + 1;
  }
  return low * 4;
}
/// @param current 已知可行代表单项；@param predicate 其余五项不变的真实目标验收；@return 最小安全整数。
template<class Predicate> std::int32_t MinimumInteger(std::int32_t current, Predicate&& predicate) {
  std::int32_t low = 0, high = current;
  while (low < high) {
    const auto middle = low + (high - low) / 2;
    if (predicate(middle)) high = middle;
    else low = middle + 1;
  }
  return low;
}
/// @param input 全部知识；@param evaluator 真实共享目标器；@param nature 当前性格；@param base 已固定投入。
/// @param axis 待搜索六项轴；@param goals 仅相关同类目标；@param stop 同源取消；@return 最小有效EV或无解。
std::optional<std::int32_t> MinimumGoalEv(const ConfigurationSpreadSearchInput& input, const ConfigurationGoalEvaluator& evaluator,
    const ConfigurationSearchNature& nature, const Spread& base, std::size_t axis,
    const std::vector<const ConfigurationDamageGoal*>& goals, const CancellationToken& stop) {
  if (goals.empty()) return 0;
  const auto maximum = std::min(252, base[axis] + 510 - Total(base));
  return MinimumGrid(maximum, [&](std::int32_t value) {
    CheckStop(stop);
    auto evs = base;
    evs[axis] = value;
    const auto subject = Pokemon(input, Actual(input, nature, evs, perfect_ivs));
    for (const auto* goal : goals) if (!evaluator.Evaluate(subject, input.subject.level, *goal).satisfied) return false;
    return true;
  });
}
/// @param input 固定知识和全部速度参照；@param evaluator 真实速度器；@param nature 代表性格。
/// @param base 已固定攻防投入；@param stop 同源取消；@return 最小严格超过全部速度线的4EV网格值。
std::optional<std::int32_t> MinimumSpeedEv(const ConfigurationSpreadSearchInput& input, const ConfigurationGoalEvaluator& evaluator,
    const ConfigurationSearchNature& nature, const Spread& base, const CancellationToken& stop) {
  if (input.speed_goals.empty()) return 0;
  const auto maximum = std::min(252, base[5] + 510 - Total(base));
  return MinimumGrid(maximum, [&](std::int32_t value) {
    CheckStop(stop);
    auto evs = base;
    evs[5] = value;
    const auto results = evaluator.EvaluateSpeedGoals(Actual(input, nature, evs, perfect_ivs), input.speed_goals);
    return std::ranges::all_of(results, [](const auto& goal) { return goal.satisfied; });
  });
}
/// 已完成全部目标复核的原始候选，不含尚未计算的独立区间。
struct RawCandidate {
  std::size_t group;
  Spread evs;
  BattleStats stats;
  std::vector<ConfigurationDamageGoalResult> goals;
  std::vector<ConfigurationSpeedGoalResult> speed_goals;
};
/// @param candidate 真实可行代表；@param groups 当前性格组；@return 原总EV/投入项数/性格ID/六EV的排序键。
auto SortKey(const RawCandidate& candidate, const std::vector<NatureGroup>& groups) {
  const auto invested = std::ranges::count_if(candidate.evs, [](auto value) { return value > 0; });
  return std::tuple{Total(candidate.evs), invested, std::string_view{groups[candidate.group].representative->identifier}, candidate.evs};
}
/// @param input 全部双类目标；@param evaluator 共享真实求值器；@param stats 当前实际能力。
/// @return 按原短路顺序的完整满足性，不反推或放宽目标。
bool Satisfied(const ConfigurationSpreadSearchInput& input, const ConfigurationGoalEvaluator& evaluator, const BattleStats& stats) {
  const auto subject = Pokemon(input, stats);
  for (const auto& goal : input.goals) if (!evaluator.Evaluate(subject, input.subject.level, goal).satisfied) return false;
  const auto speed = evaluator.EvaluateSpeedGoals(stats, input.speed_goals);
  return std::ranges::all_of(speed, [](const auto& goal) { return goal.satisfied; });
}
/// @param input 固定知识；@param evaluator 真实目标器；@param nature 代表性格；@param evs/ivs 代表投入。
/// @param ev 是否求EV而非IV区间；@param stop 同源取消；@return 其余五项固定的六个独立区间。
ConfigurationSpreadRanges Ranges(const ConfigurationSpreadSearchInput& input, const ConfigurationGoalEvaluator& evaluator,
    const ConfigurationSearchNature& nature, const Spread& evs, const Spread& ivs, bool ev, const CancellationToken& stop) {
  ConfigurationSpreadRanges result{};
  const auto& spread = ev ? evs : ivs;
  for (std::size_t axis = 0; axis < spread.size(); ++axis) {
    CheckStop(stop);
    const auto minimum = MinimumInteger(spread[axis], [&](std::int32_t value) {
      auto candidate = spread;
      candidate[axis] = value;
      return Satisfied(input, evaluator, Actual(input, nature, ev ? candidate : evs, ev ? ivs : candidate));
    });
    result[axis] = {minimum, ev ? std::min(252, spread[axis] + 510 - Total(spread)) : 31};
  }
  return result;
}
} // namespace

ConfigurationSpreadSolution SearchConfigurationSpreads(const ConfigurationSpreadSearchInput& input,
    const ConfigurationGoalEvaluator& evaluator, CancellationToken cancellation) {
  CheckStop(cancellation);
  if (input.goals.empty() && input.speed_goals.empty()) throw std::invalid_argument("at least one configuration spread goal is required");
  if (input.max_candidates < 1 || input.max_candidates > 10) throw std::invalid_argument("max_candidates must be between 1 and 10");
  std::set<std::string> goal_ids;
  for (const auto& goal : input.goals) if (!goal_ids.insert(goal.goal_id).second) throw std::invalid_argument("configuration goal IDs must be unique");
  for (const auto& goal : input.speed_goals) if (!goal_ids.insert(goal.goal_id).second) throw std::invalid_argument("configuration goal IDs must be unique across damage and speed goals");
  const auto groups = NatureGroups(input);
  const auto attack = Subset(input.goals, ConfigurationGoalKind::attack, DamageCategory::physical);
  const auto special_attack = Subset(input.goals, ConfigurationGoalKind::attack, DamageCategory::special);
  const auto defense = Subset(input.goals, ConfigurationGoalKind::defense, DamageCategory::physical);
  const auto special_defense = Subset(input.goals, ConfigurationGoalKind::defense, DamageCategory::special);
  std::vector<RawCandidate> raw;
  std::map<std::pair<std::size_t, Spread>, std::size_t> deduplicated;
  for (std::size_t group = 0; group < groups.size(); ++group) {
    CheckStop(cancellation);
    const auto& nature = *groups[group].representative;
    const auto attack_ev = MinimumGoalEv(input, evaluator, nature, {}, 1, attack, cancellation);
    const auto special_attack_ev = MinimumGoalEv(input, evaluator, nature, {}, 3, special_attack, cancellation);
    if (!attack_ev || !special_attack_ev) continue;
    Spread offensive{0, *attack_ev, 0, *special_attack_ev, 0, 0};
    const auto speed_ev = MinimumSpeedEv(input, evaluator, nature, offensive, cancellation);
    if (!speed_ev) continue;
    const auto fixed = *attack_ev + *special_attack_ev + *speed_ev;
    for (std::int32_t hp = 0; hp <= 252; hp += 4) {
      CheckStop(cancellation);
      // 实际WithSpeed入口先过滤总量再构造StatSpread，避免旧基础用例的构造前越界路径。
      if (fixed + hp > 510) break;
      const Spread base{hp, *attack_ev, 0, *special_attack_ev, 0, *speed_ev};
      const auto defense_ev = MinimumGoalEv(input, evaluator, nature, base, 2, defense, cancellation);
      const auto special_defense_ev = MinimumGoalEv(input, evaluator, nature, base, 4, special_defense, cancellation);
      if (!defense_ev || !special_defense_ev || fixed + hp + *defense_ev + *special_defense_ev > 510) continue;
      Spread evs{hp, *attack_ev, *defense_ev, *special_attack_ev, *special_defense_ev, *speed_ev};
      const auto stats = Actual(input, nature, evs, perfect_ivs);
      const auto subject = Pokemon(input, stats);
      std::vector<ConfigurationDamageGoalResult> goals;
      for (const auto& goal : input.goals) goals.push_back(evaluator.Evaluate(subject, input.subject.level, goal));
      auto speed = evaluator.EvaluateSpeedGoals(stats, input.speed_goals);
      if (!std::ranges::all_of(goals, [](const auto& goal) { return goal.satisfied; }) ||
          !std::ranges::all_of(speed, [](const auto& goal) { return goal.satisfied; })) continue;
      RawCandidate candidate{group, evs, stats, std::move(goals), std::move(speed)};
      const auto [entry, inserted] = deduplicated.emplace(std::pair{group, Values(stats)}, raw.size());
      if (inserted) raw.push_back(std::move(candidate));
      else if (SortKey(candidate, groups) < SortKey(raw[entry->second], groups)) raw[entry->second] = std::move(candidate);
    }
  }
  std::ranges::sort(raw, [&groups](const auto& first, const auto& second) { return SortKey(first, groups) < SortKey(second, groups); });
  ConfigurationSpreadSolution result;
  const auto selected = std::min(raw.size(), input.max_candidates);
  for (std::size_t index = 0; index < selected; ++index) {
    CheckStop(cancellation);
    auto& candidate = raw[index];
    const auto& group = groups[candidate.group];
    const auto& nature = *group.representative;
    auto id = "spread-" + std::to_string(index + 1) + '-' + nature.identifier;
    for (const auto value : candidate.evs) id += '-' + std::to_string(value);
    result.candidates.push_back({std::move(id), nature.identifier, nature.label, group.options, Stats(candidate.evs), Stats(perfect_ivs),
        Ranges(input, evaluator, nature, candidate.evs, perfect_ivs, true, cancellation),
        Ranges(input, evaluator, nature, candidate.evs, perfect_ivs, false, cancellation), candidate.stats,
        std::move(candidate.goals), std::move(candidate.speed_goals)});
  }
  if (!result.Reachable()) {
    const auto stats = Actual(input, *groups.front().representative, {}, perfect_ivs);
    const auto subject = Pokemon(input, stats);
    for (const auto& goal : input.goals) result.rejected_goals.push_back(evaluator.Evaluate(subject, input.subject.level, goal));
    result.rejected_speed_goals = evaluator.EvaluateSpeedGoals(stats, input.speed_goals);
  }
  return result;
}
} // namespace pbi
