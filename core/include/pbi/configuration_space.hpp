#pragma once

#include "pbi/configuration_moves.hpp"
#include "pbi/configuration_stats.hpp"

namespace pbi {
/// 合法特性候选的repository基础覆盖，不意味着当前effect已完整实现。
struct ConfigurationAbilityCandidate {
  std::string identifier;
  ConfigurationSupport support = ConfigurationSupport::supported;
  std::string reason = "Repository projection marks this ability as supported.";
};
/// 标准四维单侧候选生成输入；知识由外层读取，过滤与枚举均在Core执行。
struct ConfigurationPokemonInput {
  std::string ruleset_id = "pokemon-champion";
  std::int64_t version_group_id = 25;
  std::int64_t pokemon_id;
  std::string name;
  std::vector<PokemonType> types;
  bool can_evolve = false;
  ConfigurationMoveInput moves;
  ConfigurationStatInput stats;
  std::vector<ConfigurationAbilityCandidate> abilities;
  std::vector<std::string> requested_abilities;
  std::vector<std::optional<std::string>> items{std::nullopt, "choice-band"};
  std::size_t max_raw_configurations = 100000;
};
/// 当前标准四维的完整代表；维度计数保留来源，但不参与行为相等性。
struct ConfigurationPokemonClass {
  ConfigurationMoveClass moves;
  ConfigurationStatClass stats;
  std::string ability;
  std::string item;
  Integer member_count;
  std::string order_key;
};
/// 带维度归属的完整候选覆盖，包含命令排除和不支持候选。
struct ConfigurationCoverage {
  ConfigurationEffectSource dimension;
  ConfigurationCandidateCoverage candidate;
};
/// 单侧空间按原repr行为键排序，精确保存归并前原始总量。
struct ConfigurationPokemonSpace {
  std::vector<ConfigurationPokemonClass> classes;
  std::vector<ConfigurationCoverage> coverage;
  Integer raw_configuration_count{0};
};
/// 配置权重只代表覆盖假设，不推定玩家实际使用率。
enum class ConfigurationWeightAssumption { uniform_raw_configuration, uniform_equivalence_class };
/// 一对已排序单侧类索引和精确成员/权重，引用所属ConfigurationSpace的拥有值。
struct ConfigurationPairClass {
  std::size_t attacker_class;
  std::size_t defender_class;
  Integer member_count;
  Rational weight;
};
/// 完整标准四维双侧生成结果，权重和原始成员数均无损守恒。
struct ConfigurationSpace {
  ConfigurationPokemonSpace attacker;
  ConfigurationPokemonSpace defender;
  std::vector<ConfigurationPairClass> pairs;
  Integer raw_pair_count;
};
/// @param input 只读标准四维完整候选；@param cancellation 可共享取消令牌。
/// @return 完整合法空间；任一维度为空、预算超限或取消均整次失败。
[[nodiscard]] ConfigurationPokemonSpace GeneratePokemonConfigurationSpace(
    const ConfigurationPokemonInput& input, CancellationToken cancellation = {});
/// @param attacker 攻击侧完整候选；@param defender 防守侧完整候选。
/// @param assumption 原始成员或等价类均匀覆盖假设；@param max_raw_pairs 原始配置对预算。
/// @param cancellation 两侧和配对共用的取消令牌。
/// @return 完整配对分区，sum(member_count)==raw_pair_count且sum(weight)==1。
[[nodiscard]] ConfigurationSpace GenerateConfigurationSpace(
    const ConfigurationPokemonInput& attacker, const ConfigurationPokemonInput& defender,
    ConfigurationWeightAssumption assumption = ConfigurationWeightAssumption::uniform_raw_configuration,
    std::size_t max_raw_pairs = 1000000, CancellationToken cancellation = {});
} // namespace pbi
