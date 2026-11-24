#include "pbi/configuration_moves.hpp"
#include <nlohmann/json.hpp>
#include <iostream>

namespace {
using Json = nlohmann::json;
/// @param value 三态repository状态；@return 显式枚举，未知字符串拒绝。
pbi::ConfigurationSupport Support(const Json& value) {
  if (value == "supported") return pbi::ConfigurationSupport::supported;
  if (value == "partial") return pbi::ConfigurationSupport::partial;
  if (value == "unsupported") return pbi::ConfigurationSupport::unsupported;
  throw std::invalid_argument("unknown move support status");
}
/// @param value 领域三态；@return 原协议字符串。
std::string_view Name(pbi::ConfigurationSupport value) {
  switch (value) {
  case pbi::ConfigurationSupport::supported: return "supported";
  case pbi::ConfigurationSupport::partial: return "partial";
  case pbi::ConfigurationSupport::unsupported: return "unsupported";
  }
  throw std::invalid_argument("unknown move support status");
}
/// @param value 领域工厂状态；@return 原协议字符串。
std::string_view Name(pbi::ConfigurationEffectStatus value) {
  switch (value) {
  case pbi::ConfigurationEffectStatus::supported: return "supported";
  case pbi::ConfigurationEffectStatus::partial: return "partial";
  case pbi::ConfigurationEffectStatus::unsupported: return "unsupported";
  case pbi::ConfigurationEffectStatus::no_effect: return "no_effect";
  }
  throw std::invalid_argument("unknown move factory status");
}
/// @param value 明确null或字符串；@return 不做行为推断的可空值。
std::optional<std::string> Text(const Json& value) {
  return value.is_null() ? std::nullopt : std::optional{value.get<std::string>()};
}
/// @param request 原始合法候选完整快照；@return 真实Core过滤和组合结果。
Json Run(const Json& request) {
  pbi::ConfigurationMoveInput input;
  input.requested_ids = request.at("requested_ids").get<std::vector<std::int64_t>>();
  input.slot_counts = request.at("slot_counts").get<std::vector<std::size_t>>();
  input.max_raw_combinations = request.at("max_raw_combinations").get<std::size_t>();
  for (const auto& value : request.at("candidates")) {
    std::optional<pbi::MoveSpec> move;
    if (!value.at("move").is_null()) {
      const auto& spec = value.at("move");
      move.emplace(pbi::MoveSpecData{spec.at("move_id").get<std::int64_t>(), spec.at("name").get<std::string>(),
          {static_cast<pbi::PokemonType>(spec.at("type").get<int>()), static_cast<pbi::DamageCategory>(spec.at("category").get<int>()), spec.at("power").get<std::int32_t>()},
          spec.at("max_pp").get<std::int32_t>(), spec.at("priority").get<std::int32_t>(),
          spec.at("accuracy").is_null() ? std::nullopt : std::optional{spec.at("accuracy").get<std::int32_t>()}, Text(spec.at("effect_identifier"))});
    }
    input.candidates.push_back({value.at("move_id").get<std::int64_t>(), value.at("identifier").get<std::string>(),
        std::move(move), Text(value.at("effect_identifier")), Support(value.at("support")), value.at("reason").get<std::string>()});
  }
  const auto result = pbi::EnumerateConfigurationMoves(input);
  auto classes = Json::array(), coverage = Json::array();
  for (const auto& value : result.classes) {
    auto moves = Json::array();
    for (const auto& move : value.moves) moves.push_back({{"key", pbi::ConfigurationMoveOrderKey(move)}, {"name", move.move.View().name}});
    classes.push_back({{"moves", std::move(moves)}, {"member_count", value.member_count.str()}});
  }
  for (const auto& value : result.coverage) coverage.push_back({{"identifier", value.identifier}, {"support", Name(value.support)},
      {"included", value.included}, {"reason", value.reason}, {"factory_status", value.factory_status ? Json(Name(*value.factory_status)) : Json(nullptr)}});
  return {{"classes", std::move(classes)}, {"coverage", std::move(coverage)}, {"raw_combination_count", result.raw_combination_count.str()}};
}
} // namespace
/// 无参数；逐行运行真实候选过滤，不依赖 Python 工厂或计算进程。
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    try { std::cout << Run(Json::parse(line)).dump() << '\n'; }
    catch (const std::exception& error) { std::cout << Json{{"error", error.what()}}.dump() << '\n'; }
  }
}
