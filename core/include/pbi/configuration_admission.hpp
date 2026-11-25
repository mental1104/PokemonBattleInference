#pragma once

#include "pbi/configuration_moves.hpp"

namespace pbi {
/// 严格准入保留no_effect与真正supported的差别，两者均可选择。
enum class ConfigurationAdmissionStatus { supported, no_effect, partial, unsupported };
/// 原始repository与实际HTTP的factory对账装饰器显式分开，避免外层拼机制reason。
enum class ConfigurationRepositoryMode { raw, factory_reconciled };
/// 原候选profile与工厂产品的独立事实；repository三态不决定最终strict准入。
struct ConfigurationAdmissionInput {
  ConfigurationEffectSource source;
  std::optional<std::string> effect_identifier;
  std::string mechanism_identifier;
  std::string repository_reason;
  bool base_executable;
  bool allow_no_effect;
  ConfigurationEffectFactory factory = ConfigurationEffectFactory::transparent_inference;
  ConfigurationRepositoryMode repository_mode = ConfigurationRepositoryMode::raw;
};
/// 与原ListBattleCandidatePoolUseCase._admission相同的结果，包含完整工厂描述。
struct ConfigurationAdmission {
  ConfigurationEffectCoverage coverage;
  ConfigurationAdmissionStatus status;
  std::string reason;
  std::vector<std::string> missing_mechanism_identifiers;
  /// @return 仅supported/no_effect可进入strict任务；其他状态明确不可选择。
  [[nodiscard]] bool Selectable() const noexcept {
    return status == ConfigurationAdmissionStatus::supported || status == ConfigurationAdmissionStatus::no_effect;
  }
};
/// 原FactoryReconciled装饰器的独立结果；无promotion时保留调用者原repo状态，不冒充strict准入。
struct ConfigurationRepositoryReconciliation {
  ConfigurationEffectCoverage coverage;
  std::optional<ConfigurationAdmissionStatus> promoted_status;
  std::string repository_reason;
};
/// @param input 原候选基础可执行性、raw原因与明确factory/repository上下文。
/// @return 原factory提升事实与原完整理由；strict和普通provider共同复用，不在Go拼机制理由。
[[nodiscard]] ConfigurationRepositoryReconciliation ReconcileConfigurationRepository(const ConfigurationAdmissionInput& input);
/// @param input 原候选基础字段和真实composition选择，不从Go接收预先裁定的strict状态。
/// @return 透明占位子能力/partial/unknown/no_effect等完整准入，不修改候选或静默过滤。
[[nodiscard]] ConfigurationAdmission DescribeConfigurationAdmission(const ConfigurationAdmissionInput& input);
} // namespace pbi
