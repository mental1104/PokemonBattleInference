#pragma once

#include "pbi/actions.hpp"
#include "pbi/cancellation.hpp"

namespace pbi {
/// 原job-v1八个维度的有限模式；仅招式候选池参与枚举。
enum class JobDimensionMode { fixed, candidate_pool, disabled };
/// 原公开合同模式快照，非法扩展在纯Core边界拒绝。
struct JobDimensionModes {
  JobDimensionMode pokemon = JobDimensionMode::fixed;
  JobDimensionMode form = JobDimensionMode::fixed;
  JobDimensionMode level = JobDimensionMode::fixed;
  JobDimensionMode stats = JobDimensionMode::fixed;
  JobDimensionMode ability = JobDimensionMode::fixed;
  JobDimensionMode item = JobDimensionMode::fixed;
  JobDimensionMode moves = JobDimensionMode::candidate_pool;
  JobDimensionMode special_mechanics = JobDimensionMode::disabled;
};
/// 一侧固定身份，字符串保持原ASCII公开合同，不转写特性或preset标识。
struct JobFixedPokemon {
  std::int64_t pokemon_id;
  std::optional<std::int64_t> form_id;
  std::int32_t level;
  std::string stat_profile_id;
  std::string ability_identifier;
  std::optional<std::string> item_identifier;
};
/// 已完成独立严格准入的一侧固定身份及原唯一ID池，迭代器从不再过滤/归并。
struct JobMovePoolSelection {
  JobFixedPokemon fixed;
  std::vector<std::int64_t> candidate_move_ids;
};
/// 原job-v1完整轴与策略，canonical配置身份按原合同不包含玩家策略。
struct JobMovePoolInput {
  std::string ruleset_id;
  std::int64_t version_group_id;
  std::string calculation_revision;
  JobMovePoolSelection attacker;
  JobMovePoolSelection defender;
  JobDimensionModes dimensions;
  ActionPolicy attacker_policy = ActionPolicy::uniform_random;
  ActionPolicy defender_policy = ActionPolicy::uniform_random;
  std::string contract_version = "one-on-one-move-pool.v1";
};
/// 真正具体case的原canonical可读pairID、两侧SHA-256身份与排序技能组。
struct JobMovePoolCase {
  std::size_t ordinal;
  std::string configuration_pair_id;
  std::string attacker_configuration_id;
  std::string defender_configuration_id;
  std::vector<std::int64_t> attacker_move_ids;
  std::vector<std::int64_t> defender_move_ids;
  Rational configuration_weight;
};
/// 精确复现原配置池迭代，不持有能力等价类、战斗状态或44100个case的缓存。
class JobMovePool {
public:
  /// @param input 转移拥有的原合同输入；校验ASCII身份、固定维度和双方总候选<=20。
  /// 严格机制准入属于独立DescribeConfigurationAdmission/任务提交边界，必须先整池验证。
  explicit JobMovePool(JobMovePoolInput input);
  /// @return 已排序规范化输入的只读借用，生命周期不超过本对象。
  [[nodiscard]] const JobMovePoolInput& View() const noexcept { return input_; }
  /// @return 攻击方原具体技能组数量；小于4招全池，否则C(n,4)。
  [[nodiscard]] std::size_t AttackerMoveSetCount() const noexcept { return attacker_count_; }
  /// @return 防守方原具体技能组数量，完全保留原候选分母。
  [[nodiscard]] std::size_t DefenderMoveSetCount() const noexcept { return defender_count_; }
  /// @return 真正具体case总数，10+10时为44100，不以等价代表数替换。
  [[nodiscard]] std::size_t CaseCount() const noexcept { return attacker_count_ * defender_count_; }
  /// @param ordinal 原双重combinations迭代的零基索引；@return 原canonical身份及精确1/总数。
  /// 越界明确失败，不返回首case或相邻case作为回退。
  [[nodiscard]] JobMovePoolCase CaseAt(std::size_t ordinal) const;
  /// @param offset 起始原索引；@param limit 最多生成多少具体case，不修改完整CaseCount。
  /// @param cancellation 可空共享令牌；@return 原顺序的有界页面，取消时整个页面失败。
  [[nodiscard]] std::vector<JobMovePoolCase> Page(std::size_t offset, std::size_t limit,
                                               CancellationToken cancellation = {}) const;
private:
  JobMovePoolInput input_;
  std::size_t attacker_count_;
  std::size_t defender_count_;
};
} // namespace pbi
