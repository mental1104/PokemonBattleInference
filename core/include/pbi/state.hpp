#pragma once
#include "pbi/status.hpp"
#include <array>
#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pbi {
/// 图节点的稳定两侧，不随本次攻击方向改变。
enum class BattleSide { attacker, defender };
/// 原状态模型的四个回合阶段。
enum class BattlePhase { action_selection, action_resolution, end_of_turn, terminal };
/// 可更新的七种能力等级字段。
enum class StatStageField { attack, defense, special_attack, special_defense, speed, accuracy, evasion };
/// 重复局面与封闭循环是不同策略，不把保护上限冒充循环证明。
enum class RepetitionResolution { declare_draw, continue_battle };
/// 封闭循环的终局或吸收概率求解策略，与重复局面处理独立。
enum class CycleResolution { declare_draw, solve_absorption_probability };
/// 当前推演支持的固定形式与交换策略；未知值在构造边界明确失败。
enum class BattleFormat { one_on_one_singles };
/// 当前只支持禁止主动交换，其他值在规则构造时拒绝。
enum class SwitchingPolicy { disabled };

/// 七个 -6…6 能力等级的不可变值；更新只返回新实例。
class StatStages {
public:
  /// @param values 按 StatStageField 顺序拥有的七项等级，越界抛 invalid_argument。
  explicit StatStages(std::array<std::int32_t, 7> values = {});
  /// @param field 有限能力字段；@return 原等级；未知字段明确失败。
  [[nodiscard]] std::int32_t Value(StatStageField field) const;
  /// @return 对象拥有的只读数组，引用不超过对象生命周期。
  [[nodiscard]] const std::array<std::int32_t, 7>& Values() const noexcept { return values_; }
  /// @param field 目标字段；@param value 合法等级；@return 新值，不修改原实例。
  [[nodiscard]] StatStages WithStage(StatStageField field, std::int32_t value) const;
  /// @param other 只读等级快照；@return 全部等级是否相同。
  bool operator==(const StatStages& other) const = default;
private:
  std::array<std::int32_t, 7> values_;
};

/// 招式动态槽的完整拥有值，只有通过 MoveSlotState 构造后才能进入战斗状态。
struct MoveSlotData {
  std::int64_t move_id;
  std::int32_t current_pp;
  std::int32_t max_pp;
  bool disabled = false;
  bool locked = false;
  std::int64_t slot_id = 0;
  /// @param other 只读槽位；@return 包含顺序身份的全部字段是否相同。
  bool operator==(const MoveSlotData& other) const = default;
};
/// 已验证的不可变动态槽；slot_id=0 在构造时按原合同规范化为 move_id。
class MoveSlotState {
public:
  /// @param data 转移拥有的完整槽位，非法 ID/PP 抛 invalid_argument。
  explicit MoveSlotState(MoveSlotData data);
  /// @return 只读已验证快照，调用者不得在本对象销毁后保留引用。
  [[nodiscard]] const MoveSlotData& View() const noexcept { return data_; }
  /// @param pp 新剩余 PP；@return 不改变原对象的新槽位。
  [[nodiscard]] MoveSlotState WithCurrentPp(std::int32_t pp) const;
  /// @param disabled 是否禁用；@return 新槽位。
  [[nodiscard]] MoveSlotState WithDisabled(bool disabled) const;
  /// @param locked 是否锁定；@return 新槽位，整体锁招不变量由 BattlerState 验证。
  [[nodiscard]] MoveSlotState WithLocked(bool locked) const;
  /// @param other 只读已验证槽位；@return 全部字段是否相同。
  bool operator==(const MoveSlotState& other) const = default;
private:
  MoveSlotData data_;
};

/// 不变招式完整配置；name 只展示，effect_identifier 为规范化机制标识。
struct MoveSpecData {
  std::int64_t move_id;
  std::string name;
  DamageMove move;
  std::int32_t max_pp;
  std::int32_t priority = 0;
  std::optional<std::int32_t> accuracy = 100;
  std::optional<std::string> effect_identifier;
};
/// 已验证的不变招式，语义相等性排除展示名称。
class MoveSpec {
public:
  /// @param data 转移拥有的招式配置；非法数值抛 invalid_argument。
  /// effect 标识按 ASCII 规则规范化，非 ASCII 机制标识显式 unsupported，不猜测 Unicode 映射。
  explicit MoveSpec(MoveSpecData data);
  /// @return 对象拥有的只读配置；不泄露可写别名。
  [[nodiscard]] const MoveSpecData& View() const noexcept { return data_; }
  /// @param other 只读招式；@return 除名称外的全部战斗字段是否相同。
  [[nodiscard]] bool operator==(const MoveSpec& other) const;
private:
  MoveSpecData data_;
};

