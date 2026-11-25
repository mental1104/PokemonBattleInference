#include "pbi/configuration_stats.hpp"
#include <nlohmann/json.hpp>
#include <iostream>

namespace {
using Json = nlohmann::json;
/// @param input 固定六项数组；@return 完整拥有能力快照，缺项/越界由 JSON 明确拒绝。
pbi::BattleStats ReadStats(const Json& input) {
  const auto values = input.get<std::array<std::int32_t, 6>>();
  return {values[0], values[1], values[2], values[3], values[4], values[5]};
}
/// @param input 只读完整能力；@return 固定顺序六项 JSON，便于独立逐字段对照。
Json Stats(const pbi::BattleStats& input) {
  return Json::array({input.hp, input.attack, input.defense, input.special_attack, input.special_defense, input.speed});
}
/// @param input 完整快照；@return 测试边界读取，不计算能力或过滤候选。
pbi::ConfigurationStatProfile Profile(const Json& input) {
  return {ReadStats(input.at("ivs")), ReadStats(input.at("evs")),
          {input.at("nature").get<std::array<double, 5>>()}};
}
/// @param request 一条显式预设/受控候选命令；@return 实际纯 Core 归并结果。
Json Run(const Json& request) {
  pbi::ConfigurationStatInput input;
  input.base = ReadStats(request.at("base"));
  input.level = request.at("level").get<std::int32_t>();
  input.max_raw_profiles = request.at("max_raw_profiles").get<std::size_t>();
  if (request.at("mode") == "preset") {
    pbi::PresetStatEnumeration presets;
    for (const auto& value : request.at("presets")) presets.presets.push_back({Profile(value), value.at("label").get<std::string>()});
    input.enumeration = std::move(presets);
  } else if (request.at("mode") == "controlled") {
    pbi::ControlledStatEnumeration command;
    for (const auto& field : request.at("fields")) command.fields.push_back(static_cast<pbi::ConfigurationStatField>(field.get<int>()));
    command.ev_values = request.at("ev_values").get<std::vector<std::int32_t>>();
    for (const auto& nature : request.at("natures")) command.natures.push_back({nature.get<std::array<double, 5>>()});
    input.enumeration = std::move(command);
  } else throw std::invalid_argument("unknown configuration stat test mode");
  const auto result = pbi::EnumerateConfigurationStats(input);
  auto classes = Json::array();
  for (const auto& value : result.classes) {
    classes.push_back({{"actual", Stats(value.actual)}, {"ivs", Stats(value.representative.ivs)},
                       {"evs", Stats(value.representative.evs)}, {"nature", value.representative.nature.multipliers},
                       {"label", value.label}, {"member_count", value.member_count.str()}});
  }
  return {{"classes", std::move(classes)}, {"raw_profile_count", result.raw_profile_count.str()}};
}
} // namespace
/// 无参数；逐行运行真实纯枚举，错误按独立结果返回，不调用 Python。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << Run(Json::parse(line)).dump() << '\n'; }
    catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
