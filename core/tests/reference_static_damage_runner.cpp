#include "../src/json_contract.hpp"
#include <iostream>

namespace {
using Json = pbi::contract::Json;
/// @param value 完整旧DamageOperation加明确reference_static上下文；@return 类型化未计算输入。
/// 这是纯函数差分的字段适配，公共ABI context注册仍由唯一正式ReadDamage负责。
pbi::DamageInput Input(const Json& value) {
  pbi::contract::RequireFields(value, {"kind", "context", "generation_id", "attacker", "defender", "move", "type_chart", "policy", "weather", "terrain", "defender_side",
      "critical", "spread", "protect_reduced", "multi_target"});
  if (value.at("kind") != "damage" || value.at("context") != "reference_static") throw std::invalid_argument("expected explicit reference_static damage input");
  const auto& move = value.at("move");
  pbi::contract::RequireFields(move, {"type", "category", "power"});
  const auto& side = value.at("defender_side");
  pbi::contract::RequireFields(side, {"reflect", "light_screen", "aurora_veil"});
  return {pbi::contract::ReadPokemon(value.at("attacker")), pbi::contract::ReadPokemon(value.at("defender")),
      {static_cast<pbi::PokemonType>(pbi::contract::ReadInt32(move.at("type"))), pbi::contract::ReadEnum<pbi::DamageCategory>(move.at("category"),
          std::array<std::string_view, 3>{"physical", "special", "status"}), pbi::contract::ReadInt32(move.at("power"))},
      pbi::contract::ReadPolicy(value.at("policy"), pbi::DamagePolicyForGeneration(pbi::contract::ReadInt32(value.at("generation_id")))),
      pbi::contract::ReadEnum<pbi::DamageWeather>(value.at("weather"), std::array<std::string_view, 6>{"none", "harsh_sunlight", "rain", "sandstorm", "hail", "snow"}),
      pbi::contract::ReadEnum<pbi::DamageTerrain>(value.at("terrain"), std::array<std::string_view, 5>{"none", "electric_terrain", "psychic_terrain", "grassy_terrain", "misty_terrain"}),
      {pbi::contract::ReadBool(side.at("reflect")), pbi::contract::ReadBool(side.at("light_screen")), pbi::contract::ReadBool(side.at("aurora_veil"))},
      pbi::contract::ReadBool(value.at("critical")), pbi::contract::ReadBool(value.at("spread")), pbi::contract::ReadBool(value.at("protect_reduced")), pbi::contract::ReadBool(value.at("multi_target"))};
}
} // namespace
/// 无参数；逐行真实调用唯一typed参考静态伤害入口与完整既有DamageJson投影。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      const auto value = Json::parse(line);
      const auto input = Input(value);
      std::cout << pbi::contract::DamageJson(pbi::CalculateReferenceStaticDamage(input, pbi::contract::ReadTypeChart(value.at("type_chart"))),
          pbi::contract::ReadInt32(value.at("generation_id"))).dump() << '\n';
    } catch (const std::exception& error) {
      std::cout << Json{{"error", error.what()}}.dump() << '\n';
    }
  }
}
