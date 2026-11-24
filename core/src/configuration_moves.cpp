#include "pbi/configuration_moves.hpp"
#include <algorithm>
#include <array>
#include <map>
#include <set>

namespace pbi {
std::optional<std::string> NormalizeConfigurationEffectIdentifier(std::optional<std::string> input) {
  if (!input) return std::nullopt;
  const auto whitespace = [](unsigned char character) { return (character >= 9 && character <= 13) || (character >= 28 && character <= 32); };
  for (const unsigned char character : *input) {
    if (character > 127) throw UnsupportedRule("non-ASCII effect identifiers are unsupported");
  }
  const auto first = std::find_if_not(input->begin(), input->end(), whitespace);
  const auto last = std::find_if_not(input->rbegin(), input->rend(), whitespace).base();
  if (first >= last) return std::nullopt;
  std::string output(first, last);
  for (auto& character : output) {
    if (character >= 'A' && character <= 'Z') character += 'a' - 'A';
    else if (character == '-' || character == ' ') character = '_';
  }
  return output;
}
namespace {
/// @param text ASCII机制标识；@return Python repr 字符串，控制字节不会破坏类排序键。
std::string Repr(const std::string& text) {
  const char quote = text.find('\'') != std::string::npos && text.find('"') == std::string::npos ? '"' : '\'';
  std::string result(1, quote);
  constexpr char hex[] = "0123456789abcdef";
  for (const unsigned char character : text) {
    if (character == quote || character == '\\') { result += '\\'; result += static_cast<char>(character); }
    else if (character == '\n') result += "\\n";
    else if (character == '\r') result += "\\r";
    else if (character == '\t') result += "\\t";
    else if (character < 32 || character == 127) { result += "\\x"; result += hex[character >> 4]; result += hex[character & 15]; }
    else result += static_cast<char>(character);
  }
  result += quote;
  return result;
}
/// @param status 工厂状态；@return 原 provider 的三态映射，no_effect不自动成为supported。
ConfigurationSupport Support(ConfigurationEffectStatus status) {
  switch (status) {
  case ConfigurationEffectStatus::supported: return ConfigurationSupport::supported;
  case ConfigurationEffectStatus::partial: return ConfigurationSupport::partial;
  case ConfigurationEffectStatus::unsupported:
  case ConfigurationEffectStatus::no_effect: return ConfigurationSupport::unsupported;
  }
  throw std::invalid_argument("unknown configuration effect status");
}
/// @param token 可空令牌；取消时抛出整次失败，不返回部分组合分母。
void CheckCancellation(const CancellationToken& token) {
  if (token.Requested()) throw std::runtime_error("configuration move enumeration cancelled");
}
} // namespace

ConfigurationEffectCoverage DescribeConfigurationEffect(ConfigurationEffectSource source,
                                                        std::optional<std::string> identifier) {
  const auto normalized = NormalizeConfigurationEffectIdentifier(std::move(identifier));
  if (source == ConfigurationEffectSource::move) {
    if (!normalized) return {"none", ConfigurationEffectStatus::no_effect, "No move effect identifier was configured.", {}};
    if (*normalized == "ice_punch") return {*normalized, ConfigurationEffectStatus::supported, "Ice Punch uses the standard physical move execution pipeline.", {"freeze_secondary_effect"}};
    if (*normalized == "fake_out") return {*normalized, ConfigurationEffectStatus::supported, "Fake Out adds a first-turn gate and a typed flinch attempt.", {}};
    if (*normalized == "brick_break") return {*normalized, ConfigurationEffectStatus::supported, "Brick Break uses the standard physical move execution pipeline.", {"screen_break"}};
    return {*normalized, ConfigurationEffectStatus::unsupported, "The move effect is not implemented for this ruleset.", {}};
  }
  if (source == ConfigurationEffectSource::ability) {
    if (!normalized) return {"none", ConfigurationEffectStatus::no_effect, "No supported ability identifier was configured.", {}};
    if (*normalized == "inner_focus") return {*normalized, ConfigurationEffectStatus::partial, "Flinch immunity is supported; modern Intimidate immunity is not implemented.", {"intimidate_immunity"}};
    constexpr std::array<std::string_view, 7> abilities{"technician", "adaptability", "thick_fat", "filter", "solid_rock", "sniper", "multiscale"};
    if (std::ranges::find(abilities, *normalized) != abilities.end()) {
      return {*normalized, ConfigurationEffectStatus::supported, "Existing ability damage behavior is available through an adapter.", {}};
    }
    return {*normalized, ConfigurationEffectStatus::unsupported, "The ability identifier is not implemented for this ruleset.", {}};
  }
  if (source == ConfigurationEffectSource::item) {
    if (!normalized) return {"none", ConfigurationEffectStatus::no_effect, "No supported item identifier was configured.", {}};
    if (*normalized == "choice_band") return {*normalized, ConfigurationEffectStatus::supported,
        "Choice Band attack multiplier and move-selection lock are supported; item removal, suppression, swap, and consumption interactions are deferred.", {}};
    constexpr std::array<std::string_view, 4> items{"life_orb", "choice_specs", "expert_belt", "eviolite"};
    if (std::ranges::find(items, *normalized) != items.end()) {
      return {*normalized, ConfigurationEffectStatus::supported, "Existing item damage behavior is available through an adapter.", {}};
    }
    return {*normalized, ConfigurationEffectStatus::unsupported, "The item identifier is not implemented for this ruleset.", {}};
  }
  throw std::invalid_argument("unknown configuration effect source");
}

std::string ConfigurationMoveOrderKey(const ConfigurationMove& configured) {
  const auto& move = configured.move.View();
  std::string category;
  switch (move.move.category) {
  case DamageCategory::physical: category = "<MoveCategory.PHYSICAL: 'physical'>"; break;
  case DamageCategory::special: category = "<MoveCategory.SPECIAL: 'special'>"; break;
  case DamageCategory::status: category = "<MoveCategory.STATUS: 'status'>"; break;
  }
  return "(MoveSpecKey(move_id=" + std::to_string(move.move_id) + ", move_type_id=" +
      std::to_string(static_cast<int>(move.move.type)) + ", category=" + category + ", power=" + std::to_string(move.move.power) +
      ", accuracy=" + (move.accuracy ? std::to_string(*move.accuracy) : "None") + ", max_pp=" + std::to_string(move.max_pp) +
      ", priority=" + std::to_string(move.priority) + ", effect_identifier=" + (move.effect_identifier ? Repr(*move.effect_identifier) : "None") +
      "), " + Repr(configured.effect_identifier.value_or("none")) + ')';
}

ConfigurationMoveSpace EnumerateConfigurationMoves(const ConfigurationMoveInput& input,
                                                   CancellationToken cancellation) {
  if (input.max_raw_combinations == 0) throw std::invalid_argument("max_raw_combinations must be positive");
  CheckCancellation(cancellation);
  std::set<std::int64_t> requested;
  for (const auto identifier : input.requested_ids) {
    if (identifier <= 0 || !requested.insert(identifier).second) throw std::invalid_argument("requested move IDs must be positive and unique");
  }
  auto slots = input.slot_counts;
  std::ranges::sort(slots);
  if (std::ranges::any_of(slots, [](auto count) { return count < 1 || count > 4; }) ||
      std::ranges::adjacent_find(slots) != slots.end()) {
    throw std::invalid_argument("move slot counts must be unique and between 1 and 4");
  }
  struct Option {
    ConfigurationMove configured;
    Integer member_count;
    std::string key;
  };
  std::vector<Option> options;
  std::map<std::string, std::size_t> grouped;
  ConfigurationMoveSpace result;
  for (const auto& candidate : input.candidates) {
    CheckCancellation(cancellation);
    if (candidate.move_id <= 0 || candidate.identifier.empty() || candidate.reason.empty()) throw std::invalid_argument("move candidate identity and reason must be nonempty");
    if (candidate.support != ConfigurationSupport::supported && candidate.support != ConfigurationSupport::partial && candidate.support != ConfigurationSupport::unsupported) {
      throw std::invalid_argument("unknown repository move support status");
    }
    if (!requested.empty() && !requested.contains(candidate.move_id)) {
      result.coverage.push_back({candidate.identifier, candidate.support, false, "The move is legal but excluded by the command candidate pool.", std::nullopt});
      continue;
    }
    if (candidate.support != ConfigurationSupport::supported) {
      result.coverage.push_back({candidate.identifier, candidate.support, false, candidate.reason, std::nullopt});
      continue;
    }
    if (!candidate.move || candidate.move->View().move_id != candidate.move_id) throw std::invalid_argument("supported move candidate must contain a matching executable MoveSpec");
    const auto candidate_effect = NormalizeConfigurationEffectIdentifier(candidate.effect_identifier);
    const auto spec_effect = candidate.move->View().effect_identifier;
    if (candidate_effect && spec_effect && candidate_effect != spec_effect) throw std::invalid_argument("candidate and MoveSpec effect identifiers must match");
    const auto effect_identifier = candidate_effect ? candidate_effect : spec_effect;
    const auto effect = DescribeConfigurationEffect(ConfigurationEffectSource::move, effect_identifier);
    const bool status_move = candidate.move->View().move.category == DamageCategory::status;
    const bool complete_no_effect = !effect_identifier && !status_move && effect.status == ConfigurationEffectStatus::no_effect;
    const bool included = effect.status == ConfigurationEffectStatus::supported || complete_no_effect;
    const auto reason = !included && status_move && effect.status == ConfigurationEffectStatus::no_effect
        ? "A status move requires an explicit supported effect implementation." : effect.reason;
    result.coverage.push_back({candidate.identifier, included ? ConfigurationSupport::supported : Support(effect.status), included, reason, effect.status});
    if (!included) continue;
    ConfigurationMove configured{*candidate.move, effect.status == ConfigurationEffectStatus::no_effect ? std::nullopt : std::optional{effect.identifier}};
    const auto key = ConfigurationMoveOrderKey(configured);
    const auto [found, inserted] = grouped.emplace(key, options.size());
    if (inserted) options.push_back({std::move(configured), Integer{1}, key});
    else ++options[found->second].member_count;
  }
  std::ranges::sort(options, [](const auto& first, const auto& second) {
    if (first.configured.move.View().move_id != second.configured.move.View().move_id) return first.configured.move.View().move_id < second.configured.move.View().move_id;
    return first.key < second.key;
  });
  if (slots.empty() && !options.empty()) slots.push_back(std::min<std::size_t>(options.size(), 4));
  std::vector<std::size_t> selected;
  std::map<std::vector<std::string>, std::size_t> grouped_sets;
  /// @param self 显式递归；@param count 目标槽数量；@param start 后继候选下标。
  /// 只枚举无序索引组合，同一招式不同 projection 不能占多个槽。
  const auto visit = [&](auto&& self, std::size_t count, std::size_t start) -> void {
    CheckCancellation(cancellation);
    if (selected.size() == count) {
      Integer members{1};
      std::vector<ConfigurationMove> moves;
      std::vector<std::string> signature;
      for (const auto index : selected) {
        members *= options[index].member_count;
        moves.push_back(options[index].configured);
        signature.push_back(options[index].key);
      }
      result.raw_combination_count += members;
      if (result.raw_combination_count > input.max_raw_combinations) throw std::length_error("move-set enumeration exceeds max_raw_combinations");
      const auto [found, inserted] = grouped_sets.emplace(std::move(signature), result.classes.size());
      if (inserted) result.classes.push_back({std::move(moves), members});
      else result.classes[found->second].member_count += members;
      return;
    }
    const auto missing = count - selected.size();
    for (std::size_t index = start; index < options.size() && options.size() - index >= missing; ++index) {
      if (std::ranges::any_of(selected, [&](auto previous) { return options[previous].configured.move.View().move_id == options[index].configured.move.View().move_id; })) continue;
      selected.push_back(index);
      self(self, count, index + 1);
      selected.pop_back();
    }
  };
  for (const auto count : slots) if (count <= options.size()) visit(visit, count, 0);
  return result;
}
} // namespace pbi
