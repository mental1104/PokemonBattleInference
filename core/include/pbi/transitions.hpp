#pragma once

#include "pbi/state.hpp"
#include <span>
#include <string_view>
#include <variant>

namespace pbi {
/// 随机分支的五种稳定来源，与原 TransitionEventType 一致。
enum class TransitionEventType { hit_check, damage_roll, speed_tie, secondary_effect, custom };
/// 普通随机事件的拥有数据，整数解释值同样保留任意精度。
struct TransitionEventData {
  TransitionEventType type;
  std::string event_id;
  std::string outcome_id;
  std::optional<Integer> numeric_value = std::nullopt;
  /// @param other 只读事件；@return 全部来源和结果字段是否一致。
  bool operator==(const TransitionEventData& other) const = default;
};
/// 已验证随机事件，不允许空来源或空结果标识。
class TransitionEvent {
public:
  /// @param data 转移拥有的完整字段，非法标识/类型抛 invalid_argument。
  explicit TransitionEvent(TransitionEventData data);
  /// @return 对象拥有的只读数据，借用不超过本事件生命周期。
  [[nodiscard]] const TransitionEventData& View() const noexcept { return data_; }
  /// @param other 只读事件；@return 全部随机事件字段是否相同。
  bool operator==(const TransitionEvent& other) const = default;
private:
  TransitionEventData data_;
};
/// 不含展示文案的十六种结构化战斗事实。
enum class BattleEventKind { turn_started, move_selected, action_ordered, move_used, action_blocked, hit, miss,
  damage, hp_changed, pp_changed, ability_triggered, item_triggered, status_applied, status_prevented, fainted, turn_ended };
/// 一条业务事件的完整拥有字段，before/after 必须同时为空或同时有值。
struct BattleEventData {
  BattleEventKind kind;
  std::int64_t turn_number;
  std::optional<BattleSide> actor = std::nullopt;
  std::optional<BattleSide> target = std::nullopt;
  std::optional<std::int64_t> move_id = std::nullopt;
  std::optional<std::string> source_identifier = std::nullopt;
  std::optional<Integer> value = std::nullopt;
  std::optional<Integer> before = std::nullopt;
  std::optional<Integer> after = std::nullopt;
  /// @param other 只读事件；@return 所有显式业务字段是否相同。
  bool operator==(const BattleEventData& other) const = default;
};
/// 已验证且拥有的业务事件，兼容随机事件身份但不靠解析展示文字恢复事实。
class BattleEvent {
public:
  /// @param data 完整拥有值；value 为空且 before/after 存在时按原行为推导精确差值。
  explicit BattleEvent(BattleEventData data);
  /// @return 只读已解析业务字段；引用受本对象生命周期约束。
  [[nodiscard]] const BattleEventData& View() const noexcept { return data_; }
  /// @return 与原业务事件兼容的 custom 来源/结果/数值身份，返回拥有副本。
  [[nodiscard]] TransitionEvent Identity() const;
  /// @return before/after 的精确差值，非数值事件为 null。
  [[nodiscard]] std::optional<Integer> Delta() const;
  /// @param other 只读业务事件；@return 全部已解析字段是否相同。
  bool operator==(const BattleEvent& other) const = default;
private:
  BattleEventData data_;
};
/// 业务事件和普通随机事件保留不同类型，即使随机身份相同也不互相覆盖。
using PathEvent = std::variant<TransitionEvent, BattleEvent>;
/// 一条替代事件历史及其在当前后继状态条件下的精确概率。
struct WeightedEventPath { std::vector<PathEvent> events; Rational probability; };
/// 不可变事件摘要；同状态不同随机历史不拆开 StateKey，但完整保留条件权重。
class EventSummary {
public:
  /// @param paths 非空且条件概率精确和为一；相同完整历史按首次出现顺序合并。
  explicit EventSummary(std::vector<WeightedEventPath> paths = {{{}, Rational{1}}});
  /// @return 对象拥有的只读替代历史，不允许通过别名修改。
  [[nodiscard]] std::span<const WeightedEventPath> Paths() const noexcept { return paths_; }
  /// @param following 后执行阶段的摘要；@return 笛卡尔积历史，条件权重相乘，不修改两边。
  [[nodiscard]] EventSummary Concatenate(const EventSummary& following) const;
  /// @param other 到达同一状态的另一摘要；@param own_weight 当前绝对正权重。
  /// @param other_weight 另一绝对正权重；@return 按父分支相对权重重基准后的条件历史。
  [[nodiscard]] EventSummary MergeAlternatives(const EventSummary& other, const Rational& own_weight, const Rational& other_weight) const;
private:
  std::vector<WeightedEventPath> paths_;
};
/// 一条后继状态的完整拥有值；玩家选招权重不隐式混入本类型。
struct BattleTransitionData {
  Rational probability;
  BattleState state;
  EventSummary events;
  std::optional<std::string> source_key;
};
/// 已验证的不可变精确随机转移，祖先状态和事件没有可写别名。
class BattleTransition {
public:
  /// @param data 完整拥有值，概率必须在 (0,1]；非空来源不能全为空白。
  explicit BattleTransition(BattleTransitionData data);
  /// @return 只读拥有视图，引用受本对象生命周期约束。
  [[nodiscard]] const BattleTransitionData& View() const noexcept { return data_; }
private:
  BattleTransitionData data_;
};
/// 用于图构建及条件分支的实际回合级扩展合同，不执行环境或持久化操作。
using TransitionExpander = std::function<std::vector<BattleTransition>(const BattleState&)>;

/// @param kind 合法业务种类；@return 静态稳定标识，未知枚举抛 invalid_argument。
[[nodiscard]] std::string_view BattleEventName(BattleEventKind kind);
/// @param transitions 只读完整随机分支；非法空分布或非归一分布抛 invalid_argument。
void ValidateTransitions(std::span<const BattleTransition> transitions);
/// @param transitions 已归一化只读分布；@return 按首次 StateKey 顺序合并的新分布。
/// 事件条件权重按绝对概率重算，来源发生歧义时清空顶层 source_key，不丢弃路径。
[[nodiscard]] std::vector<BattleTransition> MergeEquivalentTransitions(std::span<const BattleTransition> transitions);
/// @param transitions 各正权重分支，允许总和非一；@return 先精确归一再归并的完整分布。
[[nodiscard]] std::vector<BattleTransition> NormalizeTransitionWeights(std::span<const BattleTransition> transitions);
/// @param parents 当前完整分布；@param expand 为每父状态生成完整条件分布，不修改父节点。
/// @param source_key 可空显式来源覆盖；@return 父子概率与条件历史相乘后按状态归并。
[[nodiscard]] std::vector<BattleTransition> BranchTransitions(std::span<const BattleTransition> parents,
    const TransitionExpander& expand, std::optional<std::string> source_key = std::nullopt);
} // namespace pbi
