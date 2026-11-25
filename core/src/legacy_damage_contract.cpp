#include "legacy_damage_contract.hpp"

namespace pbi::contract {
namespace {
/// @param value 原明确数组；错误时不把对象/字符串隐式视作序列。
void RequireArray(const Json& value) {
  if (!value.is_array()) throw RequestError(PBI_INVALID_INPUT_V1, "legacy field must be an array");
}
/// @param value 原PokemonDirector实际消费字段；@return 拥有六轴base/完整EV数组/原性格事实。
LegacyPokemonInput ReadLegacyPokemon(const Json& value) {
  RequireSchema(value, {"level", "base", "basepoint", "nature", "types"}, {});
  RequireArray(value.at("base"));
  if (value.at("base").size() != 6) throw RequestError(PBI_INVALID_INPUT_V1, "legacy base requires six stats");
  LegacyPokemonInput pokemon;
  pokemon.level = ReadInteger(value.at("level"));
  for (std::size_t index = 0; index < pokemon.base.size(); ++index) pokemon.base[index] = ReadInteger(value.at("base")[index]);
  RequireArray(value.at("basepoint"));
  pokemon.basepoint.clear();
  for (const auto& effort : value.at("basepoint")) pokemon.basepoint.push_back(ReadInteger(effort));
  if (value.at("nature").is_null()) pokemon.nature = std::nullopt;
  else pokemon.nature = ReadEnum<LegacyNature>(value.at("nature"), std::array<std::string_view, 25>{"Hardy","Lonely","Adamant","Naughty","Brave",
      "Bold","Docile","Impish","Lax","Relaxed","Modest","Mild","Bashful","Rash","Quiet","Calm","Gentle","Careful","Quirky","Sassy",
      "Timid","Hasty","Jolly","Naive","Serious"});
  RequireArray(value.at("types"));
  for (const auto& type : value.at("types")) {
    const auto integer = ReadInt32(type);
    if (integer < 1 || integer > 18) throw RequestError(PBI_INVALID_INPUT_V1, "unknown legacy Pokemon type");
    pokemon.types.push_back(static_cast<PokemonType>(integer));
  }
  return pokemon;
}
/// @param stats 六项原任意精度能力；@return 十进制字符串证据，避免JSON number转换损失大整数。
Json StatsJson(const LegacyStats& stats) {
  auto output = Json::array();
  for (const auto& stat : stats) output.push_back(stat.str());
  return output;
}
} // namespace

LegacyDamageRequest ReadLegacyDamageRequest(const Json& value) {
  RequireSchema(value, {"kind", "attacker", "defender", "move", "random_unit", "type_chart"}, {});
  if (value.at("kind") != "legacy_damage") throw RequestError(PBI_INVALID_INPUT_V1, "invalid legacy damage kind");
  const auto& move = value.at("move");
  RequireSchema(move, {"power", "type", "move_type"}, {});
  const auto type = ReadInt32(move.at("type"));
  if (type < 1 || type > 18) throw RequestError(PBI_INVALID_INPUT_V1, "unknown legacy move type");
  if (!value.at("random_unit").is_number()) throw RequestError(PBI_INVALID_INPUT_V1, "legacy random unit must be numeric");
  LegacyDamageInput input{ReadLegacyPokemon(value.at("attacker")), ReadLegacyPokemon(value.at("defender")),
      {ReadInteger(move.at("power")), static_cast<PokemonType>(type), ReadEnum<DamageCategory>(move.at("move_type"),
          std::array<std::string_view, 3>{"physical_move", "special_move", "status_move"})}, value.at("random_unit").get<double>()};
  return {std::move(input), ReadTypeChart(value.at("type_chart"))};
}

Json EvaluateLegacyDamage(const LegacyDamageRequest& request) {
  const auto result = CalculateLegacyDamage(request.input, request.knowledge);
  return {{"kind", "legacy_damage"}, {"formula", result.formula}, {"min_damage", result.min_damage.str()},
      {"max_damage", result.max_damage.str()}, {"random_damage", result.random_damage.str()}, {"min_damage_percent", result.min_damage_percent},
      {"max_damage_percent", result.max_damage_percent}, {"random_damage_percent", result.random_damage_percent},
      {"attacker_stats", StatsJson(result.attacker_stats)}, {"defender_stats", StatsJson(result.defender_stats)}, {"random_multiplier", result.random_multiplier}};
}
} // namespace pbi::contract
