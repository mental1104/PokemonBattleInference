#pragma once
#include "pbi/damage.hpp"
#include <optional>
#include <string>
#include <variant>
#include <vector>

namespace pbi {
/// 主要异常的有限类型；状态本身使用 variant，计数不能附在错误的种类上。
enum class MajorStatusKind { sleep, paralysis, burn, freeze, poison, bad_poison };
/// 临时状态种类；同种类在 CombatantStatus 中最多一份。
enum class VolatileStatusKind { confusion, infatuation, flinch };
/// 睡眠计数快照，进入 CombatantStatus 时检查非负。
struct SleepStatus {
  std::int64_t turns_asleep = 0;
  /// @param other 只读同类状态；@return 计数是否相同。
  bool operator==(const SleepStatus& other) const = default;
};
/// 麻痹快照，无额外运行时字段。
struct ParalysisStatus {
  /// @param other 只读同类标记；@return 同种类标记恒相等。
  bool operator==(const ParalysisStatus& other) const = default;
};
/// 灼伤快照，无额外运行时字段。
struct BurnStatus {
  /// @param other 只读同类标记；@return 同种类标记恒相等。
  bool operator==(const BurnStatus& other) const = default;
};
/// 冰冻快照，无额外运行时字段。
struct FreezeStatus {
  /// @param other 只读同类标记；@return 同种类标记恒相等。
  bool operator==(const FreezeStatus& other) const = default;
};
/// 普通中毒快照，无额外运行时字段。
struct PoisonStatus {
  /// @param other 只读同类标记；@return 同种类标记恒相等。
  bool operator==(const PoisonStatus& other) const = default;
};
/// 剧毒计数快照，进入 CombatantStatus 时检查至少为 1。
struct BadPoisonStatus {
  std::int64_t toxic_counter = 1;
  /// @param other 只读同类状态；@return 剧毒计数是否相同。
  bool operator==(const BadPoisonStatus& other) const = default;
};
/// 混乱剩余计数；null 表示旧模型尚未给定时长。
struct ConfusionStatus {
  std::optional<std::int64_t> turns_remaining;
  /// @param other 只读同类状态；@return 可空计数是否相同。
  bool operator==(const ConfusionStatus& other) const = default;
};
/// 迷恋来源；null 和空字符串在原状态键中不同，保留其区别。
struct InfatuationStatus {
  std::optional<std::string> source_id;
  /// @param other 只读同类状态；@return 可空来源是否相同。
  bool operator==(const InfatuationStatus& other) const = default;
};
/// 当前回合的畏缩标记，消费/回合清理由对应执行阶段负责。
struct FlinchStatus {
  /// @param other 只读同类标记；@return 同种类标记恒相等。
  bool operator==(const FlinchStatus& other) const = default;
};
using MajorStatus = std::variant<SleepStatus, ParalysisStatus, BurnStatus, FreezeStatus, PoisonStatus, BadPoisonStatus>;
using VolatileStatus = std::variant<ConfusionStatus, InfatuationStatus, FlinchStatus>;

/// 不可变且已验证的一方状态集合；返回 const 视图，更新始终创建新快照。
class CombatantStatus {
public:
  /// @param major 转移拥有的可空主状态；@param volatile_statuses 转移拥有的临时状态。
  /// 相同值去重，种类重复但计数/来源不同则抛 invalid_argument，沿用 frozenset 语义。
  explicit CombatantStatus(std::optional<MajorStatus> major = std::nullopt,
                           std::vector<VolatileStatus> volatile_statuses = {});
  /// @return 由本对象拥有的只读主状态；引用仅在对象生命周期内有效。
  [[nodiscard]] const std::optional<MajorStatus>& Major() const noexcept { return major_; }
  /// @return 按种类排序的只读临时状态；不允许外部修改集合。
  [[nodiscard]] const std::vector<VolatileStatus>& Volatile() const noexcept { return volatile_; }
  /// @param kind 主要状态种类；@return 当前是否属于该种类，未知枚举抛 invalid_argument。
  [[nodiscard]] bool Has(MajorStatusKind kind) const;
  /// @param kind 临时状态种类；@return 当前是否拥有该种类，未知枚举抛 invalid_argument。
  [[nodiscard]] bool Has(VolatileStatusKind kind) const;
  /// @param status 转移拥有的新主状态/null；@return 验证后的新快照，不修改本对象。
  [[nodiscard]] CombatantStatus WithMajor(std::optional<MajorStatus> status) const;
  /// @param status 新的临时状态；@return 替换同种类后的新快照。
  [[nodiscard]] CombatantStatus AddVolatile(VolatileStatus status) const;
  /// @param kind 要清除的种类；@return 其他状态完整保留的新快照。
  [[nodiscard]] CombatantStatus ClearVolatile(VolatileStatusKind kind) const;
  /// @return 清空全部临时状态的新快照，保留主状态。
  [[nodiscard]] CombatantStatus ClearVolatile() const;
  /// @param other 只读状态快照；@return 全部规范值是否相同，不依赖原输入顺序。
  bool operator==(const CombatantStatus& other) const = default;
private:
  std::optional<MajorStatus> major_;
  std::vector<VolatileStatus> volatile_;
};

/// @param generation 原兼容代际 1…9；@return 原 profile 的精确麻痹速度倍率。
[[nodiscard]] Rational ParalysisSpeedForGeneration(std::int32_t generation);
/// @param speed 非负基础速度；@param status 只读已验证状态；@param multiplier 精确非负策略倍率。
/// @return 向下取整的新速度，允许为零；输出 int64 越界抛 overflow_error。
[[nodiscard]] std::int64_t ApplyParalysisSpeed(std::int64_t speed, const CombatantStatus& status, const Rational& multiplier);
/// @param status 只读状态；@param category 招式分类；@param policy_multiplier 精确非负灼伤策略倍率。
/// @return 灼伤物理招式的策略倍率，其他为 1，不重复实现直接伤害链。
[[nodiscard]] Rational BurnPhysicalMultiplier(const CombatantStatus& status, DamageCategory category, const Rational& policy_multiplier);
/// @param base 只读精确基础倍率；@param status 只读状态；@param category 招式分类；@param policy_multiplier 灼伤策略。
/// @return 原基础倍率乘以灼伤修正的精确新值。
[[nodiscard]] Rational ApplyBurnDamageMultiplier(const Rational& base, const CombatantStatus& status,
                                                DamageCategory category, const Rational& policy_multiplier);
/// @param status 只读状态；@return 按旧切换清理合同仅清除混乱/迷恋，保留主状态和畏缩。
[[nodiscard]] CombatantStatus ClearStatusOnSwitchOut(const CombatantStatus& status);
} // namespace pbi
