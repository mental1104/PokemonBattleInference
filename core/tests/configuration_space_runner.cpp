#include "pbi/configuration_space.hpp"
#include <nlohmann/json.hpp>
#include <iostream>

namespace {
using Json = nlohmann::json;
/// @param value 明确null或字符串；@return 完整可空标识，不处理规则。
std::optional<std::string> Text(const Json& value) {
  return value.is_null() ? std::nullopt : std::optional{value.get<std::string>()};
}
/// @param value 六项数组；@return 固定顺序的拥有值。
pbi::BattleStats ReadStats(const Json& value) {
  const auto fields = value.get<std::array<std::int32_t, 6>>();
  return {fields[0], fields[1], fields[2], fields[3], fields[4], fields[5]};
}
/// @param value 只读能力；@return 完整六项数组。
Json Stats(const pbi::BattleStats& value) {
  return Json::array({value.hp, value.attack, value.defense, value.special_attack, value.special_defense, value.speed});
}
/// @param value repository三态文本；@return 有限枚举，未知值失败。
pbi::ConfigurationSupport Support(const Json& value) {
  if (value == "supported") return pbi::ConfigurationSupport::supported;
  if (value == "partial") return pbi::ConfigurationSupport::partial;
  if (value == "unsupported") return pbi::ConfigurationSupport::unsupported;
  throw std::invalid_argument("unknown repository configuration support");
}
/// @param value 已验证三态枚举；@return 原协议文本。
std::string_view Name(pbi::ConfigurationSupport value) {
  switch (value) {
  case pbi::ConfigurationSupport::supported: return "supported";
  case pbi::ConfigurationSupport::partial: return "partial";
  case pbi::ConfigurationSupport::unsupported: return "unsupported";
  }
  throw std::invalid_argument("unknown repository configuration support");
}
/// @param value 已验证工厂枚举；@return 原协议文本。
std::string_view Name(pbi::ConfigurationEffectStatus value) {
  switch (value) {
  case pbi::ConfigurationEffectStatus::supported: return "supported";
  case pbi::ConfigurationEffectStatus::partial: return "partial";
  case pbi::ConfigurationEffectStatus::unsupported: return "unsupported";
  case pbi::ConfigurationEffectStatus::no_effect: return "no_effect";
  }
  throw std::invalid_argument("unknown factory configuration support");
}
/// @param value 完整测试侧输入；@return 类型化纯域候选，不做过滤/枚举/能力计算。
pbi::ConfigurationPokemonInput ReadSide(const Json& value) {
  pbi::ConfigurationPokemonInput result;
  result.ruleset_id = value.at("ruleset_id").get<std::string>();
  result.version_group_id = value.at("version_group_id").get<std::int64_t>();
  result.pokemon_id = value.at("pokemon_id").get<std::int64_t>();
  result.name = value.at("name").get<std::string>();
  result.can_evolve = value.at("can_evolve").get<bool>();
  for (const auto& type : value.at("types")) result.types.push_back(static_cast<pbi::PokemonType>(type.get<int>()));
  const auto& moves = value.at("moves");
  result.moves.requested_ids = moves.at("requested_ids").get<std::vector<std::int64_t>>();
  result.moves.slot_counts = moves.at("slot_counts").get<std::vector<std::size_t>>();
  result.moves.max_raw_combinations = moves.at("max_raw_combinations").get<std::size_t>();
  for (const auto& candidate : moves.at("candidates")) {
    std::optional<pbi::MoveSpec> spec;
    if (!candidate.at("move").is_null()) {
      const auto& move = candidate.at("move");
      spec.emplace(pbi::MoveSpecData{move.at("move_id").get<std::int64_t>(), move.at("name").get<std::string>(),
          {static_cast<pbi::PokemonType>(move.at("type").get<int>()), static_cast<pbi::DamageCategory>(move.at("category").get<int>()), move.at("power").get<std::int32_t>()},
          move.at("max_pp").get<std::int32_t>(), move.at("priority").get<std::int32_t>(),
          move.at("accuracy").is_null() ? std::nullopt : std::optional{move.at("accuracy").get<std::int32_t>()}, Text(move.at("effect_identifier"))});
    }
    result.moves.candidates.push_back({candidate.at("move_id").get<std::int64_t>(), candidate.at("identifier").get<std::string>(),
        std::move(spec), Text(candidate.at("effect_identifier")), Support(candidate.at("support")), candidate.at("reason").get<std::string>()});
  }
  const auto& stats = value.at("stats");
  result.stats.base = ReadStats(stats.at("base"));
  result.stats.level = stats.at("level").get<std::int32_t>();
  result.stats.max_raw_profiles = stats.at("max_raw_profiles").get<std::size_t>();
  if (stats.at("mode") == "preset") {
    pbi::PresetStatEnumeration enumeration;
    for (const auto& preset : stats.at("presets")) enumeration.presets.push_back({
        {ReadStats(preset.at("ivs")), ReadStats(preset.at("evs")), {preset.at("nature").get<std::array<double, 5>>()}}, preset.at("label").get<std::string>()});
    result.stats.enumeration = std::move(enumeration);
  } else if (stats.at("mode") == "controlled") {
    pbi::ControlledStatEnumeration enumeration;
    for (const auto& field : stats.at("fields")) enumeration.fields.push_back(static_cast<pbi::ConfigurationStatField>(field.get<int>()));
    enumeration.ev_values = stats.at("ev_values").get<std::vector<std::int32_t>>();
    for (const auto& nature : stats.at("natures")) enumeration.natures.push_back({nature.get<std::array<double, 5>>()});
    result.stats.enumeration = std::move(enumeration);
  } else throw std::invalid_argument("unknown configuration stat enumeration mode");
  for (const auto& candidate : value.at("abilities")) result.abilities.push_back({candidate.at("identifier").get<std::string>(), Support(candidate.at("support")), candidate.at("reason").get<std::string>()});
  result.requested_abilities = value.at("requested_abilities").get<std::vector<std::string>>();
  result.items.clear();
  for (const auto& item : value.at("items")) result.items.push_back(Text(item));
  result.max_raw_configurations = value.at("max_raw_configurations").get<std::size_t>();
  if (value.contains("factory")) {
    const auto factory = value.at("factory").get<std::string>();
    if (factory == "transparent_inference") result.factory = pbi::ConfigurationEffectFactory::transparent_inference;
    else if (factory != "standard") throw std::invalid_argument("unknown configuration factory");
  }
  if (value.contains("repository_mode")) {
    const auto mode = value.at("repository_mode").get<std::string>();
    if (mode == "factory_reconciled") result.repository_mode = pbi::ConfigurationRepositoryMode::factory_reconciled;
    else if (mode != "raw") throw std::invalid_argument("unknown configuration repository mode");
  }
  return result;
}
/// @param space 已完整求出的单侧空间；@return 全部行为、第一代表、成员数与覆盖。
Json Side(const pbi::ConfigurationPokemonSpace& space) {
  auto classes = Json::array(), coverage = Json::array();
  for (const auto& value : space.classes) {
    auto names = Json::array();
    for (const auto& move : value.moves.moves) names.push_back(move.move.View().name);
    classes.push_back({{"key", value.order_key}, {"member_count", value.member_count.str()},
        {"ivs", Stats(value.stats.representative.ivs)}, {"evs", Stats(value.stats.representative.evs)},
        {"nature", value.stats.representative.nature.multipliers}, {"stat_label", value.stats.label}, {"move_names", std::move(names)}});
  }
  for (const auto& record : space.coverage) {
    const auto& value = record.candidate;
    const auto dimension = record.dimension == pbi::ConfigurationEffectSource::move ? "moves"
        : record.dimension == pbi::ConfigurationEffectSource::ability ? "ability" : "item";
    coverage.push_back({{"dimension", dimension}, {"identifier", value.identifier}, {"support", Name(value.support)},
        {"included", value.included}, {"reason", value.reason}, {"factory_status", value.factory_status ? Json(Name(*value.factory_status)) : Json(nullptr)}});
  }
  return {{"classes", std::move(classes)}, {"coverage", std::move(coverage)}, {"raw_configuration_count", space.raw_configuration_count.str()}};
}
/// @param request 完整原候选命令；@return 真实Core双方分区与精确pair权重。
Json Run(const Json& request) {
  const auto first = ReadSide(request.at("attacker")), second = ReadSide(request.at("defender"));
  pbi::ConfigurationWeightAssumption assumption;
  if (request.at("weight_assumption") == "uniform_raw_configuration") assumption = pbi::ConfigurationWeightAssumption::uniform_raw_configuration;
  else if (request.at("weight_assumption") == "uniform_equivalence_class") assumption = pbi::ConfigurationWeightAssumption::uniform_equivalence_class;
  else throw std::invalid_argument("unknown configuration weight assumption");
  const auto result = pbi::GenerateConfigurationSpace(first, second, assumption, request.at("max_raw_pairs").get<std::size_t>());
  auto pairs = Json::array();
  for (const auto& value : result.pairs) pairs.push_back({{"attacker_key", result.attacker.classes[value.attacker_class].order_key},
      {"defender_key", result.defender.classes[value.defender_class].order_key}, {"member_count", value.member_count.str()},
      {"numerator", value.weight.numerator().str()}, {"denominator", value.weight.denominator().str()}});
  return {{"attacker", Side(result.attacker)}, {"defender", Side(result.defender)}, {"pairs", std::move(pairs)}, {"raw_pair_count", result.raw_pair_count.str()}};
}
} // namespace
/// 无参数；逐行执行真实四维候选生成，整体错误不带部分分区。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << Run(Json::parse(line)).dump() << '\n'; }
    catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
