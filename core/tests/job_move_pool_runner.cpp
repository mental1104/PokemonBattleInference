#include "pbi/job_move_pool.hpp"
#include "pbi/configuration_admission.hpp"
#include <nlohmann/json.hpp>
#include <iostream>

namespace {
using Json = nlohmann::json;
/// @param value null或字符串；@return 完整可空值，不规范化身份内容。
std::optional<std::string> Text(const Json& value) {
  return value.is_null() ? std::nullopt : std::optional{value.get<std::string>()};
}
/// @param value 原固定身份对象；@return 完整类型值，不计算任何能力或机制。
pbi::JobFixedPokemon Fixed(const Json& value) {
  return {value.at("pokemon_id").get<std::int64_t>(), value.at("form_id").is_null() ? std::nullopt : std::optional{value.at("form_id").get<std::int64_t>()},
      value.at("level").get<std::int32_t>(), value.at("stat_profile_id").get<std::string>(), value.at("ability_identifier").get<std::string>(), Text(value.at("item_identifier"))};
}
/// @param value 原模式文本；@return 有限模式，不回退到fixed。
pbi::JobDimensionMode Dimension(const Json& value) {
  if (value == "fixed") return pbi::JobDimensionMode::fixed;
  if (value == "candidate_pool") return pbi::JobDimensionMode::candidate_pool;
  if (value == "disabled") return pbi::JobDimensionMode::disabled;
  throw std::invalid_argument("unknown job dimension mode");
}
/// @param value 原策略文本；@return 有限策略，不替换玩家选择规则。
pbi::ActionPolicy Policy(const Json& value) {
  if (value == "uniform-random") return pbi::ActionPolicy::uniform_random;
  if (value == "first-legal-action") return pbi::ActionPolicy::first_legal_action;
  throw std::invalid_argument("unknown job action policy");
}
/// @param request 完整原job-v1命令及分页；@return 真实惰性Core的具体case身份。
Json Job(const Json& request) {
  const auto& value = request.at("command");
  if (value.at("weight_assumption") != "uniform_configuration_pair" || value.at("mechanism_admission") != "supported_only") {
    throw std::invalid_argument("unsupported job weighting or mechanism admission policy");
  }
  const auto& first = value.at("attacker"), second = value.at("defender"), modes = value.at("dimensions");
  pbi::JobMovePoolInput input{value.at("ruleset_id").get<std::string>(), value.at("version_group_id").get<std::int64_t>(),
      value.at("calculation_revision").get<std::string>(),
      {Fixed(first.at("fixed")), first.at("candidate_move_ids").get<std::vector<std::int64_t>>()},
      {Fixed(second.at("fixed")), second.at("candidate_move_ids").get<std::vector<std::int64_t>>()},
      {Dimension(modes.at("pokemon")), Dimension(modes.at("form")), Dimension(modes.at("level")), Dimension(modes.at("stats")),
       Dimension(modes.at("ability")), Dimension(modes.at("item")), Dimension(modes.at("moves")), Dimension(modes.at("special_mechanics"))},
      Policy(value.at("attacker_policy")), Policy(value.at("defender_policy")), value.at("contract_version").get<std::string>()};
  const pbi::JobMovePool pool{std::move(input)};
  const auto page = pool.Page(request.at("offset").get<std::size_t>(), request.at("limit").get<std::size_t>());
  auto cases = Json::array();
  for (const auto& item : page) cases.push_back({{"ordinal", item.ordinal}, {"configuration_pair_id", item.configuration_pair_id},
      {"attacker_configuration_id", item.attacker_configuration_id}, {"defender_configuration_id", item.defender_configuration_id},
      {"attacker_move_ids", item.attacker_move_ids}, {"defender_move_ids", item.defender_move_ids},
      {"numerator", item.configuration_weight.numerator().str()}, {"denominator", item.configuration_weight.denominator().str()}});
  return {{"case_count", pool.CaseCount()}, {"attacker_move_set_count", pool.AttackerMoveSetCount()},
      {"defender_move_set_count", pool.DefenderMoveSetCount()}, {"cases", std::move(cases)}};
}
/// @param value 显式产品来源；@return 正式有限来源。
pbi::ConfigurationEffectSource Source(const Json& value) {
  if (value == "move") return pbi::ConfigurationEffectSource::move;
  if (value == "ability") return pbi::ConfigurationEffectSource::ability;
  if (value == "item") return pbi::ConfigurationEffectSource::item;
  throw std::invalid_argument("unknown configuration effect source");
}
/// @param request 原strict准入事实；@return 实际Core factory与strict最终裁定。
Json Admission(const Json& request) {
  pbi::ConfigurationEffectFactory factory;
  if (request.at("factory") == "standard") factory = pbi::ConfigurationEffectFactory::standard;
  else if (request.at("factory") == "transparent_inference") factory = pbi::ConfigurationEffectFactory::transparent_inference;
  else throw std::invalid_argument("unknown configuration effect factory");
  pbi::ConfigurationRepositoryMode repository;
  if (request.at("repository_mode") == "raw") repository = pbi::ConfigurationRepositoryMode::raw;
  else if (request.at("repository_mode") == "factory_reconciled") repository = pbi::ConfigurationRepositoryMode::factory_reconciled;
  else throw std::invalid_argument("unknown configuration repository mode");
  const auto result = pbi::DescribeConfigurationAdmission({Source(request.at("source")), Text(request.at("effect_identifier")),
      request.at("mechanism_identifier").get<std::string>(), request.at("repository_reason").get<std::string>(),
      request.at("base_executable").get<bool>(), request.at("allow_no_effect").get<bool>(), factory, repository});
  constexpr std::array<std::string_view, 4> statuses{"supported", "no_effect", "partial", "unsupported"};
  constexpr std::array<std::string_view, 4> factory_statuses{"supported", "partial", "unsupported", "no_effect"};
  return {{"status", statuses.at(static_cast<std::size_t>(result.status))}, {"selectable", result.Selectable()}, {"reason", result.reason},
      {"missing_mechanism_identifiers", result.missing_mechanism_identifiers}, {"coverage", {{"identifier", result.coverage.identifier},
      {"status", factory_statuses.at(static_cast<std::size_t>(result.coverage.status))}, {"reason", result.coverage.reason}, {"missing_capabilities", result.coverage.missing_capabilities}}}};
}
} // namespace
/// 无参数；逐行运行真实Core池或严格准入，错误整体返回不带部分case。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try {
      const auto request = Json::parse(line);
      if (request.at("mode") == "job") std::cout << Job(request).dump() << '\n';
      else if (request.at("mode") == "admission") std::cout << Admission(request).dump() << '\n';
      else throw std::invalid_argument("unknown job test mode");
    } catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