/// 不变宝可梦拥有值；复用已存在的能力/属性/效果快照，不持有外部知识句柄。
struct PokemonSpecData {
  std::int64_t pokemon_id;
  std::string name;
  DamagePokemon pokemon;
  std::vector<MoveSpec> moves;
};
/// 已验证的不变宝可梦，强制 1…100 级、正能力、1…2 属性和 1…4 唯一招式。
class PokemonSpec {
public:
  /// @param data 转移拥有的完整配置；不满足原领域不变量时抛 invalid_argument。
  explicit PokemonSpec(PokemonSpecData data);
  /// @return 对象拥有的只读完整配置。
  [[nodiscard]] const PokemonSpecData& View() const noexcept { return data_; }
  /// @param move_id 当前已配置的招式 ID；@return 借用至配置销毁前的招式；缺失明确失败。
  [[nodiscard]] const MoveSpec& Move(std::int64_t move_id) const;
  /// @param other 只读配置；@return 除展示名外是否语义相等，招式/属性顺序保留。
  [[nodiscard]] bool operator==(const PokemonSpec& other) const;
private:
  PokemonSpecData data_;
};

/// 通用招式执行策略的值快照；概率始终为精确有理数。
struct MoveExecutionPolicy {
  std::int32_t accuracy_denominator = 100;
  bool consume_pp_on_miss = true;
  bool consume_pp_when_action_blocked = false;
  bool consume_pp_when_before_move_stops = false;
  std::int32_t struggle_power = 50;
  Rational struggle_recoil_fraction{1, 4};
  /// @param other 只读策略；@return 所有执行字段是否相同。
  bool operator==(const MoveExecutionPolicy& other) const = default;
};
/// 一次完整推演的规则拥有值，包含保护上限和全部未来相关策略。
struct InferenceRulesData {
  std::string ruleset_id = "pokemon-champion";
  std::int64_t version_group_id = 25;
  std::int32_t level = 50;
  BattleFormat battle_format = BattleFormat::one_on_one_singles;
  SwitchingPolicy switching_policy = SwitchingPolicy::disabled;
  bool allow_terastallization = false;
  bool allow_mega_evolution = false;
  bool allow_dynamax = false;
  std::optional<std::int64_t> max_turns = 100;
  RepetitionResolution repetition_resolution = RepetitionResolution::declare_draw;
  CycleResolution cycle_resolution = CycleResolution::declare_draw;
  DamagePolicy damage_policy;
  MoveExecutionPolicy move_execution_policy;
  /// @param other 只读规则；@return 所有未来相关规则字段是否相同。
  bool operator==(const InferenceRulesData& other) const = default;
};
/// 冻结并验证规则，不允许启用当前不支持的交换/形态变换或 PP 合同。
class InferenceRules {
public:
  /// @param data 转移拥有的规则；非法或不支持配置明确抛出异常。
  explicit InferenceRules(InferenceRulesData data = {});
  /// @return 只读已验证规则；引用依附本对象生命周期。
  [[nodiscard]] const InferenceRulesData& View() const noexcept { return data_; }
  /// @param other 只读规则；@return 语义是否相同。
  bool operator==(const InferenceRules& other) const = default;
private:
  InferenceRulesData data_;
};

/// 固定双方视角的场地；具体攻击方向在 DamageInputFor 中转换。
struct BattleFieldState {
  DamageWeather weather = DamageWeather::none;
  DamageTerrain terrain = DamageTerrain::none;
  DamageScreens attacker_side;
  DamageScreens defender_side;
  /// @param other 只读场地；@return 全部环境与边侧是否相同。
  bool operator==(const BattleFieldState& other) const = default;
};

/// 一方动态状态的拥有值；只有构造 BattlerState 后才成为可进入图的合法节点。
struct BattlerData {
  PokemonSpec spec;
  std::int32_t current_hp;
  std::vector<MoveSlotState> move_slots;
  StatStages stages;
  CombatantStatus status;
  std::optional<std::int64_t> last_move_id;
  std::optional<std::int64_t> choice_lock_move_id;
  bool item_consumed = false;
  bool is_first_turn = true;
};
/// 不可变的一方状态；每次更新重新验证 HP/PP/锁招合同，祖先与兄弟分支隔离。
class BattlerState {
public:
  /// @param data 转移拥有的完整状态；非法组合在构造时失败。
  explicit BattlerState(BattlerData data);
  /// @return 对象拥有的只读完整状态。
  [[nodiscard]] const BattlerData& View() const noexcept { return data_; }
  /// @param move_id 配置内招式；@return 对象拥有的只读槽位；缺失明确失败。
  [[nodiscard]] const MoveSlotState& MoveSlot(std::int64_t move_id) const;
  /// @param hp 新当前 HP；@return 已验证的新节点。
  [[nodiscard]] BattlerState WithCurrentHp(std::int32_t hp) const;
  /// @param slot 转移拥有的新槽位；@return 按 move_id 替换的新节点。
  [[nodiscard]] BattlerState WithMoveSlot(MoveSlotState slot) const;
  /// @param status 转移拥有的新状态集合；@return 新节点。
  [[nodiscard]] BattlerState WithStatus(CombatantStatus status) const;
  /// @param stages 新能力等级值；@return 新节点。
  [[nodiscard]] BattlerState WithStages(StatStages stages) const;
  /// @param move_id 新的上一招记录/null；@return 新节点，允许未配置的上一招 ID。
  [[nodiscard]] BattlerState WithLastMove(std::optional<std::int64_t> move_id) const;
  /// @param move_id 配置内锁招/null；@return 同步更新所有槽位 locked 标记的新节点。
  [[nodiscard]] BattlerState WithChoiceLock(std::optional<std::int64_t> move_id) const;
  /// @param consumed 道具是否消耗；@return 新节点；不会自动清除非法锁招。
  [[nodiscard]] BattlerState WithItemConsumed(bool consumed) const;
  /// @return 首次回合标记变为 false 的新节点。
  [[nodiscard]] BattlerState MarkFirstTurnComplete() const;
  /// @param other 只读一方节点；@return 排除展示字段后的全部语义是否相同。
  [[nodiscard]] bool operator==(const BattlerState& other) const;
private:
  BattlerData data_;
};

