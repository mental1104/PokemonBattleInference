#include "pbi/event_analysis.hpp"
#include <algorithm>
#include <cctype>
#include <map>
#include <set>
#include <tuple>
#include <utility>

namespace pbi {
namespace {
/// @param stop 同源取消；取消整体失败，不发布未完成概率。
void CheckStop(CancellationToken stop) {
  if (stop.Requested()) throw std::runtime_error("battle event analysis cancelled");
}
/// @param value 身份文本；@return 是否非空且没有首尾ASCII空白。
bool Normalized(const std::string& value) {
  return !value.empty() && !std::isspace(static_cast<unsigned char>(value.front())) && !std::isspace(static_cast<unsigned char>(value.back()));
}
/// @param outcome 已验证图结果；@return 是否为原确定终局。
bool Terminal(GraphOutcome outcome) {
  return outcome == GraphOutcome::attacker_win || outcome == GraphOutcome::defender_win || outcome == GraphOutcome::draw;
}
/// @param event 已验证类型化事件；@return 原随机字段完整拥有值，业务事件通过真实Identity生成。
TransitionEventData Identity(const PathEvent& event) {
  if (const auto* business = std::get_if<BattleEvent>(&event)) return business->Identity().View();
  return std::get<TransitionEvent>(event).View();
}
/// @param query 完整原查询；非法枚举、重复类型、范围或非正分布限制整体拒绝。
void ValidateQuery(const EventQuery& query) {
  if (query.occurrence_mode != EventOccurrenceMode::any && query.occurrence_mode != EventOccurrenceMode::first)
    throw std::invalid_argument("unsupported event occurrence mode");
  if (query.predicate.side_role != EventSideRole::any && query.predicate.side_role != EventSideRole::actor && query.predicate.side_role != EventSideRole::target)
    throw std::invalid_argument("unsupported event side role");
  if (query.predicate.side && *query.predicate.side != BattleSide::attacker && *query.predicate.side != BattleSide::defender)
    throw std::invalid_argument("unsupported event observer side");
  std::set<BattleEventKind> kinds;
  for (const auto kind : query.predicate.battle_event_kinds) {
    static_cast<void>(BattleEventName(kind));
    if (!kinds.insert(kind).second) throw std::invalid_argument("battle event kinds cannot contain duplicates");
  }
  std::set<TransitionEventType> types;
  for (const auto type : query.predicate.transition_event_types) {
    if (type < TransitionEventType::hit_check || type > TransitionEventType::custom) throw std::invalid_argument("unsupported transition event type");
    if (!types.insert(type).second) throw std::invalid_argument("transition event types cannot contain duplicates");
  }
  if (query.predicate.move_id && *query.predicate.move_id <= 0) throw std::invalid_argument("event move ID must be positive");
  for (const auto* text : {&query.predicate.effect_identifier, &query.predicate.event_id, &query.predicate.outcome_id})
    if (*text && !Normalized(**text)) throw std::invalid_argument("event identifiers must be normalized non-empty text");
  if (query.min_occurrences < 0 || (query.max_occurrences && *query.max_occurrences < query.min_occurrences))
    throw std::invalid_argument("invalid event occurrence count range");
  if (query.distribution_count_limit == 0 || query.distribution_turn_limit == 0 || query.max_key_event_summaries == 0)
    throw std::invalid_argument("event distribution limits must be positive");
  if (query.turn_range) {
    const auto& range = *query.turn_range;
    if ((range.start && *range.start <= 0) || (range.end && *range.end <= 0) || (range.start && range.end && *range.start > *range.end))
      throw std::invalid_argument("invalid event turn range");
  }
}
/// 独立事件历史自动机状态，任意精度桶不改变原战斗StateKey或图节点身份。
struct Tracker {
  std::size_t original_node;
  Integer count;
  std::optional<Integer> first;
  bool matched_in_range;
  Integer next_turn;
  /// @param other 同一产品自动机内完整状态；@return 按全部历史字段的稳定严格排序。
  bool operator<(const Tracker& other) const {
    return std::tie(original_node, count, first, matched_in_range, next_turn) <
        std::tie(other.original_node, other.count, other.first, other.matched_in_range, other.next_turn);
  }
};
/// 已拥有产品拓扑与每节点分析历史，不保存借用或改写原图。
struct Product {
  ProbabilityGraph graph;
  std::vector<Tracker> trackers;
  Integer count_overflow;
  Integer turn_overflow;
};
/// @param turn 精确或饱和回合；@param range 原闭区间；@param overflow 大于所有有限边界的饱和桶。
/// @return 整个桶是否属于查询范围，不把饱和桶误作单一精确回合。
bool TurnInRange(const Integer& turn, const std::optional<EventTurnRange>& range, const Integer& overflow) {
  if (!range) return true;
  if (turn < overflow) return (!range->start || turn >= *range->start) && (!range->end || turn <= *range->end);
  if (range->end && *range->end < overflow) return false;
  return !range->start || *range->start <= overflow;
}
/// @param input 原完整图；@param query 原查询；@param stop 同源取消。
/// @return 每原边的每条替代事件路径分别扩展的有限精确产品图。
Product BuildProduct(const EventAnalysisGraph& input, const EventQuery& query, CancellationToken stop) {
  if (!input.topology.Truncations().empty() || std::ranges::any_of(input.topology.Nodes(), [](const auto& node) { return node.outcome == GraphOutcome::unknown; }))
    throw std::invalid_argument("event analysis requires a complete graph without unknown nodes");
  if (input.edge_events.size() != input.topology.Edges().size() || input.root_turn_number <= 0)
    throw std::invalid_argument("event graph metadata must match topology edges and a positive root turn");
  Integer count_overflow = std::max(Integer{query.distribution_count_limit}, query.min_occurrences);
  if (query.max_occurrences) count_overflow = std::max(count_overflow, *query.max_occurrences);
  ++count_overflow;
  Integer turn_overflow = std::max(Integer{query.distribution_turn_limit}, input.root_turn_number);
  if (query.turn_range) {
    if (query.turn_range->start) turn_overflow = std::max(turn_overflow, *query.turn_range->start);
    if (query.turn_range->end) turn_overflow = std::max(turn_overflow, *query.turn_range->end);
  }
  ++turn_overflow;
  std::vector<std::vector<std::size_t>> outgoing(input.topology.Nodes().size());
  for (std::size_t index = 0; index < input.topology.Edges().size(); ++index) outgoing[input.topology.Edges()[index].source.value].push_back(index);
  std::vector<Tracker> trackers{{input.topology.Root().value, 0, std::nullopt, false, std::min(input.root_turn_number, turn_overflow)}};
  std::map<Tracker, GraphNodeId> indices{{trackers.front(), {0}}};
  std::vector<ProbabilityNode> nodes{input.topology.Nodes()[trackers.front().original_node]};
  std::vector<ProbabilityEdge> edges;
  // 以拥有索引遍历BFS队列；内层push_back可能扩容，因此当前tracker必须复制。
  for (std::size_t source = 0; source < trackers.size(); ++source) {
    CheckStop(stop);
    const auto tracker = trackers[source];
    if (Terminal(nodes[source].outcome)) continue;
    for (const auto index : outgoing[tracker.original_node]) {
      const auto& edge = input.topology.Edges()[index];
      for (const auto& path : input.edge_events[index].Paths()) {
        CheckStop(stop);
        Integer matched = 0;
        for (const auto& event : path.events) if (query.predicate.Matches(event)) ++matched;
        const Integer incremented = tracker.count + matched;
        auto first = tracker.first;
        if (matched > 0 && !first) first = tracker.next_turn;
        const Integer next_turn = tracker.next_turn + 1;
        Tracker next{edge.target.value, std::min(incremented, count_overflow), std::move(first),
            tracker.matched_in_range || (matched > 0 && TurnInRange(tracker.next_turn, query.turn_range, turn_overflow)), std::min(next_turn, turn_overflow)};
        const auto [found, inserted] = indices.emplace(next, GraphNodeId{nodes.size()});
        if (inserted) {
          nodes.push_back(input.topology.Nodes()[next.original_node]);
          trackers.push_back(std::move(next));
        }
        edges.push_back({{source}, found->second, edge.probability * path.probability});
      }
    }
  }
  return {ProbabilityGraph{std::move(nodes), std::move(edges)}, std::move(trackers), std::move(count_overflow), std::move(turn_overflow)};
}
/// @param graph 完整拓扑；@param observer 观察方；@param stop 同源取消。
/// @return 完整拥有精确解；未完成/取消不回退零概率。
SolvedGraph RequireSolved(const ProbabilityGraph& graph, BattleSide observer, CancellationToken stop) {
  auto result = SolveGraph(graph, observer, std::nullopt, stop);
  if (const auto* solved = std::get_if<SolvedGraph>(&result)) return *solved;
  CheckStop(stop);
  throw std::invalid_argument("battle event analysis requires an exactly solved graph");
}
/// @param product 完整产品图；@param predicate 吸收/封闭历史属性；@param stop 同源取消。
/// @return 将所有吸收边界二分类后复用原SCC/精确方程求得的属性概率。
template<class Predicate> Rational Property(const Product& product, Predicate&& predicate, CancellationToken stop) {
  std::vector<bool> closed(product.graph.Nodes().size());
  for (const auto& component : AnalyzeComponents(product.graph, stop)) if (component.kind == ComponentKind::closed_cycle)
    for (const auto node : component.nodes) closed[node.value] = true;
  std::vector<ProbabilityNode> nodes(product.graph.Nodes().begin(), product.graph.Nodes().end());
  for (std::size_t index = 0; index < nodes.size(); ++index) {
    CheckStop(stop);
    if (Terminal(nodes[index].outcome) || closed[index]) nodes[index].outcome = predicate(product.trackers[index], nodes[index].outcome, closed[index])
        ? GraphOutcome::attacker_win : GraphOutcome::defender_win;
    else nodes[index].outcome = GraphOutcome::non_terminal;
  }
  const ProbabilityGraph binary{std::move(nodes), {product.graph.Edges().begin(), product.graph.Edges().end()}, product.graph.Root()};
  return RequireSolved(binary, BattleSide::attacker, stop).win;
}
/// @param tracker 一条吸收历史；@param query 完整查询；@param product 提供饱和边界。
/// @return 整条历史是否满足次数以及首次/任意回合范围，不只统计单边命中。
bool QuerySatisfied(const Tracker& tracker, const EventQuery& query, const Product& product) {
  if (tracker.count < query.min_occurrences) return false;
  if (query.max_occurrences && (tracker.count == product.count_overflow || tracker.count > *query.max_occurrences)) return false;
  if (!query.turn_range) return true;
  if (query.occurrence_mode == EventOccurrenceMode::any) return tracker.matched_in_range;
  return tracker.first && TurnInRange(*tracker.first, query.turn_range, product.turn_overflow);
}
/// @param name 原枚举稳定值；@return 原Python Enum str使用的大写下划线成员名。
std::string EnumMember(std::string_view name) {
  std::string result;
  for (const auto character : name) result.push_back(character == '-' ? '_' : static_cast<char>(std::toupper(static_cast<unsigned char>(character))));
  return result;
}
/// @param type 原随机类别；@return 原枚举成员名称，非法类别直接拒绝。
std::string TransitionName(TransitionEventType type) {
  constexpr std::array<std::string_view, 5> names{"HIT_CHECK", "DAMAGE_ROLL", "SPEED_TIE", "SECONDARY_EFFECT", "CUSTOM"};
  return std::string{names.at(static_cast<std::size_t>(type))};
}
/// @param side 可空事件位置；@return 与原排序str字段一致的表示。
std::string SideKey(std::optional<BattleSide> side) {
  if (!side) return "None";
  return *side == BattleSide::attacker ? "BattleSide.ATTACKER" : "BattleSide.DEFENDER";
}
/// @param event 已匹配事件；@return 原关键摘要键，不包含turn/value/numeric以保持同一业务身份。
EventKeySummary Summary(const PathEvent& event) {
  const auto identity = Identity(event);
  EventKeySummary result{identity.type, {}, {}, {}, {}, {}, identity.event_id, identity.outcome_id, 0};
  if (const auto* business = std::get_if<BattleEvent>(&event)) {
    const auto& value = business->View();
    result.battle_event_kind = value.kind; result.actor = value.actor; result.target = value.target;
    result.move_id = value.move_id; result.effect_identifier = value.source_identifier;
  }
  return result;
}
/// @param value 完整事件摘要；@return 原Python tuple(str(field))的精确顺序键。
auto SummaryKey(const EventKeySummary& value) {
  return std::array<std::string, 8>{"TransitionEventType." + TransitionName(value.event_type),
      value.battle_event_kind ? "BattleEventKind." + EnumMember(BattleEventName(*value.battle_event_kind)) : "None",
      SideKey(value.actor), SideKey(value.target), value.move_id ? std::to_string(*value.move_id) : "None",
      value.effect_identifier.value_or("None"), value.event_id, value.outcome_id};
}
/// @param value 原完整事件身份；@return 保留None与字面量"None"差异的类型化计数键。
auto SummaryIdentity(const EventKeySummary& value) {
  return std::tuple{value.event_type, value.battle_event_kind, value.actor, value.target, value.move_id,
      value.effect_identifier, value.event_id, value.outcome_id};
}
/// @param input 原完整图及事件路径；@param query 原过滤器和摘要上限；@param stop 同源取消。
/// @return 元数据覆盖与排序关键摘要；不将路径组数量误作随机概率。
std::pair<EventPathCoverage, std::vector<EventKeySummary>> Coverage(const EventAnalysisGraph& input, const EventQuery& query, CancellationToken stop) {
  EventPathCoverage coverage{input.topology.Edges().size(), 0, 0, 0};
  using IdentityKey = decltype(SummaryIdentity(std::declval<const EventKeySummary&>()));
  std::map<IdentityKey, EventKeySummary> summaries;
  for (const auto& edge : input.edge_events) {
    CheckStop(stop);
    bool matching_edge = false;
    for (const auto& path : edge.Paths()) {
      ++coverage.total_path_groups;
      std::vector<PathEvent> unique;
      for (const auto& event : path.events) if (query.predicate.Matches(event) && std::ranges::find(unique, event) == unique.end()) unique.push_back(event);
      if (unique.empty()) continue;
      ++coverage.matching_path_groups; matching_edge = true;
      // 原实现先按完整事件set去重，再按摘要key计数；同key不同数值仍可能在一组增加多次。
      for (const auto& event : unique) {
        auto summary = Summary(event);
        const auto [found, inserted] = summaries.try_emplace(SummaryIdentity(summary), std::move(summary));
        static_cast<void>(inserted);
        ++found->second.path_group_count;
      }
    }
    if (matching_edge) ++coverage.matching_edges;
  }
  std::vector<EventKeySummary> values;
  for (auto& [key, value] : summaries) { static_cast<void>(key); values.push_back(std::move(value)); }
  std::ranges::sort(values, [](const auto& first, const auto& second) {
    if (first.path_group_count != second.path_group_count) return first.path_group_count > second.path_group_count;
    return SummaryKey(first) < SummaryKey(second);
  });
  if (values.size() > query.max_key_event_summaries) values.resize(query.max_key_event_summaries);
  return {coverage, std::move(values)};
}
/// @param joint 联合概率；@param condition 条件事件概率；@return 零条件显式为空，正条件返回精确商。
EventConditionalProbability Conditional(const Rational& joint, const Rational& condition) {
  return {condition == Rational{0} ? std::nullopt : std::optional<Rational>{joint / condition}, condition};
}
} // namespace

bool EventPredicate::Matches(const PathEvent& event) const {
  const auto identity = Identity(event);
  if ((!transition_event_types.empty() && std::ranges::find(transition_event_types, identity.type) == transition_event_types.end()) ||
      (event_id && *event_id != identity.event_id) || (outcome_id && *outcome_id != identity.outcome_id)) return false;
  const auto* business = std::get_if<BattleEvent>(&event);
  if (!business) return battle_event_kinds.empty() && !side && !move_id && !effect_identifier;
  const auto& value = business->View();
  if ((!battle_event_kinds.empty() && std::ranges::find(battle_event_kinds, value.kind) == battle_event_kinds.end()) ||
      (move_id && value.move_id != move_id) || (effect_identifier && value.source_identifier != effect_identifier)) return false;
  if (!side) return true;
  if (side_role == EventSideRole::actor) return value.actor == side;
  if (side_role == EventSideRole::target) return value.target == side;
  return value.actor == side || value.target == side;
}

EventAnalysisGraph ProjectEventAnalysisGraph(const BattleGraph& graph) {
  std::vector<EventSummary> events;
  for (const auto& edge : graph.Edges()) events.push_back(edge.events);
  return {graph.Topology(), std::move(events), graph.Nodes().front().state.View().turn_number};
}

EventAnalysisResult AnalyzeBattleEvents(const EventAnalysisArtifact& artifact, const EventQuery& query, BattleSide observer, CancellationToken cancellation) {
  CheckStop(cancellation);
  if (!Normalized(artifact.calculation_revision) || !Normalized(artifact.inference_run_id)) throw std::invalid_argument("event artifact identities must be normalized");
  ValidateQuery(query);
  const auto baseline = RequireSolved(artifact.graph.topology, observer, cancellation);
  const auto product = BuildProduct(artifact.graph, query, cancellation);
  const auto preserved = RequireSolved(product.graph, observer, cancellation);
  if (baseline.win != preserved.win || baseline.loss != preserved.loss || baseline.draw != preserved.draw || baseline.closed_cycle != preserved.closed_cycle)
    throw std::invalid_argument("event product graph changed original outcome probabilities");
  const auto event_probability = Property(product, [&](const Tracker& tracker, GraphOutcome, bool) { return QuerySatisfied(tracker, query, product); }, cancellation);
  const auto observer_outcome = observer == BattleSide::attacker ? GraphOutcome::attacker_win : GraphOutcome::defender_win;
  const auto joint = Property(product, [&](const Tracker& tracker, GraphOutcome outcome, bool closed) {
    return !closed && outcome == observer_outcome && QuerySatisfied(tracker, query, product);
  }, cancellation);
  std::vector<EventDistributionBucket> count_distribution;
  for (std::size_t count = 0;; ++count) {
    count_distribution.push_back({"count:" + std::to_string(count),
        Property(product, [&](const Tracker& tracker, GraphOutcome, bool) { return tracker.count == count; }, cancellation)});
    if (count == query.distribution_count_limit) break;
  }
  const Integer count_overflow = Integer{query.distribution_count_limit} + 1;
  count_distribution.push_back({"count:" + count_overflow.str() + '+', Property(product,
      [&](const Tracker& tracker, GraphOutcome, bool) { return tracker.count > query.distribution_count_limit; }, cancellation)});
  std::vector<EventDistributionBucket> first_distribution{{"first:never", Property(product,
      [](const Tracker& tracker, GraphOutcome, bool) { return !tracker.first; }, cancellation)}};
  for (std::size_t turn = 1;; ++turn) {
    first_distribution.push_back({"first:turn:" + std::to_string(turn),
        Property(product, [&](const Tracker& tracker, GraphOutcome, bool) { return tracker.first && *tracker.first == turn; }, cancellation)});
    if (turn == query.distribution_turn_limit) break;
  }
  first_distribution.push_back({"first:after:" + std::to_string(query.distribution_turn_limit), Property(product,
      [&](const Tracker& tracker, GraphOutcome, bool) { return tracker.first && *tracker.first > query.distribution_turn_limit; }, cancellation)});
  auto [coverage, summaries] = Coverage(artifact.graph, query, cancellation);
  Rational count_total{0}, first_total{0};
  for (const auto& bucket : count_distribution) count_total += bucket.probability;
  for (const auto& bucket : first_distribution) first_total += bucket.probability;
  if (count_total != Rational{1} || first_total != Rational{1}) throw std::invalid_argument("event distributions must sum exactly to one");
  const auto runs = 4 + count_distribution.size() + first_distribution.size();
  return {artifact.calculation_revision, artifact.inference_run_id, observer, query, baseline.win, baseline.loss, baseline.draw,
      event_probability, joint, Conditional(joint, event_probability), Conditional(baseline.win - joint, Rational{1} - event_probability),
      std::move(first_distribution), std::move(count_distribution), coverage, std::move(summaries), true,
      {artifact.graph.topology.Nodes().size(), artifact.graph.topology.Edges().size(), product.graph.Nodes().size(), product.graph.Edges().size(), runs}};
}
} // namespace pbi
