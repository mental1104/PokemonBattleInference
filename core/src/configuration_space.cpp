#include "pbi/configuration_space.hpp"
#include "configuration_moves_internal.hpp"
#include <algorithm>
#include <map>
#include <numeric>
#include <set>

namespace pbi {
namespace {
/// @param token 可空共享令牌；取消时不返回不完整配置分区。
void CheckCancellation(const CancellationToken& token) {
  if (token.Requested()) throw std::runtime_error("configuration space generation cancelled");
}
/// @param input 本次明确composition及原profile展示名；@param dimension 原三种provider维度。
/// 新composition返回原generator诊断；已发布standard/raw保留原Core错误文本。
[[noreturn]] void EmptyDimension(const ConfigurationPokemonInput& input, ConfigurationEffectSource dimension) {
  if (input.factory != ConfigurationEffectFactory::standard || input.repository_mode != ConfigurationRepositoryMode::raw) {
    const auto key = dimension == ConfigurationEffectSource::move ? "moves" : dimension == ConfigurationEffectSource::ability ? "ability" : "item";
    throw std::invalid_argument(std::string{"dimension '"} + key + "' has no supported candidates for " + input.name);
  }
  if (dimension == ConfigurationEffectSource::move) throw std::invalid_argument("configuration moves dimension has no executable values");
  if (dimension == ConfigurationEffectSource::ability) throw std::invalid_argument("configuration ability dimension has no executable values");
  throw std::invalid_argument("configuration item dimension has no executable values");
}
/// @param input 已读取ASCII标识；@return 原工厂规范标识，不在外层复制规则。
std::string Normalize(const std::string& input) {
  return NormalizeConfigurationEffectIdentifier(input).value_or("");
}
/// @param value 只读ASCII规则轴/机制键；@return Python repr 的稳定引号形式。
std::string Quote(const std::string& value) {
  // 机制已由统一规范化完成ASCII约束；规则轴只允许当前工厂固定标识。
  const char quote = value.find('\'') != std::string::npos && value.find('"') == std::string::npos ? '"' : '\'';
  std::string result(1, quote);
  constexpr char hex[] = "0123456789abcdef";
  for (const unsigned char character : value) {
    if (character == quote || character == '\\') { result += '\\'; result += static_cast<char>(character); }
    else if (character == '\n') result += "\\n";
    else if (character == '\r') result += "\\r";
    else if (character == '\t') result += "\\t";
    else if (character < 32 || character == 127) { result += "\\x"; result += hex[character >> 4]; result += hex[character & 15]; }
    else result += static_cast<char>(character);
  }
  return result + quote;
}
/// @param values 已格式化完整元素；@return Python tuple repr，单元素保留尾逗号。
std::string Tuple(const std::vector<std::string>& values) {
  std::string output = "(";
  for (std::size_t index = 0; index < values.size(); ++index) {
    if (index != 0) output += ", ";
    output += values[index];
  }
  if (values.size() == 1) output += ',';
  return output + ')';
}
/// @param input 原始身份/属性；@param moves 规范组合；@param stats 实际能力类。
/// @param ability 规范特性；@param item 规范道具；@return 原标准四维行为repr排序键。
std::string OrderKey(const ConfigurationPokemonInput& input, const ConfigurationMoveClass& moves,
                     const ConfigurationStatClass& stats, const std::string& ability, const std::string& item) {
  std::vector<std::string> types, move_keys;
  for (const auto type : input.types) types.push_back(std::to_string(static_cast<int>(type)));
  for (const auto& move : moves.moves) move_keys.push_back(ConfigurationMoveOrderKey(move));
  const auto& value = stats.actual;
  const auto actual = Tuple({std::to_string(value.hp), std::to_string(value.attack), std::to_string(value.defense),
                            std::to_string(value.special_attack), std::to_string(value.special_defense), std::to_string(value.speed)});
  return Tuple({Quote(input.ruleset_id), std::to_string(input.version_group_id), std::to_string(input.pokemon_id),
                std::to_string(input.stats.level), Tuple(types), actual, Tuple(move_keys), Quote(ability), Quote(item),
                input.can_evolve ? "True" : "False", "()"});
}
/// 一项规范特性/道具及去重前原始成员数，保持首次遇见顺序。
struct EffectOption {
  std::string identifier;
  Integer members;
};
/// @param values 正在构造的拥有集合；@param grouped 索引；@param identifier 规范标识。
/// 第一代表保持不变，只增加精确成员计数。
void AppendEffect(std::vector<EffectOption>& values, std::map<std::string, std::size_t>& grouped,
                  const std::string& identifier) {
  const auto [entry, inserted] = grouped.emplace(identifier, values.size());
  if (inserted) values.push_back({identifier, Integer{1}});
  else ++values[entry->second].members;
}
/// @param input 单侧完整命令；@param coverage 输出覆盖；@param token 共享取消。
/// @return 原AbilityDimensionProvider支持、规范化、命令过滤和归并的完整结果。
std::vector<EffectOption> Abilities(const ConfigurationPokemonInput& input,
                                   std::vector<ConfigurationCoverage>& coverage, const CancellationToken& token) {
  std::set<std::string> requested;
  for (const auto& value : input.requested_abilities) {
    const auto identifier = Normalize(value);
    if (identifier.empty() || !requested.insert(identifier).second) throw std::invalid_argument("ability candidate identifiers must be nonblank and unique");
  }
  std::vector<EffectOption> values;
  std::map<std::string, std::size_t> grouped;
  for (const auto& candidate : input.abilities) {
    CheckCancellation(token);
    const auto identifier = Normalize(candidate.identifier);
    if (identifier.empty() || candidate.reason.empty()) throw std::invalid_argument("ability identity and reason must be nonempty");
    if (candidate.support != ConfigurationSupport::supported && candidate.support != ConfigurationSupport::partial && candidate.support != ConfigurationSupport::unsupported) {
      throw std::invalid_argument("unknown ability support status");
    }
    const auto reconciled = ReconcileConfigurationRepository({ConfigurationEffectSource::ability, identifier, identifier,
        candidate.reason, true, false, input.factory, input.repository_mode});
    const auto repository_support = reconciled.promoted_status == ConfigurationAdmissionStatus::supported ? ConfigurationSupport::supported : candidate.support;
    if (!requested.empty() && !requested.contains(identifier)) {
      coverage.push_back({ConfigurationEffectSource::ability, {identifier, repository_support, false, "The ability is legal but excluded by the command candidate pool.", std::nullopt}});
      continue;
    }
    if (repository_support != ConfigurationSupport::supported) {
      coverage.push_back({ConfigurationEffectSource::ability, {identifier, repository_support, false, reconciled.repository_reason, std::nullopt}});
      continue;
    }
    const auto& effect = reconciled.coverage;
    const auto support = effect.status == ConfigurationEffectStatus::supported ? ConfigurationSupport::supported
        : effect.status == ConfigurationEffectStatus::partial ? ConfigurationSupport::partial : ConfigurationSupport::unsupported;
    const bool included = effect.status == ConfigurationEffectStatus::supported;
    coverage.push_back({ConfigurationEffectSource::ability, {identifier, support, included, effect.reason, effect.status}});
    if (included) AppendEffect(values, grouped, effect.identifier);
  }
  return values;
}
/// @param input 单侧受控道具候选；@param coverage 输出完整覆盖；@param token 共享取消。
/// @return 规范化排序后的显式受控集合，不从游戏全道具表扩张。
std::vector<EffectOption> Items(const ConfigurationPokemonInput& input,
                               std::vector<ConfigurationCoverage>& coverage, const CancellationToken& token) {
  if (input.items.empty()) throw std::invalid_argument("item candidates must not be empty");
  std::vector<std::optional<std::string>> candidates;
  for (const auto& value : input.items) {
    auto normalized = value ? std::optional{Normalize(*value)} : std::nullopt;
    if (normalized && normalized->empty()) throw std::invalid_argument("item identifier must be nonblank or null");
    candidates.push_back(std::move(normalized));
  }
  std::ranges::sort(candidates);
  if (std::ranges::adjacent_find(candidates) != candidates.end()) throw std::invalid_argument("item candidates must be unique after normalization");
  std::vector<EffectOption> values;
  std::map<std::string, std::size_t> grouped;
  for (const auto& candidate : candidates) {
    CheckCancellation(token);
    const auto effect = DescribeConfigurationEffect(ConfigurationEffectSource::item, candidate, input.factory);
    const bool included = (!candidate && effect.status == ConfigurationEffectStatus::no_effect) || effect.status == ConfigurationEffectStatus::supported;
    const auto support = included ? ConfigurationSupport::supported : effect.status == ConfigurationEffectStatus::partial
        ? ConfigurationSupport::partial : ConfigurationSupport::unsupported;
    coverage.push_back({ConfigurationEffectSource::item, {effect.identifier, support, included, effect.reason, effect.status}});
    if (included) AppendEffect(values, grouped, effect.identifier);
  }
  return values;
}
} // namespace

ConfigurationPokemonSpace GeneratePokemonConfigurationSpace(const ConfigurationPokemonInput& input,
                                                             CancellationToken cancellation) {
  CheckCancellation(cancellation);
  if (input.ruleset_id != "pokemon-champion") throw UnsupportedRule("unsupported configuration ruleset");
  if (input.version_group_id <= 0 || input.pokemon_id <= 0 || input.name.empty() || input.max_raw_configurations == 0) {
    throw std::invalid_argument("configuration identity and budget must be positive");
  }
  std::set<PokemonType> types;
  for (const auto type : input.types) {
    if (static_cast<int>(type) < 1 || static_cast<int>(type) > 18 || !types.insert(type).second) throw std::invalid_argument("configuration types must be valid and unique");
  }
  if (types.empty() || types.size() > 2 || input.moves.candidates.empty() || input.abilities.empty()) {
    throw std::invalid_argument("configuration types and move and ability candidates must not be empty");
  }
  auto move_input = input.moves;
  if (input.repository_mode == ConfigurationRepositoryMode::factory_reconciled) for (auto& candidate : move_input.candidates) {
    CheckCancellation(cancellation);
    if (candidate.support != ConfigurationSupport::supported && candidate.support != ConfigurationSupport::partial && candidate.support != ConfigurationSupport::unsupported)
      throw std::invalid_argument("unknown repository move support status");
    const bool executable = candidate.move.has_value();
    const bool allow_no_effect = executable && candidate.move->View().move.category != DamageCategory::status;
    auto reconciled = ReconcileConfigurationRepository({ConfigurationEffectSource::move, candidate.effect_identifier, candidate.identifier,
        candidate.reason, executable, allow_no_effect, input.factory, input.repository_mode});
    if (reconciled.promoted_status == ConfigurationAdmissionStatus::supported) candidate.support = ConfigurationSupport::supported;
    candidate.reason = std::move(reconciled.repository_reason);
  }
  const auto moves = detail::EnumerateConfigurationMovesWithFactory(move_input, input.factory, cancellation);
  const auto stats = EnumerateConfigurationStats(input.stats, cancellation);
  ConfigurationPokemonSpace result;
  for (const auto& record : moves.coverage) result.coverage.push_back({ConfigurationEffectSource::move, record});
  const auto abilities = Abilities(input, result.coverage, cancellation);
  const auto items = Items(input, result.coverage, cancellation);
  // 原生成器先扩展全部维度，再统一检查空维度；保持错误与预算的执行顺序。
  if (moves.classes.empty()) EmptyDimension(input, ConfigurationEffectSource::move);
  if (abilities.empty()) EmptyDimension(input, ConfigurationEffectSource::ability);
  if (items.empty()) EmptyDimension(input, ConfigurationEffectSource::item);
  /// @param values 已归并的完整effect值；@return 归并前成员总量，不以类数量替代。
  const auto count = [](const std::vector<EffectOption>& values) {
    Integer total{0};
    for (const auto& value : values) total += value.members;
    return total;
  };
  result.raw_configuration_count = moves.raw_combination_count * stats.raw_profile_count * count(abilities) * count(items);
  if (result.raw_configuration_count > input.max_raw_configurations) throw std::length_error("configuration enumeration exceeds max_raw_configurations");
  std::map<std::string, std::size_t> grouped;
  for (const auto& move : moves.classes) for (const auto& stat : stats.classes) for (const auto& ability : abilities) for (const auto& item : items) {
    CheckCancellation(cancellation);
    auto key = OrderKey(input, move, stat, ability.identifier, item.identifier);
    const Integer members = move.member_count * stat.member_count * ability.members * item.members;
    const auto [entry, inserted] = grouped.emplace(key, result.classes.size());
    if (inserted) result.classes.push_back({move, stat, ability.identifier, item.identifier, members, std::move(key)});
    else result.classes[entry->second].member_count += members;
  }
  std::ranges::sort(result.classes, {}, &ConfigurationPokemonClass::order_key);
  Integer actual_count{0};
  for (const auto& value : result.classes) actual_count += value.member_count;
  if (actual_count != result.raw_configuration_count) throw std::logic_error("configuration members do not cover the raw space");
  return result;
}

ConfigurationSpace GenerateConfigurationSpace(const ConfigurationPokemonInput& attacker, const ConfigurationPokemonInput& defender,
                                               ConfigurationWeightAssumption assumption, std::size_t max_raw_pairs,
                                               CancellationToken cancellation) {
  if (attacker.ruleset_id != defender.ruleset_id || attacker.version_group_id != defender.version_group_id) {
    throw std::invalid_argument("configuration sides must share the same ruleset and version group");
  }
  if (max_raw_pairs == 0) throw std::invalid_argument("max_raw_configuration_pairs must be positive");
  if (assumption != ConfigurationWeightAssumption::uniform_raw_configuration && assumption != ConfigurationWeightAssumption::uniform_equivalence_class) {
    throw std::invalid_argument("unknown configuration weight assumption");
  }
  auto first = GeneratePokemonConfigurationSpace(attacker, cancellation);
  auto second = GeneratePokemonConfigurationSpace(defender, cancellation);
  Integer raw_pairs = first.raw_configuration_count * second.raw_configuration_count;
  if (raw_pairs > max_raw_pairs) throw std::length_error("configuration enumeration exceeds max_raw_configuration_pairs");
  const Integer unique_pairs = Integer{first.classes.size()} * second.classes.size();
  std::vector<ConfigurationPairClass> pairs;
  Rational total_weight{0};
  Integer total_members{0};
  for (std::size_t attacker_index = 0; attacker_index < first.classes.size(); ++attacker_index) {
    for (std::size_t defender_index = 0; defender_index < second.classes.size(); ++defender_index) {
      CheckCancellation(cancellation);
      const Integer members = first.classes[attacker_index].member_count * second.classes[defender_index].member_count;
      Rational weight = assumption == ConfigurationWeightAssumption::uniform_raw_configuration
          ? Rational{members, raw_pairs} : Rational{Integer{1}, unique_pairs};
      total_weight += weight;
      total_members += members;
      pairs.push_back({attacker_index, defender_index, members, std::move(weight)});
    }
  }
  if (total_members != raw_pairs || total_weight != Rational{1}) throw std::logic_error("configuration pair members and weights do not cover the raw space");
  return {std::move(first), std::move(second), std::move(pairs), std::move(raw_pairs)};
}
} // namespace pbi
