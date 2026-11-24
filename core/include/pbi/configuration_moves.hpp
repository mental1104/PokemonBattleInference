#pragma once

#include "pbi/cancellation.hpp"
#include "pbi/state.hpp"

namespace pbi {
/// Repository 的基础可执行性与当前工厂的机制覆盖必须分别保留。
enum class ConfigurationSupport { supported, partial, unsupported };
/// 与原 effect descriptor 同义的完整、部分、缺失和显式无附加效果。
enum class ConfigurationEffectStatus { supported, partial, unsupported, no_effect };
/// 当前规则集的固定 effect 产品类型，不使用可变全局注册表。
enum class ConfigurationEffectSource { move, ability, item };
/// 通用标准工厂与旧HTTP推演的透明中性占位composition显式分开。
enum class ConfigurationEffectFactory { standard, transparent_inference };
/// 原工厂的可执行覆盖快照；缺失子能力保留为严格任务准入的独立依据。
struct ConfigurationEffectCoverage {
  std::string identifier;
  ConfigurationEffectStatus status;
  std::string reason;
  std::vector<std::string> missing_capabilities;
};
/// 一条原合法候选的完整纳入/排除记录，命令排除不冒充机制不支持。
struct ConfigurationCandidateCoverage {
  std::string identifier;
  ConfigurationSupport support;
  bool included;
  std::string reason;
  std::optional<ConfigurationEffectStatus> factory_status;
};
/// 已完成 version-aware 合法性读取的招式候选；不可执行候选允许不携带 MoveSpec。
struct ConfigurationMoveCandidate {
  std::int64_t move_id;
  std::string identifier;
  std::optional<MoveSpec> move;
  std::optional<std::string> effect_identifier;
  ConfigurationSupport support = ConfigurationSupport::supported;
  std::string reason = "Repository projection marks this move candidate as supported.";
};
/// 指定允许的合法 ID、显式槽数量或默认四招规范及原始组合保护。
struct ConfigurationMoveInput {
  std::vector<ConfigurationMoveCandidate> candidates;
  std::vector<std::int64_t> requested_ids;
  std::vector<std::size_t> slot_counts;
  std::size_t max_raw_combinations = 10000;
};
/// 配置招式保留原 MoveSpec effect 与 provider 选择 effect 两个不同事实。
struct ConfigurationMove {
  MoveSpec move;
  std::optional<std::string> effect_identifier;
  /// @param other 只读配置招式；@return 排除展示名的原始行为是否相同。
  bool operator==(const ConfigurationMove& other) const = default;
};
/// 一至四个唯一招式 ID 的无序规范组合；成员数包含候选行为去重前的乘数。
struct ConfigurationMoveClass {
  std::vector<ConfigurationMove> moves;
  Integer member_count{1};
};
/// 无损组合分区和所有合法候选覆盖记录，空 values 由上层维度校验统一拒绝。
struct ConfigurationMoveSpace {
  std::vector<ConfigurationMoveClass> classes;
  std::vector<ConfigurationCandidateCoverage> coverage;
  Integer raw_combination_count{0};
};
/// @param identifier 拥有的可空ASCII机制标识；@return 原strip/lower/替换规范形式，空为null。
/// 非ASCII标识明确unsupported，不猜测Unicode大小写映射。
[[nodiscard]] std::optional<std::string> NormalizeConfigurationEffectIdentifier(std::optional<std::string> identifier);
/// @param source 有限产品来源；@param identifier 已读取机制标识，null 表示明确未配置。
/// @return 当前 PokemonChampion 工厂覆盖，未知非空标识保持 unsupported。
[[nodiscard]] ConfigurationEffectCoverage DescribeConfigurationEffect(
    ConfigurationEffectSource source, std::optional<std::string> identifier,
    ConfigurationEffectFactory factory = ConfigurationEffectFactory::standard);
/// @param input 只读合法候选池和枚举边界；@param cancellation 可空共享取消令牌。
/// @return 真实过滤、候选归并、唯一 ID 组合和精确成员数；超预算整次失败。
[[nodiscard]] ConfigurationMoveSpace EnumerateConfigurationMoves(
    const ConfigurationMoveInput& input, CancellationToken cancellation = {});
/// @param move 只读配置招式；@return 与原 repr(behavior_signature) 相同的排序键。
/// 仅用于保留旧类索引顺序，不用不稳定的 std::hash 值标识配置。
[[nodiscard]] std::string ConfigurationMoveOrderKey(const ConfigurationMove& move);
} // namespace pbi
