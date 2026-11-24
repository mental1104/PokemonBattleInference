#pragma once

#include "pbi/battle_graph.hpp"

namespace pbi {
/// 原查询侧别作用于事件主体、目标或任意位置；不解析事件展示文案。
enum class EventSideRole { any, actor, target };
/// 回合范围限制任意一次命中或首次命中，整条历史的次数限制保持不变。
enum class EventOccurrenceMode { any, first };
/// 正回合闭区间，空边界表示对应方向无限制。
struct EventTurnRange {
  std::optional<Integer> start;
  std::optional<Integer> end;
  /// @param other 同一业务范围；@return 完整值相等。
  bool operator==(const EventTurnRange& other) const = default;
};
/// 结构化事件的AND过滤器，业务字段约束不会错误匹配普通随机事件。
struct EventPredicate {
  std::vector<BattleEventKind> battle_event_kinds;
  std::vector<TransitionEventType> transition_event_types;
  std::optional<BattleSide> side;
  EventSideRole side_role = EventSideRole::any;
  std::optional<std::int64_t> move_id;
  std::optional<std::string> effect_identifier;
  std::optional<std::string> event_id;
  std::optional<std::string> outcome_id;
  /// @param event 完整类型化路径事件；@return 是否同时满足全部非空约束。
  [[nodiscard]] bool Matches(const PathEvent& event) const;
  /// @param other 同一业务过滤器；@return 全部字段及集合顺序一致。
  bool operator==(const EventPredicate& other) const = default;
};
/// 原有限分布和完整历史查询，产品图计数/回合使用任意精度饱和桶。
struct EventQuery {
  EventPredicate predicate;
  EventOccurrenceMode occurrence_mode = EventOccurrenceMode::any;
  std::optional<EventTurnRange> turn_range;
  Integer min_occurrences = 1;
  std::optional<Integer> max_occurrences;
  std::size_t distribution_count_limit = 8;
  std::size_t distribution_turn_limit = 16;
  std::size_t max_key_event_summaries = 32;
  /// @param other 同一完整查询；@return 全部字段一致。
  bool operator==(const EventQuery& other) const = default;
};
/// 已完成图的分析投影，事件摘要与拓扑边逐一对应，不修改战斗StateKey。
struct EventAnalysisGraph {
  ProbabilityGraph topology;
  std::vector<EventSummary> edge_events;
  Integer root_turn_number = 1;
};
/// 一次独立推演运行身份和拥有图；revision/run ID由执行端提供，不由概率伪造。
struct EventAnalysisArtifact {
  std::string calculation_revision;
  std::string inference_run_id;
  EventAnalysisGraph graph;
};
/// 条件质量为零时value为空，不能显示为零条件胜率。
struct EventConditionalProbability {
  std::optional<Rational> value;
  Rational condition_probability;
};
/// 完整概率分布的一桶；包括原never/overflow桶且总和必须精确为一。
struct EventDistributionBucket { std::string key; Rational probability; };
/// 元数据覆盖是边/路径组数量，不是随机历史概率。
struct EventPathCoverage {
  std::size_t total_edges;
  std::size_t matching_edges;
  std::size_t total_path_groups;
  std::size_t matching_path_groups;
};
/// 命中事件的稳定业务身份，不把trace、数值或对象地址当事件key。
struct EventKeySummary {
  TransitionEventType event_type;
  std::optional<BattleEventKind> battle_event_kind;
  std::optional<BattleSide> actor;
  std::optional<BattleSide> target;
  std::optional<std::int64_t> move_id;
  std::optional<std::string> effect_identifier;
  std::string event_id;
  std::string outcome_id;
  std::size_t path_group_count;
};
/// 实际原图/产品图规模及精确求解次数，不推测未执行成本。
struct EventAnalysisCost {
  std::size_t original_nodes;
  std::size_t original_edges;
  std::size_t product_nodes;
  std::size_t product_edges;
  std::size_t exact_solver_runs;
};
/// 单图真实产品自动机分析结果，所有概率使用同一精确有理数求解器。
struct EventAnalysisResult {
  std::string calculation_revision;
  std::string inference_run_id;
  BattleSide observer;
  EventQuery query;
  Rational baseline_win;
  Rational baseline_loss;
  Rational baseline_draw;
  Rational event_probability;
  Rational event_win_joint_probability;
  EventConditionalProbability win_given_event;
  EventConditionalProbability win_given_not_event;
  std::vector<EventDistributionBucket> first_occurrence_distribution;
  std::vector<EventDistributionBucket> occurrence_count_distribution;
  EventPathCoverage path_group_coverage;
  std::vector<EventKeySummary> key_events;
  bool original_probability_preserved;
  EventAnalysisCost cost;
};
/// @param graph 真实Core构建的完整图；@return 拓扑/替代路径条件权重的拥有投影。
[[nodiscard]] EventAnalysisGraph ProjectEventAnalysisGraph(const BattleGraph& graph);
/// @param artifact 完整已完成独立图；@param query 原次数/回合/过滤约束。
/// @param observer 胜率观察侧；@param cancellation 同源取消。
/// @return 原事件产品自动机的全部联合/条件概率、分布、覆盖及成本。
/// 图不完整/精确求解失败/取消时整体抛异常，不将截断当平局或发布部分结果。
[[nodiscard]] EventAnalysisResult AnalyzeBattleEvents(const EventAnalysisArtifact& artifact, const EventQuery& query,
    BattleSide observer = BattleSide::attacker, CancellationToken cancellation = {});
} // namespace pbi
