#include "configuration_contract.hpp"
#include "state_contract.hpp"

#include <limits>
#include <set>
#include <tuple>

namespace pbi::contract {
namespace {
constexpr std::array<std::string_view, 3> support_names{"supported", "partial", "unsupported"};
constexpr std::array<std::string_view, 4> effect_names{"supported", "partial", "unsupported", "no_effect"};
constexpr std::array<std::string_view, 3> source_names{"move", "ability", "item"};
constexpr std::array<std::string_view, 6> stat_names{"hp", "attack", "defense", "special_attack", "special_defense", "speed"};
constexpr std::array<std::string_view, 2> assumptions{"uniform_raw_configuration", "uniform_equivalence_class"};
constexpr std::array<std::string_view, 2> factories{"standard", "transparent_inference"};
constexpr std::array<std::string_view, 4> admission_names{"supported", "no_effect", "partial", "unsupported"};
constexpr std::array<std::string_view, 2> repository_modes{"raw", "factory_reconciled"};
constexpr std::array<std::string_view, 2> sides{"attacker", "defender"};
constexpr std::array<std::string_view, 2> policies{"uniform-random", "first-legal-action"};
constexpr std::array<std::string_view, 3> dimension_modes{"fixed", "candidate_pool", "disabled"};

/// @param stop 当前只读令牌；取消时终止整个批次，不留下半套成员或权重。
void CheckStop(CancellationToken stop) {
  if (stop.Requested()) throw RequestError(PBI_CANCELLED_V1, "calculation cancelled");
}
/// @param value 正式数组；类型错误拒绝，不接受对象迭代的隐式转换。
void RequireArray(const Json& value) {
  if (!value.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "configuration field must be an array");
}
/// @param value 明确字符串；@return 拥有文本，空文本由对应纯域校验。
std::string Text(const Json& value) {
  if (!value.is_string()) throw RequestError(PBI_INVALID_INPUT_V1, "configuration field must be a string");
  return value.get<std::string>();
}
/// @param value 明确null或字符串；@return 保留null和显式文本区别。
std::optional<std::string> OptionalText(const Json& value) {
  return value.is_null() ? std::nullopt : std::optional{Text(value)};
}
/// @param value 正整数预算；@return size_t拥有值，不将原本可配置预算静默裁低。
std::size_t Positive(const Json& value) {
  const auto number = ReadInteger(value);
  if (number <= 0) throw RequestError(PBI_INVALID_INPUT_V1, "configuration limits must be positive");
  if (static_cast<std::uint64_t>(number) > std::numeric_limits<std::size_t>::max())
    throw RequestError(PBI_RESOURCE_LIMIT_V1, "configuration limit exceeds platform range");
  return static_cast<std::size_t>(number);
}
/// @param value 非负索引或页长度；@return 平台可表示的完整数值，保留空页语义。
std::size_t Index(const Json& value) {
  const auto number = ReadInteger(value);
  if (number < 0) throw RequestError(PBI_INVALID_INPUT_V1, "job page index must not be negative");
  if (static_cast<std::uint64_t>(number) > std::numeric_limits<std::size_t>::max())
    throw RequestError(PBI_RESOURCE_LIMIT_V1, "job page index exceeds platform range");
  return static_cast<std::size_t>(number);
}
/// @param value 对象；@param name 可省略正整数字段；@param fallback 原Core默认值。
/// @return 显式预算或原默认，不把null解释为无限。
std::size_t Budget(const Json& value, std::string_view name, std::size_t fallback) {
  return value.contains(name) ? Positive(value.at(name)) : fallback;
}
/// @param value 完整五轴binary64数组；@return 保留旧单增无降、负数及有符号零的有限倍率。
ConfigurationNature Nature(const Json& value) {
  RequireArray(value);
  if (value.size() != 5) throw RequestError(PBI_INVALID_INPUT_V1, "configuration nature requires five multipliers");
  ConfigurationNature result;
  for (std::size_t index = 0; index < result.multipliers.size(); ++index) {
    if (!value[index].is_number()) throw RequestError(PBI_INVALID_INPUT_V1, "nature multiplier must be numeric");
    const double number = value[index].get<double>();
    if (!std::isfinite(number)) throw RequestError(PBI_INVALID_INPUT_V1, "nature multiplier must be finite");
    result.multipliers[index] = number;
  }
  return result;
}
/// @param value 完整IV/EV/性格快照；@return 不执行能力计算的拥有值。
ConfigurationStatProfile Profile(const Json& value) {
  RequireFields(value, {"ivs", "evs", "nature"});
  return {ReadBattleStats(value.at("ivs")), ReadBattleStats(value.at("evs")), Nature(value.at("nature"))};
}
/// @param value 原始能力枚举命令；@param stop 同源取消；@return 完整typed预设或受控输入。
ConfigurationStatInput ReadStatsInput(const Json& value, CancellationToken stop) {
  RequireSchema(value, {"base", "level", "enumeration"}, {"max_raw_profiles"});
  ConfigurationStatInput result;
  result.base = ReadBattleStats(value.at("base"));
  result.level = ReadInt32(value.at("level"));
  result.max_raw_profiles = Budget(value, "max_raw_profiles", result.max_raw_profiles);
  const auto& command = value.at("enumeration");
  if (!command.is_object() || !command.contains("mode")) throw RequestError(PBI_INVALID_INPUT_V1, "stat enumeration requires a mode");
  const auto mode = Text(command.at("mode"));
  if (mode == "preset") {
    RequireFields(command, {"mode", "presets"});
    RequireArray(command.at("presets"));
    PresetStatEnumeration enumeration;
    for (const auto& preset : command.at("presets")) {
      CheckStop(stop);
      RequireFields(preset, {"profile", "label"});
      enumeration.presets.push_back({Profile(preset.at("profile")), Text(preset.at("label"))});
    }
    result.enumeration = std::move(enumeration);
  } else if (mode == "controlled") {
    RequireFields(command, {"mode", "fields", "ev_values", "natures"});
    ControlledStatEnumeration enumeration;
    RequireArray(command.at("fields")); RequireArray(command.at("ev_values")); RequireArray(command.at("natures"));
    for (const auto& field : command.at("fields")) {
      CheckStop(stop); enumeration.fields.push_back(ReadEnum<ConfigurationStatField>(field, stat_names));
    }
    for (const auto& number : command.at("ev_values")) {
      CheckStop(stop); enumeration.ev_values.push_back(ReadInt32(number));
    }
    for (const auto& nature : command.at("natures")) {
      CheckStop(stop); enumeration.natures.push_back(Nature(nature));
    }
    result.enumeration = std::move(enumeration);
  } else throw RequestError(PBI_UNSUPPORTED_V1, "unsupported stat enumeration mode");
  return result;
}
/// @param value 完整合法招式候选命令；@param stop 同源取消；@return 只读取不组合的typed输入。
ConfigurationMoveInput ReadMovesInput(const Json& value, CancellationToken stop) {
  RequireSchema(value, {"candidates"}, {"requested_ids", "slot_counts", "max_raw_combinations"});
  ConfigurationMoveInput result;
  result.max_raw_combinations = Budget(value, "max_raw_combinations", result.max_raw_combinations);
  RequireArray(value.at("candidates"));
  for (const auto& candidate : value.at("candidates")) {
    CheckStop(stop);
    RequireFields(candidate, {"move_id", "identifier", "move", "effect_identifier", "support", "reason"});
    std::optional<MoveSpec> move;
    if (!candidate.at("move").is_null()) move.emplace(ReadMoveSpecValue(candidate.at("move")));
    result.candidates.push_back({ReadInteger(candidate.at("move_id")), Text(candidate.at("identifier")), std::move(move),
        OptionalText(candidate.at("effect_identifier")), ReadEnum<ConfigurationSupport>(candidate.at("support"), support_names), Text(candidate.at("reason"))});
  }
  if (value.contains("requested_ids")) {
    RequireArray(value.at("requested_ids"));
    for (const auto& identifier : value.at("requested_ids")) { CheckStop(stop); result.requested_ids.push_back(ReadInteger(identifier)); }
  }
  if (value.contains("slot_counts")) {
    RequireArray(value.at("slot_counts"));
    for (const auto& number : value.at("slot_counts")) { CheckStop(stop); result.slot_counts.push_back(Positive(number)); }
  }
  return result;
}
/// @param value 完整标准四维单侧命令；@param stop 同源取消；@return 不进行维度过滤的拥有快照。
ConfigurationPokemonInput ReadSide(const Json& value, CancellationToken stop) {
  RequireSchema(value, {"pokemon_id", "name", "types", "moves", "stats", "abilities"},
      {"ruleset_id", "version_group_id", "can_evolve", "requested_abilities", "items", "max_raw_configurations", "factory", "repository_mode"});
  ConfigurationPokemonInput result;
  result.pokemon_id = ReadInteger(value.at("pokemon_id")); result.name = Text(value.at("name"));
  if (value.contains("ruleset_id")) result.ruleset_id = Text(value.at("ruleset_id"));
  if (value.contains("version_group_id")) result.version_group_id = ReadInteger(value.at("version_group_id"));
  if (value.contains("can_evolve")) result.can_evolve = ReadBool(value.at("can_evolve"));
  if (value.contains("factory")) result.factory = ReadEnum<ConfigurationEffectFactory>(value.at("factory"), factories);
  if (value.contains("repository_mode")) result.repository_mode = ReadEnum<ConfigurationRepositoryMode>(value.at("repository_mode"), repository_modes);
  RequireArray(value.at("types"));
  for (const auto& type : value.at("types")) { CheckStop(stop); result.types.push_back(static_cast<PokemonType>(ReadInt32(type))); }
  result.moves = ReadMovesInput(value.at("moves"), stop); result.stats = ReadStatsInput(value.at("stats"), stop);
  RequireArray(value.at("abilities"));
  for (const auto& ability : value.at("abilities")) {
    CheckStop(stop); RequireFields(ability, {"identifier", "support", "reason"});
    result.abilities.push_back({Text(ability.at("identifier")), ReadEnum<ConfigurationSupport>(ability.at("support"), support_names), Text(ability.at("reason"))});
  }
  if (value.contains("requested_abilities")) {
    RequireArray(value.at("requested_abilities"));
    for (const auto& ability : value.at("requested_abilities")) { CheckStop(stop); result.requested_abilities.push_back(Text(ability)); }
  }
  if (value.contains("items")) {
    RequireArray(value.at("items")); result.items.clear();
    for (const auto& item : value.at("items")) { CheckStop(stop); result.items.push_back(OptionalText(item)); }
  }
  result.max_raw_configurations = Budget(value, "max_raw_configurations", result.max_raw_configurations);
  return result;
}
/// @param value 原固定六轴身份；@return 完整原始ASCII标识，不规范化canonical事实。
JobFixedPokemon ReadFixed(const Json& value) {
  RequireFields(value, {"pokemon_id", "form_id", "level", "stat_profile_id", "ability_identifier", "item_identifier"});
  return {ReadInteger(value.at("pokemon_id")), value.at("form_id").is_null() ? std::nullopt : std::optional{ReadInteger(value.at("form_id"))},
      ReadInt32(value.at("level")), Text(value.at("stat_profile_id")), Text(value.at("ability_identifier")), OptionalText(value.at("item_identifier"))};
}
/// @param value 原固定身份与唯一招式池；@param stop 批次取消；@return 未过滤的拥有值。
JobMovePoolSelection ReadSelection(const Json& value, CancellationToken stop) {
  RequireFields(value, {"fixed", "candidate_move_ids"}); RequireArray(value.at("candidate_move_ids"));
  JobMovePoolSelection result{ReadFixed(value.at("fixed")), {}};
  for (const auto& identifier : value.at("candidate_move_ids")) { CheckStop(stop); result.candidate_move_ids.push_back(ReadInteger(identifier)); }
  return result;
}
/// @param value 原job-v1全部维度；@return 每轴有限模式，不忽略新增自由度。
JobDimensionModes ReadDimensions(const Json& value) {
  RequireFields(value, {"pokemon", "form", "level", "stats", "ability", "item", "moves", "special_mechanics"});
  return {ReadEnum<JobDimensionMode>(value.at("pokemon"), dimension_modes), ReadEnum<JobDimensionMode>(value.at("form"), dimension_modes),
      ReadEnum<JobDimensionMode>(value.at("level"), dimension_modes), ReadEnum<JobDimensionMode>(value.at("stats"), dimension_modes),
      ReadEnum<JobDimensionMode>(value.at("ability"), dimension_modes), ReadEnum<JobDimensionMode>(value.at("item"), dimension_modes),
      ReadEnum<JobDimensionMode>(value.at("moves"), dimension_modes), ReadEnum<JobDimensionMode>(value.at("special_mechanics"), dimension_modes)};
}
/// @param value 原完整命令；@param stop 批次取消；@return 由纯Core验证并排序的具体case池。
JobMovePool ReadJob(const Json& value, CancellationToken stop) {
  RequireFields(value, {"contract_version", "ruleset_id", "version_group_id", "calculation_revision", "attacker", "defender", "dimensions",
      "attacker_policy", "defender_policy", "weight_assumption", "mechanism_admission"});
  if (Text(value.at("weight_assumption")) != "uniform_configuration_pair" || Text(value.at("mechanism_admission")) != "supported_only")
    throw RequestError(PBI_UNSUPPORTED_V1, "unsupported job weighting or mechanism admission policy");
  // canonical规划可表达其他轴，但本ABI不能借Champion工厂替未知规则集裁定strict可执行性。
  if (Text(value.at("ruleset_id")) != "pokemon-champion")
    throw RequestError(PBI_UNSUPPORTED_V1, "unsupported configuration ruleset");
  return JobMovePool{{Text(value.at("ruleset_id")), ReadInteger(value.at("version_group_id")), Text(value.at("calculation_revision")),
      ReadSelection(value.at("attacker"), stop), ReadSelection(value.at("defender"), stop), ReadDimensions(value.at("dimensions")),
      ReadEnum<ActionPolicy>(value.at("attacker_policy"), policies), ReadEnum<ActionPolicy>(value.at("defender_policy"), policies), Text(value.at("contract_version"))}};
}
/// @param pool 已验证原命令；@param facts 完整来源事实；@param stop 批次取消。
/// 检查恰好整池覆盖及关联，不声称能验证外层数据库事实的真伪。
void ValidateJobFacts(const JobMovePool& pool, const std::vector<JobAdmissionFact>& facts, CancellationToken stop) {
  std::set<std::tuple<BattleSide, ConfigurationEffectSource, std::int64_t>> seen;
  for (const auto& fact : facts) {
    CheckStop(stop); const auto& value = fact.admission;
    const auto& selection = fact.side == BattleSide::attacker ? pool.View().attacker : pool.View().defender;
    if (!seen.emplace(fact.side, value.source, fact.move_id.value_or(0)).second)
      throw RequestError(PBI_INVALID_INPUT_V1, "duplicate job admission fact");
    const auto effect = NormalizeConfigurationEffectIdentifier(value.effect_identifier);
    if (value.source == ConfigurationEffectSource::move) {
      if (!fact.move_id || !fact.move || fact.move->View().move_id != *fact.move_id ||
          std::ranges::find(selection.candidate_move_ids, *fact.move_id) == selection.candidate_move_ids.end())
        throw RequestError(PBI_INVALID_INPUT_V1, "job admission move does not match the command");
      const auto spec_effect = fact.move->View().effect_identifier;
      if (spec_effect && spec_effect != effect) throw RequestError(PBI_INVALID_INPUT_V1, "job admission move effect mismatch");
      if (value.allow_no_effect && (effect || fact.move->View().move.category == DamageCategory::status))
        throw RequestError(PBI_INVALID_INPUT_V1, "job move cannot use the no-effect admission path");
    } else {
      if (fact.move_id || fact.move) throw RequestError(PBI_INVALID_INPUT_V1, "non-move admission fact contains a move");
      // 原任务用精确字符串"none"选择无道具，canonical仍保留该字符串；仅效果关联视为null。
      const bool no_item = value.source == ConfigurationEffectSource::item &&
          (!selection.fixed.item_identifier || *selection.fixed.item_identifier == "none");
      const auto expected = value.source == ConfigurationEffectSource::ability
          ? NormalizeConfigurationEffectIdentifier(selection.fixed.ability_identifier)
          : no_item ? std::nullopt : NormalizeConfigurationEffectIdentifier(selection.fixed.item_identifier);
      if (effect != expected || NormalizeConfigurationEffectIdentifier(value.mechanism_identifier) != expected.value_or("none"))
        throw RequestError(PBI_INVALID_INPUT_V1, "job admission effect does not match the fixed command");
      if (value.allow_no_effect && (value.source == ConfigurationEffectSource::ability || !no_item || effect))
        throw RequestError(PBI_INVALID_INPUT_V1, "job effect cannot use the no-effect admission path");
    }
  }
  if (seen.size() != pool.View().attacker.candidate_move_ids.size() + pool.View().defender.candidate_move_ids.size() + 4)
    throw RequestError(PBI_INVALID_INPUT_V1, "job admission facts must cover the complete pool");
}
/// @param value 正式操作；@return 唯一input节点，所有外层未知字段明确拒绝。
const Json& Input(const Json& value) { RequireFields(value, {"kind", "input"}); return value.at("input"); }
/// @param value 完整Core效果描述；@return 保留部分支持和全部缺失能力，不折叠为布尔值。
Json Effect(const ConfigurationEffectCoverage& value) {
  return {{"identifier", value.identifier}, {"status", effect_names.at(static_cast<std::size_t>(value.status))},
      {"reason", value.reason}, {"missing_capabilities", value.missing_capabilities}};
}
/// @param value 原始能力代表；@return 完整IV/EV/五轴性格，可再次作为preset输入。
Json ProfileJson(const ConfigurationStatProfile& value) {
  return {{"ivs", BattleStatsJson(value.ivs)}, {"evs", BattleStatsJson(value.evs)}, {"nature", value.nature.multipliers}};
}
/// @param value 已归并能力类；@return 第一代表、实际能力和精确原始成员数。
Json StatClass(const ConfigurationStatClass& value) {
  return {{"representative", ProfileJson(value.representative)}, {"actual", BattleStatsJson(value.actual)},
      {"label", value.label}, {"member_count", value.member_count.str()}};
}
/// @param value 已归并招式类；@return 全部ID/属性/效果和独立provider效果，不只返回展示名。
Json MoveClass(const ConfigurationMoveClass& value) {
  auto moves = Json::array();
  for (const auto& move : value.moves) moves.push_back({{"spec", MoveSpecJson(move.move)},
      {"effect_identifier", move.effect_identifier ? Json(*move.effect_identifier) : Json(nullptr)}, {"key", ConfigurationMoveOrderKey(move)}});
  return {{"moves", std::move(moves)}, {"member_count", value.member_count.str()}};
}
/// @param value Core纳入/排除事实；@return 全部状态、命令排除原因与可空工厂状态。
Json Coverage(const ConfigurationCandidateCoverage& value) {
  return {{"identifier", value.identifier}, {"support", support_names.at(static_cast<std::size_t>(value.support))},
      {"included", value.included}, {"reason", value.reason},
      {"factory_status", value.factory_status ? Json(effect_names.at(static_cast<std::size_t>(*value.factory_status))) : Json(nullptr)}};
}
/// 配置结果逐条投影预算，避免大量小候选组成未受控JSON树。
class Projection {
public:
  /// @param stop 只读批次令牌，整个投影期间保持可取消。
  explicit Projection(CancellationToken stop) : stop_(std::move(stop)) {}
  /// @param array 该结果拥有的数组；@param value 完整一条记录，超限不保留部分成功。
  void Append(Json& array, Json value) {
    CheckStop(stop_); const auto size = value.dump().size();
    if (size > remaining_) throw RequestError(PBI_RESOURCE_LIMIT_V1, "result byte budget exceeded");
    remaining_ -= size; array.push_back(std::move(value));
  }
private:
  CancellationToken stop_;
  std::size_t remaining_ = PBI_V1_MAX_RESULT_BYTES;
};
/// @param input 原合法候选；@param projection 本结果预算；@param factory 显式composition，默认保持旧标准工厂。
/// @return 全部repository原理由与独立factory事实，不把strict决定当provider准入。
Json MoveDescriptions(const ConfigurationMoveInput& input, Projection& projection,
                      ConfigurationEffectFactory factory = ConfigurationEffectFactory::standard) {
  auto result = Json::array();
  for (const auto& value : input.candidates) {
    auto identifier = value.effect_identifier;
    if (!NormalizeConfigurationEffectIdentifier(identifier) && value.move) identifier = value.move->View().effect_identifier;
    projection.Append(result, {{"source", "move"}, {"identifier", value.identifier}, {"move_id", value.move_id},
        {"repository", {{"support", support_names.at(static_cast<std::size_t>(value.support))}, {"reason", value.reason}}},
        {"factory", Effect(DescribeConfigurationEffect(ConfigurationEffectSource::move, identifier, factory))}});
  }
  return result;
}
/// @param value 完整单侧结果；@param input 原候选快照；@param projection 本结果预算。
/// @return 可执行配置第一代表、全部coverage和原repository/factory事实。
Json Side(const ConfigurationPokemonSpace& value, const ConfigurationPokemonInput& input, Projection& projection) {
  auto classes = Json::array(), coverage = Json::array();
  for (const auto& item : value.classes) projection.Append(classes, {{"key", item.order_key}, {"member_count", item.member_count.str()},
      {"moves", MoveClass(item.moves)}, {"stats", StatClass(item.stats)}, {"ability", item.ability}, {"item", item.item}});
  for (const auto& item : value.coverage) {
    auto record = Coverage(item.candidate); record["dimension"] = source_names.at(static_cast<std::size_t>(item.dimension));
    projection.Append(coverage, std::move(record));
  }
  auto descriptions = MoveDescriptions(input.moves, projection, input.factory);
  for (const auto& ability : input.abilities) projection.Append(descriptions, {{"source", "ability"}, {"identifier", ability.identifier},
      {"repository", {{"support", support_names.at(static_cast<std::size_t>(ability.support))}, {"reason", ability.reason}}},
      {"factory", Effect(DescribeConfigurationEffect(ConfigurationEffectSource::ability, ability.identifier, input.factory))}});
  for (const auto& item : input.items) projection.Append(descriptions, {{"source", "item"},
      {"factory", Effect(DescribeConfigurationEffect(ConfigurationEffectSource::item, item, input.factory))}});
  auto types = Json::array(); for (const auto type : input.types) types.push_back(static_cast<int>(type));
  return {{"classes", std::move(classes)}, {"coverage", std::move(coverage)}, {"candidate_descriptions", std::move(descriptions)},
      {"raw_configuration_count", value.raw_configuration_count.str()},
      {"pokemon", {{"ruleset_id", input.ruleset_id}, {"version_group_id", input.version_group_id}, {"pokemon_id", input.pokemon_id},
          {"name", input.name}, {"types", std::move(types)}, {"level", input.stats.level}, {"can_evolve", input.can_evolve}}}};
}
/// @tparam Function 同步纯Core计算；@param stop 同源令牌；@param function 完整操作。
/// @return 完整值；仅真实取消才映射CANCELLED，其他runtime错误仍由ABI保留失败分类。
template<class Function>
auto Compute(CancellationToken stop, Function&& function) {
  CheckStop(stop);
  try { return function(); }
  catch (const std::length_error&) { throw RequestError(PBI_RESOURCE_LIMIT_V1, "configuration raw member budget exceeded"); }
  catch (const std::runtime_error&) { CheckStop(stop); throw; }
}
} // namespace

ConfigurationStatsRequest ReadConfigurationStatsRequest(const Json& value, CancellationToken stop) {
  return {ReadStatsInput(Input(value), stop)};
}
ConfigurationMovesRequest ReadConfigurationMovesRequest(const Json& value, CancellationToken stop) {
  return {ReadMovesInput(Input(value), stop)};
}
ConfigurationSpaceRequest ReadConfigurationSpaceRequest(const Json& value, CancellationToken stop) {
  const auto& input = Input(value);
  RequireSchema(input, {"attacker", "defender"}, {"weight_assumption", "max_raw_pairs"});
  return {ReadSide(input.at("attacker"), stop), ReadSide(input.at("defender"), stop),
      input.contains("weight_assumption") ? ReadEnum<ConfigurationWeightAssumption>(input.at("weight_assumption"), assumptions)
          : ConfigurationWeightAssumption::uniform_raw_configuration,
      Budget(input, "max_raw_pairs", 1000000)};
}
ConfigurationCoverageRequest ReadConfigurationCoverageRequest(const Json& value, CancellationToken stop) {
  const auto& input = Input(value);
  if (!input.is_object()) throw RequestError(PBI_INVALID_INPUT_V1, "coverage input must be an object");
  const auto mode = input.contains("mode") ? Text(input.at("mode")) : "describe";
  if (mode == "admission") {
    RequireSchema(input, {"mode", "candidates"}, {"factory", "repository_mode"}); RequireArray(input.at("candidates"));
    const auto factory = input.contains("factory") ? ReadEnum<ConfigurationEffectFactory>(input.at("factory"), factories)
        : ConfigurationEffectFactory::transparent_inference;
    const auto repository = input.contains("repository_mode") ? ReadEnum<ConfigurationRepositoryMode>(input.at("repository_mode"), repository_modes)
        : ConfigurationRepositoryMode::raw;
    ConfigurationAdmissionQueries result;
    for (const auto& candidate : input.at("candidates")) {
      CheckStop(stop);
      RequireFields(candidate, {"source", "effect_identifier", "mechanism_identifier", "repository_reason", "base_executable", "allow_no_effect"});
      result.candidates.push_back({ReadEnum<ConfigurationEffectSource>(candidate.at("source"), source_names),
          OptionalText(candidate.at("effect_identifier")), Text(candidate.at("mechanism_identifier")), Text(candidate.at("repository_reason")),
          ReadBool(candidate.at("base_executable")), ReadBool(candidate.at("allow_no_effect")), factory, repository});
    }
    return {std::move(result)};
  }
  if (mode != "describe") throw RequestError(PBI_UNSUPPORTED_V1, "unsupported configuration coverage mode");
  RequireSchema(input, {"moves", "abilities", "items"}, {"mode", "factory", "include_capabilities"});
  const auto factory = input.contains("factory") ? ReadEnum<ConfigurationEffectFactory>(input.at("factory"), factories)
      : ConfigurationEffectFactory::standard;
  ConfigurationDescriptionQueries result;
  if (input.contains("include_capabilities")) result.include_capabilities = ReadBool(input.at("include_capabilities"));
  constexpr std::array<std::string_view, 3> fields{"moves", "abilities", "items"};
  for (std::size_t index = 0; index < fields.size(); ++index) {
    RequireArray(input.at(fields[index]));
    for (const auto& identifier : input.at(fields[index])) {
      CheckStop(stop); result.effects.push_back({static_cast<ConfigurationEffectSource>(index), OptionalText(identifier), factory});
    }
  }
  return {std::move(result)};
}
JobMovePoolRequest ReadJobMovePoolRequest(const Json& value, CancellationToken stop) {
  const auto& input = Input(value); RequireFields(input, {"command", "admission", "offset", "limit"});
  auto pool = ReadJob(input.at("command"), stop);
  const auto offset = Index(input.at("offset")), limit = Index(input.at("limit"));
  if (offset > pool.CaseCount()) throw RequestError(PBI_INVALID_INPUT_V1, "job page offset exceeds the complete pool");
  const auto& snapshot = input.at("admission");
  RequireFields(snapshot, {"ruleset_id", "version_group_id", "calculation_revision", "candidates"});
  if (Text(snapshot.at("ruleset_id")) != pool.View().ruleset_id || ReadInteger(snapshot.at("version_group_id")) != pool.View().version_group_id ||
      Text(snapshot.at("calculation_revision")) != pool.View().calculation_revision)
    throw RequestError(PBI_INVALID_INPUT_V1, "job admission snapshot does not match the command axes");
  RequireArray(snapshot.at("candidates")); std::vector<JobAdmissionFact> facts;
  for (const auto& fact : snapshot.at("candidates")) {
    CheckStop(stop);
    RequireFields(fact, {"side", "source", "move_id", "move", "effect_identifier", "mechanism_identifier", "repository_reason", "base_executable", "allow_no_effect"});
    std::optional<MoveSpec> move;
    if (!fact.at("move").is_null()) move.emplace(ReadMoveSpecValue(fact.at("move")));
    facts.push_back({ReadEnum<BattleSide>(fact.at("side"), sides),
        fact.at("move_id").is_null() ? std::nullopt : std::optional{ReadInteger(fact.at("move_id"))}, std::move(move),
        {ReadEnum<ConfigurationEffectSource>(fact.at("source"), source_names), OptionalText(fact.at("effect_identifier")),
            Text(fact.at("mechanism_identifier")), Text(fact.at("repository_reason")), ReadBool(fact.at("base_executable")),
            ReadBool(fact.at("allow_no_effect")), ConfigurationEffectFactory::transparent_inference, ConfigurationRepositoryMode::factory_reconciled}});
  }
  ValidateJobFacts(pool, facts, stop);
  return {std::move(pool), std::move(facts), offset, limit};
}
Json EvaluateConfigurationStats(const ConfigurationStatsRequest& request, CancellationToken stop) {
  return Compute(stop, [&] {
    const auto result = EnumerateConfigurationStats(request.input, stop); Projection projection{stop};
    auto classes = Json::array(); for (const auto& item : result.classes) projection.Append(classes, StatClass(item));
    return Json{{"kind", "configuration_stats"}, {"classes", std::move(classes)}, {"raw_profile_count", result.raw_profile_count.str()}};
  });
}
Json EvaluateConfigurationMoves(const ConfigurationMovesRequest& request, CancellationToken stop) {
  return Compute(stop, [&] {
    const auto result = EnumerateConfigurationMoves(request.input, stop); Projection projection{stop};
    auto classes = Json::array(), coverage = Json::array();
    for (const auto& item : result.classes) projection.Append(classes, MoveClass(item));
    for (const auto& item : result.coverage) projection.Append(coverage, Coverage(item));
    auto descriptions = MoveDescriptions(request.input, projection);
    return Json{{"kind", "configuration_moves"}, {"classes", std::move(classes)}, {"coverage", std::move(coverage)},
        {"candidate_descriptions", std::move(descriptions)}, {"raw_combination_count", result.raw_combination_count.str()}};
  });
}
Json EvaluateConfigurationSpace(const ConfigurationSpaceRequest& request, CancellationToken stop) {
  return Compute(stop, [&] {
    const auto result = GenerateConfigurationSpace(request.attacker, request.defender, request.assumption, request.max_raw_pairs, stop);
    Projection projection{stop}; auto attacker = Side(result.attacker, request.attacker, projection);
    auto defender = Side(result.defender, request.defender, projection); auto pairs = Json::array();
    for (const auto& pair : result.pairs) projection.Append(pairs, {{"attacker_class", pair.attacker_class}, {"defender_class", pair.defender_class},
        {"member_count", pair.member_count.str()}, {"weight", FractionJson(pair.weight)}});
    return Json{{"kind", "configuration_space"}, {"attacker", std::move(attacker)}, {"defender", std::move(defender)},
        {"pairs", std::move(pairs)}, {"weight_assumption", assumptions.at(static_cast<std::size_t>(request.assumption))}, {"raw_pair_count", result.raw_pair_count.str()}};
  });
}
Json EvaluateConfigurationCoverage(const ConfigurationCoverageRequest& request, CancellationToken stop) {
  return Compute(stop, [&] {
    Projection projection{stop};
    if (const auto* queries = std::get_if<ConfigurationDescriptionQueries>(&request.queries)) {
      auto effects = Json::array();
      std::vector<ConfigurationEffectRecord> records;
      for (const auto& query : queries->effects) {
        const auto description = DescribeConfigurationEffect(query.source, query.identifier, query.factory);
        auto effect = Effect(description);
        if (queries->include_capabilities) {
          auto capabilities = Json::array();
          for (const auto& capability : description.capabilities) capabilities.push_back({{"identifier", capability.identifier},
              {"status", effect_names.at(static_cast<std::size_t>(capability.status))}, {"reason", capability.reason}});
          effect["capabilities"] = std::move(capabilities);
          records.push_back({query.source, description});
        }
        effect["source"] = source_names.at(static_cast<std::size_t>(query.source));
        effect["factory"] = factories.at(static_cast<std::size_t>(query.factory)); projection.Append(effects, std::move(effect));
      }
      Json result{{"kind", "configuration_coverage"}, {"mode", "describe"}, {"effects", std::move(effects)}};
      if (queries->include_capabilities) {
        const auto coverage = SummarizeConfigurationMechanisms(records, stop);
        result["included_mechanisms"] = coverage.included;
        result["excluded_mechanisms"] = coverage.excluded;
      }
      return result;
    }
    auto candidates = Json::array();
    for (const auto& candidate : std::get<ConfigurationAdmissionQueries>(request.queries).candidates) {
      CheckStop(stop); const auto result = DescribeConfigurationAdmission(candidate);
      projection.Append(candidates, {{"source", source_names.at(static_cast<std::size_t>(candidate.source))},
          {"mechanism_identifier", candidate.mechanism_identifier}, {"factory", factories.at(static_cast<std::size_t>(candidate.factory))},
          {"repository_mode", repository_modes.at(static_cast<std::size_t>(candidate.repository_mode))},
          {"coverage", Effect(result.coverage)}, {"status", admission_names.at(static_cast<std::size_t>(result.status))},
          {"reason", result.reason}, {"selectable", result.Selectable()}, {"missing_mechanism_identifiers", result.missing_mechanism_identifiers}});
    }
    return Json{{"kind", "configuration_coverage"}, {"mode", "admission"}, {"candidates", std::move(candidates)}};
  });
}
Json EvaluateJobMovePool(const JobMovePoolRequest& request, CancellationToken stop) {
  return Compute(stop, [&] {
    // 再次执行整池strict判断；分页绝不以过滤失败候选的方式改变原分母。
    for (const auto& fact : request.admission) {
      CheckStop(stop);
      if (!DescribeConfigurationAdmission(fact.admission).Selectable())
        throw RequestError(PBI_UNSUPPORTED_V1, "job pool contains a mechanism that failed strict admission");
    }
    Projection projection{stop}; auto cases = Json::array();
    const auto count = std::min(request.limit, request.pool.CaseCount() - request.offset);
    for (std::size_t index = 0; index < count; ++index) {
      CheckStop(stop); const auto item = request.pool.CaseAt(request.offset + index);
      projection.Append(cases, {{"ordinal", item.ordinal}, {"configuration_pair_id", item.configuration_pair_id},
          {"attacker_configuration_id", item.attacker_configuration_id}, {"defender_configuration_id", item.defender_configuration_id},
          {"attacker_move_ids", item.attacker_move_ids}, {"defender_move_ids", item.defender_move_ids},
          {"configuration_weight", FractionJson(item.configuration_weight)}});
    }
    const auto next = request.offset + count;
    return Json{{"kind", "job_move_pool"}, {"case_count", request.pool.CaseCount()},
        {"attacker_move_set_count", request.pool.AttackerMoveSetCount()}, {"defender_move_set_count", request.pool.DefenderMoveSetCount()},
        {"offset", request.offset}, {"next_offset", next}, {"has_more", next < request.pool.CaseCount()}, {"cases", std::move(cases)}};
  });
}
} // namespace pbi::contract
