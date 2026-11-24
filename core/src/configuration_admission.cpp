#include "pbi/configuration_admission.hpp"
#include <algorithm>

namespace pbi {
ConfigurationAdmission DescribeConfigurationAdmission(const ConfigurationAdmissionInput& input) {
  if (input.mechanism_identifier.empty() || input.repository_reason.empty()) throw std::invalid_argument("admission identity and repository reason must be nonempty");
  auto coverage = DescribeConfigurationEffect(input.source, input.effect_identifier, input.factory);
  if (input.repository_mode != ConfigurationRepositoryMode::raw && input.repository_mode != ConfigurationRepositoryMode::factory_reconciled) {
    throw std::invalid_argument("unknown configuration repository mode");
  }
  auto repository_reason = input.repository_reason;
  if (input.repository_mode == ConfigurationRepositoryMode::factory_reconciled) {
    const bool supported = coverage.status == ConfigurationEffectStatus::supported;
    const bool no_effect = coverage.status == ConfigurationEffectStatus::no_effect;
    const bool promoted = input.source == ConfigurationEffectSource::move
        ? input.base_executable && (supported || (input.allow_no_effect && !input.effect_identifier && no_effect))
        : input.source == ConfigurationEffectSource::ability ? supported : supported || (no_effect && !input.effect_identifier);
    if (promoted) repository_reason += " Factory reconciliation: " + coverage.reason;
  }
  std::vector<std::string> missing;
  for (const auto& value : coverage.missing_capabilities) {
    if (std::ranges::find(missing, value) == missing.end()) missing.push_back(value);
  }
  ConfigurationAdmissionStatus status;
  // 原strict边界先看基础可执行性，再检查缺失子能力；overall SUPPORTED不能遮住占位缺口。
  if (!input.base_executable) status = ConfigurationAdmissionStatus::unsupported;
  else if (!missing.empty()) status = ConfigurationAdmissionStatus::partial;
  else if (coverage.status == ConfigurationEffectStatus::supported) status = ConfigurationAdmissionStatus::supported;
  else if (coverage.status == ConfigurationEffectStatus::no_effect && input.allow_no_effect) status = ConfigurationAdmissionStatus::no_effect;
  else if (coverage.status == ConfigurationEffectStatus::partial) status = ConfigurationAdmissionStatus::partial;
  else status = ConfigurationAdmissionStatus::unsupported;
  if (status == ConfigurationAdmissionStatus::supported || status == ConfigurationAdmissionStatus::no_effect) missing.clear();
  else if (missing.empty()) missing.push_back(coverage.identifier == "none" ? input.mechanism_identifier : coverage.identifier);
  auto reason = repository_reason + " Current factory coverage: " + coverage.reason;
  return {std::move(coverage), status, std::move(reason), std::move(missing)};
}
} // namespace pbi