/// 图节点的规范键；内部编码无歧义地保存全部语义，排除名称与绝对回合号。
/// 编码仅为 Core 内部去重格式，不是网络/同步协议；相等性比较完整编码，哈希碰撞不会合并节点。
class StateKey {
public:
  /// @param other 只读规范键；@return 完整语义编码是否相同。
  bool operator==(const StateKey& other) const = default;
private:
  friend class BattleState;
  friend struct StateKeyHash;
  /// @param bytes 转移拥有的完整编码，仅允许已验证 BattleState 构造。
  explicit StateKey(std::string bytes) : bytes_(std::move(bytes)) {}
  std::string bytes_;
};
/// unordered_map/set 使用的显式哈希器，调用者仍由 StateKey 完整相等性处理碰撞。
struct StateKeyHash {
  /// @param key 只读规范键；@return 当前标准库的进程内哈希，不承诺跨进程/平台值一致。
  [[nodiscard]] std::size_t operator()(const StateKey& key) const { return std::hash<std::string>{}(key.bytes_); }
};

/// 一场 1v1 图节点的完整拥有值。
struct BattleStateData {
  BattlerState attacker;
  BattlerState defender;
  InferenceRules rules;
  std::int64_t turn_number = 1;
  BattleFieldState field;
  BattlePhase phase = BattlePhase::action_selection;
};
/// 不可变的完整战斗节点，更新/相对攻击快照都不修改祖先。
class BattleState {
public:
  /// @param data 转移拥有的节点；双方等级/规则和回合字段必须满足原合同。
  explicit BattleState(BattleStateData data);
  /// @return 对象拥有的只读完整节点。
  [[nodiscard]] const BattleStateData& View() const noexcept { return data_; }
  /// @param side 固定双方标识；@return 借用的只读一方状态。
  [[nodiscard]] const BattlerState& Battler(BattleSide side) const;
  /// @param side 固定双方标识；@return 借用的只读对手状态。
  [[nodiscard]] const BattlerState& Opponent(BattleSide side) const;
  /// @param side 固定双方标识；@param battler 转移拥有的新一方节点；@return 新战斗节点。
  [[nodiscard]] BattleState WithBattler(BattleSide side, BattlerState battler) const;
  /// @param phase 新的回合阶段；@return 新节点。
  [[nodiscard]] BattleState WithPhase(BattlePhase phase) const;
  /// @param field 新的固定双方场地；@return 新节点。
  [[nodiscard]] BattleState WithField(BattleFieldState field) const;
  /// @return 回合号加一并回到行动选择的新节点；int64 回合溢出明确失败。
  [[nodiscard]] BattleState NextTurn() const;
  /// @param side 本次行动的固定双方标识；@param move_id 当前可用的配置招式；@param policy 显式伤害策略副本。
  /// @return 按方向交换双方/屏障且禁用消耗道具的快照，不提前应用等级/实时状态效果或消耗 PP。
  [[nodiscard]] DamageInput DamageInputFor(BattleSide side, std::int64_t move_id, DamagePolicy policy) const;
  /// @return 拥有全部未来相关语义的规范键，排除绝对回合号与展示名。
  [[nodiscard]] StateKey Key() const;
  /// @param other 只读战斗节点；@return 与规范键一致的语义相等结果。
  [[nodiscard]] bool operator==(const BattleState& other) const;
private:
  BattleStateData data_;
};
/// @param battler 只读一方状态；@return 旧行动排序所用的等级后速度，不擅自叠加麻痹。
[[nodiscard]] std::int64_t EffectiveActionSpeed(const BattlerState& battler);
} // namespace pbi
