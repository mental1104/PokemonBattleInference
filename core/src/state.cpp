#include "pbi/state.hpp"
#include <algorithm>
#include <bit>
#include <limits>
#include <stdexcept>
#include <tuple>
#include <type_traits>
#include <utility>

namespace pbi {
namespace {
/// @param value 枚举值；@param last 合法最大值；未知枚举明确失败，不回退默认。
template<class Enum> void RequireEnum(Enum value, Enum last) {
  if (static_cast<std::size_t>(value) > static_cast<std::size_t>(last)) throw std::invalid_argument("unsupported battle enum value");
}
/// @param value 只读 UTF-8 文本；@return 是否为 Python strip 后不会改变的非空文本。
bool NormalizedText(std::string_view value) {
  if (value.empty()) return false;
  // Python str.isspace 的 ASCII 和 Unicode 空白集合；这里只需检查首尾，不转写展示文案。
  constexpr std::array<std::string_view, 29> spaces{"\t", "\n", "\v", "\f", "\r", "\x1c", "\x1d", "\x1e", "\x1f", " ",
      "\xc2\x85", "\xc2\xa0", "\xe1\x9a\x80", "\xe2\x80\x80", "\xe2\x80\x81", "\xe2\x80\x82", "\xe2\x80\x83", "\xe2\x80\x84", "\xe2\x80\x85", "\xe2\x80\x86", "\xe2\x80\x87", "\xe2\x80\x88", "\xe2\x80\x89", "\xe2\x80\x8a", "\xe2\x80\xa8", "\xe2\x80\xa9", "\xe2\x80\xaf", "\xe2\x81\x9f", "\xe3\x80\x80"};
  return std::none_of(spaces.begin(), spaces.end(), [value](auto space) { return value.starts_with(space) || value.ends_with(space); });
}
/// @param value 转移拥有的 ASCII 机制标识；@return 旧 strip/lower/hyphen/space 规范形式，空值为 null。
std::optional<std::string> NormalizeEffect(std::optional<std::string> value) {
  if (!value) return std::nullopt;
  for (const unsigned char character : *value) {
    if (character > 127) throw UnsupportedRule("non-ASCII effect identifiers are unsupported");
  }
  const auto whitespace = [](unsigned char character) { return (character >= 9 && character <= 13) || (character >= 28 && character <= 32); };
  const auto first = std::find_if_not(value->begin(), value->end(), whitespace);
  const auto last = std::find_if_not(value->rbegin(), value->rend(), whitespace).base();
  if (first >= last) return std::nullopt;
  std::string result(first, last);
  for (auto& character : result) {
    if (character >= 'A' && character <= 'Z') character = static_cast<char>(character + ('a' - 'A'));
    else if (character == '-' || character == ' ') character = '_';
  }
  return result;
}

/// 无 JSON/平台服务的内部规范键编码器，所有序列/字符串均有长度，不以分隔符拼接字段。
class KeyWriter {
public:
  /// @param value 精确无符号位模式；按固定小端写入本实例。
  void Number(std::uint64_t value) { for (int byte = 0; byte < 8; ++byte) bytes_.push_back(static_cast<char>((value >> (byte * 8)) & 255)); }
  /// @param value 精确有符号值；模 2**64 转换避免实现相关移位。
  void Int(std::int64_t value) { Number(static_cast<std::uint64_t>(value)); }
  /// @param value 布尔语义，写入单字节。
  void Bool(bool value) { bytes_.push_back(value ? '\1' : '\0'); }
  /// @param value 只读字符串；复制长度及完整字节，允许内部 NUL，不保留引用。
  void Text(std::string_view value) { Number(value.size()); bytes_.append(value); }
  /// @param value 有限策略倍率；+0/-0 在语义相等时必须产生同一键。
  void Float(double value) { Number(std::bit_cast<std::uint64_t>(value == 0 ? 0.0 : value)); }
  /// @param value 精确分数；使用规范分子/分母，不转换为浮点数。
  void Fraction(const Rational& value) { Text(value.numerator().str()); Text(value.denominator().str()); }
  /// @param value 可空整数，null 与零明确区分。
  void OptionalInt(std::optional<std::int64_t> value) { Bool(value.has_value()); if (value) Int(*value); }
  /// @param value 只读可空字符串，null 与空字符串明确区分。
  void OptionalText(const std::optional<std::string>& value) { Bool(value.has_value()); if (value) Text(*value); }
  /// @param value 只读三种屏障，顺序固定。
  void Screens(const DamageScreens& value) { Bool(value.reflect); Bool(value.light_screen); Bool(value.aurora_veil); }
  /// @param value 只读完整伤害策略；所有原策略字段和随机槽位进入键。
  void Policy(const DamagePolicy& value) {
    for (const auto multiplier : {value.terrain_boost_multiplier, value.misty_terrain_dragon_multiplier,
        value.weather_boost_multiplier, value.weather_weaken_multiplier}) Float(multiplier);
    for (const auto multiplier : {value.sandstorm_rock_spdef_multiplier, value.snow_ice_defense_multiplier, value.hail_ice_defense_multiplier}) {
      Bool(multiplier.has_value()); if (multiplier) Float(*multiplier);
    }
    for (const auto multiplier : {value.screen_single_target_multiplier, value.screen_multi_target_multiplier,
        value.aurora_veil_single_target_multiplier, value.aurora_veil_multi_target_multiplier, value.critical_hit_multiplier,
        value.spread_move_multiplier, value.protect_damage_multiplier, value.same_type_attack_bonus_multiplier}) Float(multiplier);
    Int(value.technician_base_power_threshold);
    for (const auto multiplier : {value.technician_base_power_multiplier, value.adaptability_stab_multiplier, value.thick_fat_damage_multiplier,
        value.filter_damage_multiplier, value.sniper_critical_multiplier, value.multiscale_damage_multiplier, value.life_orb_damage_multiplier,
        value.choice_item_attack_multiplier, value.expert_belt_damage_multiplier, value.eviolite_defense_multiplier, value.burn_physical_attack_multiplier}) Float(multiplier);
    Number(value.random_damage_multipliers.size());
    for (const auto multiplier : value.random_damage_multipliers) Float(multiplier);
  }
  /// @param value 只读规则；回合保护与循环策略同样影响未来转移，不能漏掉。
  void Rules(const InferenceRulesData& value) {
    Text(value.ruleset_id); Int(value.version_group_id); Int(value.level);
    Int(static_cast<int>(value.battle_format)); Int(static_cast<int>(value.switching_policy));
    Bool(value.allow_terastallization); Bool(value.allow_mega_evolution); Bool(value.allow_dynamax);
    OptionalInt(value.max_turns); Int(static_cast<int>(value.repetition_resolution)); Int(static_cast<int>(value.cycle_resolution));
    Policy(value.damage_policy);
    const auto& execution = value.move_execution_policy;
    Int(execution.accuracy_denominator); Bool(execution.consume_pp_on_miss); Bool(execution.consume_pp_when_action_blocked);
    Bool(execution.consume_pp_when_before_move_stops); Int(execution.struggle_power); Fraction(execution.struggle_recoil_fraction);
  }
  /// @param value 只读状态集合，临时状态已经按种类规范排序。
  void Status(const CombatantStatus& value) {
    Bool(value.Major().has_value());
    if (value.Major()) {
      Number(value.Major()->index());
      // variant 固定状态种类；只有睡眠和剧毒持有主状态计数。
      std::visit([this](const auto& status) {
        using T = std::decay_t<decltype(status)>;
        if constexpr (std::is_same_v<T, SleepStatus>) Int(status.turns_asleep);
        else if constexpr (std::is_same_v<T, BadPoisonStatus>) Int(status.toxic_counter);
      }, *value.Major());
    }
    Number(value.Volatile().size());
    for (const auto& status : value.Volatile()) {
      Number(status.index());
      std::visit([this](const auto& item) {
        using T = std::decay_t<decltype(item)>;
        if constexpr (std::is_same_v<T, ConfusionStatus>) OptionalInt(item.turns_remaining);
        else if constexpr (std::is_same_v<T, InfatuationStatus>) OptionalText(item.source_id);
      }, status);
    }
  }
  /// @param value 只读一方节点，显式排除 Pokemon/Move 展示名称。
  void Battler(const BattlerData& value) {
    const auto& spec = value.spec.View();
    const auto& pokemon = spec.pokemon;
    Int(spec.pokemon_id); Int(pokemon.level); Number(pokemon.types.size());
    for (const auto type : pokemon.types) Int(static_cast<int>(type));
    const auto& stats = pokemon.stats;
    for (const auto stat : {stats.hp, stats.attack, stats.defense, stats.special_attack, stats.special_defense, stats.speed}) Int(stat);
    Int(static_cast<int>(pokemon.ability)); Int(static_cast<int>(pokemon.item)); Bool(pokemon.can_evolve);
    Bool(pokemon.grounding.has_value()); if (pokemon.grounding) Int(static_cast<int>(*pokemon.grounding));
    Number(spec.moves.size());
    for (const auto& move_spec : spec.moves) {
      const auto& move = move_spec.View();
      Int(move.move_id); Int(static_cast<int>(move.move.type)); Int(static_cast<int>(move.move.category)); Int(move.move.power);
      OptionalInt(move.accuracy); Int(move.max_pp); Int(move.priority); OptionalText(move.effect_identifier);
    }
    Int(value.current_hp); Number(value.move_slots.size());
    for (const auto& slot_value : value.move_slots) {
      const auto& slot = slot_value.View();
      Int(slot.move_id); Int(slot.current_pp); Int(slot.max_pp); Bool(slot.disabled); Bool(slot.locked); Int(slot.slot_id);
    }
    for (const auto stage : value.stages.Values()) Int(stage);
    Status(value.status); OptionalInt(value.last_move_id); OptionalInt(value.choice_lock_move_id);
    Bool(value.item_consumed); Bool(value.is_first_turn);
  }
  /// @return 移交本实例拥有的完整编码，调用后不再使用该编码器。
  std::string Finish() && { return std::move(bytes_); }
private:
  std::string bytes_;
};
} // namespace

StatStages::StatStages(std::array<std::int32_t, 7> values) : values_(values) {
  for (const auto stage : values_) if (stage < -6 || stage > 6) throw std::invalid_argument("stat stage must be between -6 and 6");
}
std::int32_t StatStages::Value(StatStageField field) const {
  RequireEnum(field, StatStageField::evasion);
  return values_[static_cast<std::size_t>(field)];
}
StatStages StatStages::WithStage(StatStageField field, std::int32_t value) const {
  static_cast<void>(Value(field));
  auto values = values_; values[static_cast<std::size_t>(field)] = value;
  return StatStages{values};
}
MoveSlotState::MoveSlotState(MoveSlotData data) : data_(data) {
  if (data_.slot_id == 0) data_.slot_id = data_.move_id;
  if (data_.move_id <= 0 || data_.slot_id <= 0) throw std::invalid_argument("move and slot ids must be positive");
  if (data_.max_pp <= 0 || data_.current_pp < 0 || data_.current_pp > data_.max_pp) throw std::invalid_argument("invalid move pp");
}
MoveSlotState MoveSlotState::WithCurrentPp(std::int32_t pp) const { auto copy = data_; copy.current_pp = pp; return MoveSlotState{copy}; }
MoveSlotState MoveSlotState::WithDisabled(bool disabled) const { auto copy = data_; copy.disabled = disabled; return MoveSlotState{copy}; }
MoveSlotState MoveSlotState::WithLocked(bool locked) const { auto copy = data_; copy.locked = locked; return MoveSlotState{copy}; }
MoveSpec::MoveSpec(MoveSpecData data) : data_(std::move(data)) {
  if (data_.move_id <= 0 || data_.max_pp <= 0 || (data_.accuracy && (*data_.accuracy < 1 || *data_.accuracy > 100))) {
    throw std::invalid_argument("invalid move specification");
  }
  const auto type = static_cast<int>(data_.move.type);
  if (type < 1 || type > 18) throw std::invalid_argument("invalid move type");
  RequireEnum(data_.move.category, DamageCategory::status);
  if (data_.move.category != DamageCategory::status && data_.move.power <= 0) throw std::invalid_argument("damaging moves need positive power");
  data_.effect_identifier = NormalizeEffect(std::move(data_.effect_identifier));
}
bool MoveSpec::operator==(const MoveSpec& other) const {
  return std::tie(data_.move_id, data_.move, data_.max_pp, data_.priority, data_.accuracy, data_.effect_identifier) ==
         std::tie(other.data_.move_id, other.data_.move, other.data_.max_pp, other.data_.priority, other.data_.accuracy, other.data_.effect_identifier);
}
std::optional<TransparentNeutralAbility> FindTransparentNeutralAbility(std::string_view identifier) {
  if (identifier == "pressure") return TransparentNeutralAbility::pressure;
  if (identifier == "pickpocket") return TransparentNeutralAbility::pickpocket;
  return std::nullopt;
}
std::string_view TransparentNeutralAbilityIdentifier(TransparentNeutralAbility ability) {
  switch (ability) {
    case TransparentNeutralAbility::pressure: return "pressure";
    case TransparentNeutralAbility::pickpocket: return "pickpocket";
  }
  throw UnsupportedRule("unsupported transparent ability identifier");
}
PokemonSpec::PokemonSpec(PokemonSpecData data) : data_(std::move(data)) {
  const auto& pokemon = data_.pokemon;
  if (data_.pokemon_id <= 0 || !NormalizedText(data_.name) || pokemon.level < 1 || pokemon.level > 100) throw std::invalid_argument("invalid pokemon identity or level");
  if (pokemon.types.empty() || pokemon.types.size() > 2 || (pokemon.types.size() == 2 && pokemon.types[0] == pokemon.types[1])) throw std::invalid_argument("pokemon types must be one or two unique values");
  for (const auto type : pokemon.types) {
    if (static_cast<int>(type) < 1 || static_cast<int>(type) > 18) throw std::invalid_argument("invalid pokemon type");
  }
  RequireEnum(pokemon.ability, DamageAbility::inner_focus); RequireEnum(pokemon.item, DamageItem::eviolite);
  if (data_.transparent_ability) {
    static_cast<void>(TransparentNeutralAbilityIdentifier(*data_.transparent_ability));
    // 原DamageAbility.from_identifier将两项及None/none都解析为UNKNOWN；既有Core枚举none是该UNKNOWN的历史ABI拼写。
    if (pokemon.ability != DamageAbility::none) throw std::invalid_argument("transparent unknown assumption conflicts with a known mechanical ability");
  }
  if (pokemon.grounding) RequireEnum(*pokemon.grounding, Grounding::airborne);
  const auto& stats = pokemon.stats;
  for (const auto stat : {stats.hp, stats.attack, stats.defense, stats.special_attack, stats.special_defense, stats.speed}) {
    if (stat <= 0) throw std::invalid_argument("all pokemon stats must be positive");
  }
  if (data_.moves.empty() || data_.moves.size() > 4) throw std::invalid_argument("pokemon must have one to four moves");
  for (std::size_t index = 0; index < data_.moves.size(); ++index) {
    for (std::size_t previous = 0; previous < index; ++previous) {
      if (data_.moves[index].View().move_id == data_.moves[previous].View().move_id) throw std::invalid_argument("configured move ids must be unique");
    }
  }
}
const MoveSpec& PokemonSpec::Move(std::int64_t move_id) const {
  for (const auto& move : data_.moves) if (move.View().move_id == move_id) return move;
  throw std::invalid_argument("move is not configured for pokemon");
}
bool PokemonSpec::operator==(const PokemonSpec& other) const {
  // 透明raw标识只解释原UNKNOWN假设，不进入原PokemonSpecKey或改变状态去重关系。
  return data_.pokemon_id == other.data_.pokemon_id && data_.pokemon == other.data_.pokemon && data_.moves == other.data_.moves;
}
InferenceRules::InferenceRules(InferenceRulesData data) : data_(std::move(data)) {
  if (!NormalizedText(data_.ruleset_id) || data_.version_group_id <= 0 || data_.level < 1 || data_.level > 100 ||
      (data_.max_turns && *data_.max_turns <= 0)) throw std::invalid_argument("invalid inference rules");
  if (data_.battle_format != BattleFormat::one_on_one_singles || data_.switching_policy != SwitchingPolicy::disabled ||
      data_.allow_terastallization || data_.allow_mega_evolution || data_.allow_dynamax) throw UnsupportedRule("unsupported battle format or transformation");
  RequireEnum(data_.repetition_resolution, RepetitionResolution::continue_battle);
  RequireEnum(data_.cycle_resolution, CycleResolution::solve_absorption_probability);
  ValidateDamagePolicy(data_.damage_policy);
  const auto& policy = data_.move_execution_policy;
  if (policy.accuracy_denominator != 100 || !policy.consume_pp_on_miss || policy.consume_pp_when_action_blocked || policy.consume_pp_when_before_move_stops) {
    throw UnsupportedRule("unsupported move execution policy");
  }
  if (policy.struggle_power <= 0 || policy.struggle_recoil_fraction <= Rational{0} || policy.struggle_recoil_fraction > Rational{1}) {
    throw std::invalid_argument("invalid struggle policy");
  }
}
BattlerState::BattlerState(BattlerData data) : data_(std::move(data)) {
  if (data_.current_hp < 0 || data_.current_hp > data_.spec.View().pokemon.stats.hp) throw std::invalid_argument("current hp is outside maximum hp");
  if (data_.move_slots.size() != data_.spec.View().moves.size()) throw std::invalid_argument("move slots must match configured moves");
  std::size_t locked = 0;
  for (std::size_t index = 0; index < data_.move_slots.size(); ++index) {
    const auto& slot = data_.move_slots[index].View();
    if (slot.max_pp != data_.spec.Move(slot.move_id).View().max_pp) throw std::invalid_argument("slot max pp must match move");
    for (std::size_t previous = 0; previous < index; ++previous) {
      if (data_.move_slots[previous].View().move_id == slot.move_id) throw std::invalid_argument("move slot ids must be unique");
    }
    if (slot.locked) {
      ++locked;
      if (!data_.choice_lock_move_id || slot.move_id != *data_.choice_lock_move_id) throw std::invalid_argument("slot lock disagrees with choice lock");
    }
  }
  if (data_.last_move_id && *data_.last_move_id <= 0) throw std::invalid_argument("last move id must be positive");
  if (data_.choice_lock_move_id) {
    static_cast<void>(data_.spec.Move(*data_.choice_lock_move_id));
    const auto item = data_.spec.View().pokemon.item;
    if (item != DamageItem::choice_band && item != DamageItem::choice_specs) throw std::invalid_argument("choice lock requires a choice item");
    if (data_.item_consumed || locked != 1) throw std::invalid_argument("choice lock must have one locked slot and an active item");
  }
}
const MoveSlotState& BattlerState::MoveSlot(std::int64_t move_id) const {
  for (const auto& slot : data_.move_slots) if (slot.View().move_id == move_id) return slot;
  throw std::invalid_argument("move id is not present in slots");
}
BattlerState BattlerState::WithCurrentHp(std::int32_t hp) const { auto copy = data_; copy.current_hp = hp; return BattlerState{std::move(copy)}; }
BattlerState BattlerState::WithMoveSlot(MoveSlotState slot) const {
  static_cast<void>(data_.spec.Move(slot.View().move_id));
  auto copy = data_;
  for (auto& existing : copy.move_slots) if (existing.View().move_id == slot.View().move_id) existing = slot;
  return BattlerState{std::move(copy)};
}
BattlerState BattlerState::WithStatus(CombatantStatus status) const { auto copy = data_; copy.status = std::move(status); return BattlerState{std::move(copy)}; }
BattlerState BattlerState::WithStages(StatStages stages) const { auto copy = data_; copy.stages = stages; return BattlerState{std::move(copy)}; }
BattlerState BattlerState::WithLastMove(std::optional<std::int64_t> move_id) const { auto copy = data_; copy.last_move_id = move_id; return BattlerState{std::move(copy)}; }
BattlerState BattlerState::WithChoiceLock(std::optional<std::int64_t> move_id) const {
  auto copy = data_; copy.choice_lock_move_id = move_id;
  for (auto& slot : copy.move_slots) slot = slot.WithLocked(move_id && slot.View().move_id == *move_id);
  return BattlerState{std::move(copy)};
}
BattlerState BattlerState::WithItemConsumed(bool consumed) const { auto copy = data_; copy.item_consumed = consumed; return BattlerState{std::move(copy)}; }
BattlerState BattlerState::MarkFirstTurnComplete() const { auto copy = data_; copy.is_first_turn = false; return BattlerState{std::move(copy)}; }
bool BattlerState::operator==(const BattlerState& other) const {
  return std::tie(data_.spec, data_.current_hp, data_.move_slots, data_.stages, data_.status, data_.last_move_id, data_.choice_lock_move_id, data_.item_consumed, data_.is_first_turn) ==
         std::tie(other.data_.spec, other.data_.current_hp, other.data_.move_slots, other.data_.stages, other.data_.status, other.data_.last_move_id, other.data_.choice_lock_move_id, other.data_.item_consumed, other.data_.is_first_turn);
}
BattleState::BattleState(BattleStateData data) : data_(std::move(data)) {
  if (data_.turn_number <= 0 || data_.attacker.View().spec.View().pokemon.level != data_.rules.View().level ||
      data_.defender.View().spec.View().pokemon.level != data_.rules.View().level) throw std::invalid_argument("invalid turn number or battle level");
  RequireEnum(data_.phase, BattlePhase::terminal); RequireEnum(data_.field.weather, DamageWeather::snow); RequireEnum(data_.field.terrain, DamageTerrain::misty);
}
const BattlerState& BattleState::Battler(BattleSide side) const {
  RequireEnum(side, BattleSide::defender); return side == BattleSide::attacker ? data_.attacker : data_.defender;
}
const BattlerState& BattleState::Opponent(BattleSide side) const {
  RequireEnum(side, BattleSide::defender); return side == BattleSide::attacker ? data_.defender : data_.attacker;
}
BattleState BattleState::WithBattler(BattleSide side, BattlerState battler) const {
  RequireEnum(side, BattleSide::defender);
  auto copy = data_;
  if (side == BattleSide::attacker) copy.attacker = std::move(battler); else copy.defender = std::move(battler);
  return BattleState{std::move(copy)};
}
BattleState BattleState::WithPhase(BattlePhase phase) const { auto copy = data_; copy.phase = phase; return BattleState{std::move(copy)}; }
BattleState BattleState::WithField(BattleFieldState field) const { auto copy = data_; copy.field = field; return BattleState{std::move(copy)}; }
BattleState BattleState::NextTurn() const {
  if (data_.turn_number == std::numeric_limits<std::int64_t>::max()) throw std::overflow_error("turn number exceeds int64 range");
  auto copy = data_; ++copy.turn_number; copy.phase = BattlePhase::action_selection; return BattleState{std::move(copy)};
}
DamageInput BattleState::DamageInputFor(BattleSide side, std::int64_t move_id, DamagePolicy policy) const {
  const auto& attacker = Battler(side).View();
  const auto& defender = Opponent(side).View();
  const auto& slot = Battler(side).MoveSlot(move_id).View();
  if (slot.current_pp <= 0 || slot.disabled || (attacker.choice_lock_move_id && *attacker.choice_lock_move_id != move_id)) {
    throw std::invalid_argument("damage move is unavailable or violates choice lock");
  }
  auto attacking = attacker.spec.View().pokemon;
  auto defending = defender.spec.View().pokemon;
  if (attacker.item_consumed) attacking.item = DamageItem::none;
  if (defender.item_consumed) defending.item = DamageItem::none;
  return {std::move(attacking), std::move(defending), attacker.spec.Move(move_id).View().move, std::move(policy),
          data_.field.weather, data_.field.terrain, side == BattleSide::attacker ? data_.field.defender_side : data_.field.attacker_side,
          false, false, false, false};
}
StateKey BattleState::Key() const {
  KeyWriter writer;
  writer.Text("PBI-state-v1"); writer.Battler(data_.attacker.View()); writer.Battler(data_.defender.View());
  writer.Int(static_cast<int>(data_.field.weather)); writer.Int(static_cast<int>(data_.field.terrain));
  writer.Screens(data_.field.attacker_side); writer.Screens(data_.field.defender_side);
  writer.Int(static_cast<int>(data_.phase)); writer.Rules(data_.rules.View());
  return StateKey{std::move(writer).Finish()};
}
bool BattleState::operator==(const BattleState& other) const {
  return data_.attacker == other.data_.attacker && data_.defender == other.data_.defender &&
         data_.field == other.data_.field && data_.phase == other.data_.phase && data_.rules == other.data_.rules;
}
std::int64_t EffectiveActionSpeed(const BattlerState& battler) {
  return ApplyStatStage(battler.View().spec.View().pokemon.stats.speed, battler.View().stages.Value(StatStageField::speed));
}
} // namespace pbi
