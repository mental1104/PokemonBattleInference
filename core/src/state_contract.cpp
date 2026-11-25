#include "state_contract.hpp"
#include <type_traits>

namespace pbi::contract {
namespace {
constexpr std::array<std::string_view, 2> sides{"attacker", "defender"};
constexpr std::array<std::string_view, 4> phases{"action-selection", "action-resolution", "end-of-turn", "terminal"};
constexpr std::array<std::string_view, 6> major_kinds{"sleep", "paralysis", "burn", "freeze", "poison", "bad_poison"};
constexpr std::array<std::string_view, 3> volatile_kinds{"confusion", "infatuation", "flinch"};
constexpr std::array<std::string_view, 6> weather_names{"none", "harsh_sunlight", "rain", "sandstorm", "hail", "snow"};
constexpr std::array<std::string_view, 5> terrain_names{"none", "electric_terrain", "psychic_terrain", "grassy_terrain", "misty_terrain"};
constexpr std::array<std::string_view, 3> categories{"physical", "special", "status"};
constexpr std::array<std::string_view, 2> repetitions{"declare-draw", "continue"};
constexpr std::array<std::string_view, 2> cycles{"declare-draw", "solve-absorption-probability"};

/// @param value 可空整数节点；@return 精确 int64 或 null，不接受 float/bool。
std::optional<std::int64_t> ReadOptionalInt(const Json& value) { return value.is_null() ? std::nullopt : std::optional{ReadInteger(value)}; }
/// @param value 可空字符串节点；@return 复制拥有的字符串/null。
std::optional<std::string> ReadOptionalText(const Json& value) { return value.is_null() ? std::nullopt : std::optional{value.get<std::string>()}; }
} // namespace
/// @param value 只读状态对象；@return variant 约束的完整主/临时状态，重复种类由 Core 校验。
CombatantStatus ReadStatusValue(const Json& value) {
  RequireFields(value, {"major", "volatile"});
  std::optional<MajorStatus> major;
  if (!value.at("major").is_null()) {
    const auto& status = value.at("major");
    const auto kind = ReadEnum<MajorStatusKind>(status.at("kind"), major_kinds);
    if (kind == MajorStatusKind::sleep) {
      RequireSchema(status, {"kind"}, {"turns_asleep"});
      major = SleepStatus{status.contains("turns_asleep") ? ReadInteger(status.at("turns_asleep")) : 0};
    } else if (kind == MajorStatusKind::bad_poison) {
      RequireSchema(status, {"kind"}, {"toxic_counter"});
      major = BadPoisonStatus{status.contains("toxic_counter") ? ReadInteger(status.at("toxic_counter")) : 1};
    } else {
      RequireFields(status, {"kind"});
      switch (kind) {
      case MajorStatusKind::paralysis: major = ParalysisStatus{}; break;
      case MajorStatusKind::burn: major = BurnStatus{}; break;
      case MajorStatusKind::freeze: major = FreezeStatus{}; break;
      case MajorStatusKind::poison: major = PoisonStatus{}; break;
      default: throw RequestError(PBI_UNSUPPORTED_V1, "unsupported major status");
      }
    }
  }
  const auto& values = value.at("volatile");
  if (!values.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "volatile statuses must be an array");
  if (values.size() > 16) throw RequestError(PBI_RESOURCE_LIMIT_V1, "volatile status budget exceeded");
  std::vector<VolatileStatus> temporary;
  for (const auto& status : values) {
    switch (ReadEnum<VolatileStatusKind>(status.at("kind"), volatile_kinds)) {
    case VolatileStatusKind::confusion:
      RequireSchema(status, {"kind"}, {"turns_remaining"});
      temporary.push_back(ConfusionStatus{status.contains("turns_remaining") ? ReadOptionalInt(status.at("turns_remaining")) : std::nullopt}); break;
    case VolatileStatusKind::infatuation:
      RequireSchema(status, {"kind"}, {"source_id"});
      temporary.push_back(InfatuationStatus{status.contains("source_id") ? ReadOptionalText(status.at("source_id")) : std::nullopt}); break;
    case VolatileStatusKind::flinch:
      RequireFields(status, {"kind"}); temporary.push_back(FlinchStatus{}); break;
    }
  }
  return CombatantStatus{std::move(major), std::move(temporary)};
}
/// @param value 只读已验证状态；@return 按种类排序的规范 JSON，不改变输入。
Json StatusJson(const CombatantStatus& value) {
  Json major = nullptr;
  if (value.Major()) {
    major = {{"kind", major_kinds.at(value.Major()->index())}};
    if (const auto* sleep = std::get_if<SleepStatus>(&*value.Major())) major["turns_asleep"] = sleep->turns_asleep;
    if (const auto* poison = std::get_if<BadPoisonStatus>(&*value.Major())) major["toxic_counter"] = poison->toxic_counter;
  }
  auto temporary = Json::array();
  for (const auto& status : value.Volatile()) {
    Json item{{"kind", volatile_kinds.at(status.index())}};
    if (const auto* confusion = std::get_if<ConfusionStatus>(&status)) item["turns_remaining"] = confusion->turns_remaining ? Json(*confusion->turns_remaining) : Json(nullptr);
    if (const auto* infatuation = std::get_if<InfatuationStatus>(&status)) item["source_id"] = infatuation->source_id ? Json(*infatuation->source_id) : Json(nullptr);
    temporary.push_back(std::move(item));
  }
  return {{"major", std::move(major)}, {"volatile", std::move(temporary)}};
}
namespace {
/// @param value 七项整数数组；@return 已验证等级。
StatStages ReadStages(const Json& value) {
  if (!value.is_array() || value.size() != 7) throw RequestError(PBI_INVALID_INPUT_V1, "stages must have seven entries");
  std::array<std::int32_t, 7> stages{};
  for (std::size_t index = 0; index < stages.size(); ++index) stages[index] = ReadInt32(value[index]);
  return StatStages{stages};
}
/// @param value 三屏障对象；@return 完整只读领域值。
DamageScreens ReadScreens(const Json& value) {
  RequireFields(value, {"reflect", "light_screen", "aurora_veil"});
  return {ReadBool(value.at("reflect")), ReadBool(value.at("light_screen")), ReadBool(value.at("aurora_veil"))};
}
/// @param value 只读屏障；@return 完整字段对象。
Json ScreensJson(const DamageScreens& value) { return {{"reflect", value.reflect}, {"light_screen", value.light_screen}, {"aurora_veil", value.aurora_veil}}; }
/// @param value 完整固定双方场地对象；@return 领域快照。
BattleFieldState ReadField(const Json& value) {
  RequireFields(value, {"weather", "terrain", "attacker_side", "defender_side"});
  return {ReadEnum<DamageWeather>(value.at("weather"), weather_names), ReadEnum<DamageTerrain>(value.at("terrain"), terrain_names),
          ReadScreens(value.at("attacker_side")), ReadScreens(value.at("defender_side"))};
}
/// @param value 只读场地；@return 完整字段对象。
Json FieldJson(const BattleFieldState& value) {
  return {{"weather", weather_names.at(static_cast<std::size_t>(value.weather))}, {"terrain", terrain_names.at(static_cast<std::size_t>(value.terrain))},
          {"attacker_side", ScreensJson(value.attacker_side)}, {"defender_side", ScreensJson(value.defender_side)}};
}
/// @param value 招式动态槽对象；@return 由 Core 验证后的快照。
MoveSlotState ReadSlot(const Json& value) {
  RequireSchema(value, {"move_id", "current_pp", "max_pp"}, {"disabled", "locked", "slot_id"});
  return MoveSlotState{{ReadInteger(value.at("move_id")), ReadInt32(value.at("current_pp")), ReadInt32(value.at("max_pp")),
      value.contains("disabled") ? ReadBool(value.at("disabled")) : false, value.contains("locked") ? ReadBool(value.at("locked")) : false,
      value.contains("slot_id") ? ReadInteger(value.at("slot_id")) : 0}};
}
/// @param value 完整招式配置对象；@return 已验证并规范 effect 标识的配置。
MoveSpec ReadMove(const Json& value) {
  RequireSchema(value, {"move_id", "name", "move", "max_pp"}, {"priority", "accuracy", "effect_identifier"});
  const auto& move = value.at("move"); RequireFields(move, {"type", "category", "power"});
  std::optional<std::int32_t> accuracy = 100;
  if (value.contains("accuracy")) accuracy = value.at("accuracy").is_null() ? std::nullopt : std::optional{ReadInt32(value.at("accuracy"))};
  return MoveSpec{{ReadInteger(value.at("move_id")), value.at("name").get<std::string>(),
      {static_cast<PokemonType>(ReadInt32(move.at("type"))), ReadEnum<DamageCategory>(move.at("category"), categories), ReadInt32(move.at("power"))},
      ReadInt32(value.at("max_pp")), value.contains("priority") ? ReadInt32(value.at("priority")) : 0, accuracy,
      value.contains("effect_identifier") ? ReadOptionalText(value.at("effect_identifier")) : std::nullopt}};
}
/// @param value 不变配置对象；@return 拥有一到四招的完整领域配置。
PokemonSpec ReadSpec(const Json& value) {
  RequireSchema(value, {"pokemon_id", "name", "pokemon", "moves"}, {"ability_context"});
  const auto& moves = value.at("moves");
  if (!moves.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "moves must be an array");
  if (moves.size() > 4) throw RequestError(PBI_RESOURCE_LIMIT_V1, "configured move budget exceeded");
  std::vector<MoveSpec> configured;
  for (const auto& move : moves) configured.push_back(ReadMove(move));
  std::optional<TransparentNeutralAbility> transparent_ability;
  if (value.contains("ability_context")) {
    if (!value.at("ability_context").is_string()) throw RequestError(PBI_INVALID_INPUT_V1, "ability context must be a string");
    if (value.at("ability_context") != "transparent_inference") throw RequestError(PBI_UNSUPPORTED_V1, "unsupported battle ability context");
    const auto& pokemon = value.at("pokemon");
    if (pokemon.contains("ability")) {
      if (!pokemon.at("ability").is_string()) throw RequestError(PBI_INVALID_INPUT_V1, "ability must be a string");
      transparent_ability = FindTransparentNeutralAbility(pokemon.at("ability").get<std::string>());
    }
  }
  // 只有显式context与白名单同时成立，才由Core声明原UNKNOWN解释；Go仍传真实原始能力。
  const auto pokemon = transparent_ability ? ReadPokemonWithInterpretedAbility(value.at("pokemon"), DamageAbility::none) : ReadPokemon(value.at("pokemon"));
  return PokemonSpec{{ReadInteger(value.at("pokemon_id")), value.at("name").get<std::string>(), pokemon, std::move(configured), transparent_ability}};
}
/// @param value 一方状态对象；@return 拥有并验证所有动态字段的节点。
BattlerState ReadBattler(const Json& value) {
  RequireSchema(value, {"spec", "current_hp", "move_slots"}, {"stages", "status", "last_move_id", "choice_lock_move_id", "item_consumed", "is_first_turn"});
  if (!value.at("move_slots").is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "move slots must be an array");
  if (value.at("move_slots").size() > 4) throw RequestError(PBI_RESOURCE_LIMIT_V1, "move slot budget exceeded");
  std::vector<MoveSlotState> slots;
  for (const auto& slot : value.at("move_slots")) slots.push_back(ReadSlot(slot));
  return BattlerState{{ReadSpec(value.at("spec")), ReadInt32(value.at("current_hp")), std::move(slots),
      value.contains("stages") ? ReadStages(value.at("stages")) : StatStages{}, value.contains("status") ? ReadStatusValue(value.at("status")) : CombatantStatus{},
      value.contains("last_move_id") ? ReadOptionalInt(value.at("last_move_id")) : std::nullopt,
      value.contains("choice_lock_move_id") ? ReadOptionalInt(value.at("choice_lock_move_id")) : std::nullopt,
      value.contains("item_consumed") ? ReadBool(value.at("item_consumed")) : false,
      value.contains("is_first_turn") ? ReadBool(value.at("is_first_turn")) : true}};
}
/// @param value 规则覆盖对象；@return 拥有全部默认/显式规则的已验证值。
InferenceRules ReadRules(const Json& value) {
  RequireSchema(value, {}, {"ruleset_id", "version_group_id", "level", "battle_format", "switching_policy", "allow_terastallization", "allow_mega_evolution", "allow_dynamax", "max_turns", "repetition_resolution", "cycle_resolution", "damage_policy", "move_execution_policy"});
  InferenceRulesData rules;
  if (value.contains("ruleset_id")) rules.ruleset_id = value.at("ruleset_id").get<std::string>();
  if (value.contains("version_group_id")) rules.version_group_id = ReadInteger(value.at("version_group_id"));
  if (value.contains("level")) rules.level = ReadInt32(value.at("level"));
  if (value.contains("battle_format")) rules.battle_format = ReadEnum<BattleFormat>(value.at("battle_format"), std::array<std::string_view, 1>{"one-on-one-singles"});
  if (value.contains("switching_policy")) rules.switching_policy = ReadEnum<SwitchingPolicy>(value.at("switching_policy"), std::array<std::string_view, 1>{"disabled"});
  if (value.contains("allow_terastallization")) rules.allow_terastallization = ReadBool(value.at("allow_terastallization"));
  if (value.contains("allow_mega_evolution")) rules.allow_mega_evolution = ReadBool(value.at("allow_mega_evolution"));
  if (value.contains("allow_dynamax")) rules.allow_dynamax = ReadBool(value.at("allow_dynamax"));
  if (value.contains("max_turns")) rules.max_turns = ReadOptionalInt(value.at("max_turns"));
  if (value.contains("repetition_resolution")) rules.repetition_resolution = ReadEnum<RepetitionResolution>(value.at("repetition_resolution"), repetitions);
  if (value.contains("cycle_resolution")) rules.cycle_resolution = ReadEnum<CycleResolution>(value.at("cycle_resolution"), cycles);
  if (value.contains("damage_policy")) rules.damage_policy = ReadPolicy(value.at("damage_policy"), std::move(rules.damage_policy));
  if (value.contains("move_execution_policy")) {
    const auto& policy = value.at("move_execution_policy");
    RequireSchema(policy, {}, {"accuracy_denominator", "consume_pp_on_miss", "consume_pp_when_action_blocked", "consume_pp_when_before_move_stops", "struggle_power", "struggle_recoil_fraction"});
    auto& execution = rules.move_execution_policy;
    if (policy.contains("accuracy_denominator")) execution.accuracy_denominator = ReadInt32(policy.at("accuracy_denominator"));
    if (policy.contains("consume_pp_on_miss")) execution.consume_pp_on_miss = ReadBool(policy.at("consume_pp_on_miss"));
    if (policy.contains("consume_pp_when_action_blocked")) execution.consume_pp_when_action_blocked = ReadBool(policy.at("consume_pp_when_action_blocked"));
    if (policy.contains("consume_pp_when_before_move_stops")) execution.consume_pp_when_before_move_stops = ReadBool(policy.at("consume_pp_when_before_move_stops"));
    if (policy.contains("struggle_power")) execution.struggle_power = ReadInt32(policy.at("struggle_power"));
    if (policy.contains("struggle_recoil_fraction")) execution.struggle_recoil_fraction = ReadFraction(policy.at("struggle_recoil_fraction"));
  }
  return InferenceRules{std::move(rules)};
}
/// @param value 完整规则；@return 全部规则字段的稳定快照，概率仍为字符串分数。
Json RulesJson(const InferenceRules& value) {
  const auto& rules = value.View(); const auto& execution = rules.move_execution_policy;
  return {{"ruleset_id", rules.ruleset_id}, {"version_group_id", rules.version_group_id}, {"level", rules.level},
      {"battle_format", "one-on-one-singles"}, {"switching_policy", "disabled"}, {"allow_terastallization", rules.allow_terastallization},
      {"allow_mega_evolution", rules.allow_mega_evolution}, {"allow_dynamax", rules.allow_dynamax},
      {"max_turns", rules.max_turns ? Json(*rules.max_turns) : Json(nullptr)},
      {"repetition_resolution", repetitions.at(static_cast<std::size_t>(rules.repetition_resolution))}, {"cycle_resolution", cycles.at(static_cast<std::size_t>(rules.cycle_resolution))},
      {"damage_policy", PolicyJson(rules.damage_policy)}, {"move_execution_policy", {{"accuracy_denominator", execution.accuracy_denominator},
          {"consume_pp_on_miss", execution.consume_pp_on_miss}, {"consume_pp_when_action_blocked", execution.consume_pp_when_action_blocked},
          {"consume_pp_when_before_move_stops", execution.consume_pp_when_before_move_stops}, {"struggle_power", execution.struggle_power},
          {"struggle_recoil_fraction", FractionJson(execution.struggle_recoil_fraction)}}}};
}
/// @param value 一方节点；@return 完整输入可重放快照，保留展示名但它不进入 Core Key。
Json BattlerJson(const BattlerState& value) {
  const auto& state = value.View(); const auto& spec = state.spec.View();
  auto moves = Json::array();
  for (const auto& configured : spec.moves) moves.push_back(MoveSpecJson(configured));
  auto slots = Json::array();
  for (const auto& configured : state.move_slots) {
    const auto& slot = configured.View();
    slots.push_back({{"move_id", slot.move_id}, {"current_pp", slot.current_pp}, {"max_pp", slot.max_pp}, {"disabled", slot.disabled}, {"locked", slot.locked}, {"slot_id", slot.slot_id}});
  }
  auto pokemon = PokemonJson(spec.pokemon);
  Json specification{{"pokemon_id", spec.pokemon_id}, {"name", spec.name}, {"pokemon", std::move(pokemon)}, {"moves", std::move(moves)}};
  if (spec.transparent_ability) {
    specification["pokemon"]["ability"] = TransparentNeutralAbilityIdentifier(*spec.transparent_ability);
    specification["ability_context"] = "transparent_inference";
  }
  return {{"spec", std::move(specification)},
      {"current_hp", state.current_hp}, {"move_slots", std::move(slots)}, {"stages", state.stages.Values()}, {"status", StatusJson(state.status)},
      {"last_move_id", state.last_move_id ? Json(*state.last_move_id) : Json(nullptr)}, {"choice_lock_move_id", state.choice_lock_move_id ? Json(*state.choice_lock_move_id) : Json(nullptr)},
      {"item_consumed", state.item_consumed}, {"is_first_turn", state.is_first_turn}};
}
/// @param value 完整更新指令；@return 有限 variant，不保留动态 JSON 给领域执行。
StateUpdate ReadUpdate(const Json& value) {
  const auto kind = value.at("kind").get<std::string>();
  if (kind == "next_turn") { RequireFields(value, {"kind"}); return NextTurnUpdate{}; }
  if (kind == "phase") { RequireFields(value, {"kind", "value"}); return PhaseUpdate{ReadEnum<BattlePhase>(value.at("value"), phases)}; }
  if (kind == "field") { RequireFields(value, {"kind", "value"}); return FieldUpdate{ReadField(value.at("value"))}; }
  if (kind == "rules") { RequireFields(value, {"kind", "value"}); return RulesUpdate{ReadRules(value.at("value"))}; }
  constexpr std::array<std::string_view, 10> battler_kinds{"hp", "pp", "disabled", "choice_lock", "stages", "status", "last_move", "item_consumed", "first_turn_complete", "slot"};
  if (std::find(battler_kinds.begin(), battler_kinds.end(), kind) == battler_kinds.end()) throw RequestError(PBI_UNSUPPORTED_V1, "unsupported state update kind");
  const auto side = ReadEnum<BattleSide>(value.at("side"), sides);
  if (kind == "first_turn_complete") { RequireFields(value, {"kind", "side"}); return BattlerUpdate{side, FirstTurnUpdate{}}; }
  if (kind == "choice_lock" || kind == "last_move") {
    RequireFields(value, {"kind", "side", "move_id"});
    const auto move = ReadOptionalInt(value.at("move_id"));
    return kind == "choice_lock" ? StateUpdate{BattlerUpdate{side, ChoiceUpdate{move}}} : StateUpdate{BattlerUpdate{side, LastMoveUpdate{move}}};
  }
  if (kind == "pp" || kind == "disabled") {
    RequireFields(value, {"kind", "side", "move_id", "value"});
    const auto move = ReadInteger(value.at("move_id"));
    return kind == "pp" ? StateUpdate{BattlerUpdate{side, PpUpdate{move, ReadInt32(value.at("value"))}}} : StateUpdate{BattlerUpdate{side, DisabledUpdate{move, ReadBool(value.at("value"))}}};
  }
  RequireFields(value, {"kind", "side", "value"});
  if (kind == "hp") return BattlerUpdate{side, HpUpdate{ReadInt32(value.at("value"))}};
  if (kind == "stages") return BattlerUpdate{side, StagesUpdate{ReadStages(value.at("value"))}};
  if (kind == "status") return BattlerUpdate{side, StatusUpdate{ReadStatusValue(value.at("value"))}};
  if (kind == "item_consumed") return BattlerUpdate{side, ItemUpdate{ReadBool(value.at("value"))}};
  if (kind == "slot") return BattlerUpdate{side, SlotUpdate{ReadSlot(value.at("value"))}};
  throw RequestError(PBI_UNSUPPORTED_V1, "unsupported state update kind");
}
/// @param state 只读一方祖先；@param update 只读类型化指令；@return 对应 Core 更新的新状态。
BattlerState ApplyBattlerUpdate(const BattlerState& state, const BattlerChange& update) {
  return std::visit([&state](const auto& change) -> BattlerState {
    using T = std::decay_t<decltype(change)>;
    if constexpr (std::is_same_v<T, HpUpdate>) return state.WithCurrentHp(change.value);
    else if constexpr (std::is_same_v<T, PpUpdate>) return state.WithMoveSlot(state.MoveSlot(change.move_id).WithCurrentPp(change.value));
    else if constexpr (std::is_same_v<T, DisabledUpdate>) return state.WithMoveSlot(state.MoveSlot(change.move_id).WithDisabled(change.value));
    else if constexpr (std::is_same_v<T, ChoiceUpdate>) return state.WithChoiceLock(change.move_id);
    else if constexpr (std::is_same_v<T, StagesUpdate>) return state.WithStages(change.value);
    else if constexpr (std::is_same_v<T, StatusUpdate>) return state.WithStatus(change.value);
    else if constexpr (std::is_same_v<T, LastMoveUpdate>) return state.WithLastMove(change.move_id);
    else if constexpr (std::is_same_v<T, ItemUpdate>) return state.WithItemConsumed(change.value);
    else if constexpr (std::is_same_v<T, SlotUpdate>) return state.WithMoveSlot(change.value);
    else return state.MarkFirstTurnComplete();
  }, update);
}
/// @param state 只读完整祖先；@param update 只读类型化指令；@return 新节点，副作用仅在返回值。
BattleState ApplyUpdate(const BattleState& state, const StateUpdate& update) {
  return std::visit([&state](const auto& change) -> BattleState {
    using T = std::decay_t<decltype(change)>;
    if constexpr (std::is_same_v<T, BattlerUpdate>) return state.WithBattler(change.side, ApplyBattlerUpdate(state.Battler(change.side), change.change));
    else if constexpr (std::is_same_v<T, NextTurnUpdate>) return state.NextTurn();
    else if constexpr (std::is_same_v<T, PhaseUpdate>) return state.WithPhase(change.value);
    else if constexpr (std::is_same_v<T, FieldUpdate>) return state.WithField(change.value);
    else { auto copy = state.View(); copy.rules = change.value; return BattleState{std::move(copy)}; }
  }, update);
}
} // namespace

MoveSpec ReadMoveSpecValue(const Json& value) { return ReadMove(value); }

Json MoveSpecJson(const MoveSpec& value) {
  const auto& move = value.View();
  return {{"move_id", move.move_id}, {"name", move.name},
      {"move", {{"type", static_cast<int>(move.move.type)}, {"category", categories.at(static_cast<std::size_t>(move.move.category))}, {"power", move.move.power}}},
      {"max_pp", move.max_pp}, {"priority", move.priority}, {"accuracy", move.accuracy ? Json(*move.accuracy) : Json(nullptr)},
      {"effect_identifier", move.effect_identifier ? Json(*move.effect_identifier) : Json(nullptr)}};
}

BattleState ReadBattleStateValue(const Json& value) {
  RequireSchema(value, {"attacker", "defender", "rules"}, {"turn_number", "field", "phase"});
  return BattleState{{ReadBattler(value.at("attacker")), ReadBattler(value.at("defender")), ReadRules(value.at("rules")),
      value.contains("turn_number") ? ReadInteger(value.at("turn_number")) : 1,
      value.contains("field") ? ReadField(value.at("field")) : BattleFieldState{},
      value.contains("phase") ? ReadEnum<BattlePhase>(value.at("phase"), phases) : BattlePhase::action_selection}};
}

Json StateJson(const BattleState& state) {
  const auto& data = state.View();
  return {{"attacker", BattlerJson(data.attacker)}, {"defender", BattlerJson(data.defender)},
      {"rules", RulesJson(data.rules)}, {"turn_number", data.turn_number}, {"field", FieldJson(data.field)},
      {"phase", phases.at(static_cast<std::size_t>(data.phase))}};
}

std::pair<BattleStateRequest, std::size_t> ReadBattleStateRequest(const Json& value, std::size_t remaining_rolls) {
  RequireSchema(value, {"kind", "state", "updates"}, {"compare_to", "damage_query"});
  const auto& updates = value.at("updates");
  if (!updates.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "state updates must be an array");
  if (updates.size() > 256) throw RequestError(PBI_RESOURCE_LIMIT_V1, "state update budget exceeded");
  auto state = ReadBattleStateValue(value.at("state"));
  std::size_t consumed = state.View().rules.View().damage_policy.random_damage_multipliers.size();
  std::vector<StateUpdate> changes;
  for (const auto& update : updates) {
    auto change = ReadUpdate(update);
    if (const auto* rules = std::get_if<RulesUpdate>(&change)) consumed += rules->value.View().damage_policy.random_damage_multipliers.size();
    changes.push_back(std::move(change));
  }
  std::optional<BattleState> reference;
  if (value.contains("compare_to") && !value.at("compare_to").is_null()) { reference = ReadBattleStateValue(value.at("compare_to")); consumed += reference->View().rules.View().damage_policy.random_damage_multipliers.size(); }
  std::optional<StateDamageQuery> damage;
  if (value.contains("damage_query") && !value.at("damage_query").is_null()) {
    const auto& query = value.at("damage_query");
    RequireSchema(query, {"side", "move_id", "generation_id", "type_chart"}, {"policy"});
    const auto generation = ReadInt32(query.at("generation_id"));
    auto policy = DamagePolicyForGeneration(generation);
    if (query.contains("policy") && !query.at("policy").is_null()) policy = ReadPolicy(query.at("policy"), std::move(policy));
    consumed += policy.random_damage_multipliers.size();
    damage = StateDamageQuery{ReadEnum<BattleSide>(query.at("side"), sides), ReadInteger(query.at("move_id")), generation, std::move(policy), ReadTypeChart(query.at("type_chart"))};
  }
  if (consumed > remaining_rolls) throw RequestError(PBI_RESOURCE_LIMIT_V1, "state policy roll budget exceeded");
  return {BattleStateRequest{std::move(state), std::move(changes), std::move(reference), std::move(damage)}, consumed};
}
StatusModifiersRequest ReadStatusModifiersRequest(const Json& value) {
  RequireSchema(value, {"kind", "status", "speed", "generation_id", "category", "base_multiplier", "burn_multiplier"}, {"paralysis_multiplier"});
  auto paralysis = ParalysisSpeedForGeneration(ReadInt32(value.at("generation_id")));
  if (value.contains("paralysis_multiplier") && !value.at("paralysis_multiplier").is_null()) paralysis = ReadFraction(value.at("paralysis_multiplier"));
  return {ReadStatusValue(value.at("status")), ReadInteger(value.at("speed")), std::move(paralysis), ReadEnum<DamageCategory>(value.at("category"), categories),
          ReadFraction(value.at("base_multiplier")), ReadFraction(value.at("burn_multiplier"))};
}
Json EvaluateBattleState(const BattleStateRequest& request) {
  auto state = request.state;
  for (const auto& update : request.updates) state = ApplyUpdate(state, update);
  const auto& data = state.View();
  Json damage = nullptr;
  if (request.damage) {
    const auto& query = *request.damage;
    damage = DamageJson(CalculateDamage(state.DamageInputFor(query.side, query.move_id, query.policy), query.knowledge), query.generation);
  }
  return {{"kind", "battle_state"}, {"state", StateJson(state)},
      {"same_key_as_input", state.Key() == request.state.Key()}, {"same_key_as_reference", request.reference ? Json(state.Key() == request.reference->Key()) : Json(nullptr)},
      {"attacker_speed", EffectiveActionSpeed(data.attacker)}, {"defender_speed", EffectiveActionSpeed(data.defender)}, {"damage", std::move(damage)}};
}
Json EvaluateStatusModifiers(const StatusModifiersRequest& request) {
  return {{"kind", "status_modifiers"}, {"status", StatusJson(request.status)},
      {"speed", ApplyParalysisSpeed(request.speed, request.status, request.paralysis)},
      {"burn_multiplier", FractionJson(BurnPhysicalMultiplier(request.status, request.category, request.burn_multiplier))},
      {"adjusted_multiplier", FractionJson(ApplyBurnDamageMultiplier(request.base_multiplier, request.status, request.category, request.burn_multiplier))},
      {"after_switch_out", StatusJson(ClearStatusOnSwitchOut(request.status))}};
}
} // namespace pbi::contract
