#include "pbi/winning_paths.hpp"
#include "sha256.hpp"
#include <algorithm>
#include <array>
#include <limits>
#include <map>
#include <set>
#include <tuple>

namespace pbi {
namespace {
/// @param stop 同源令牌；取消中断整个查询，不返回累积到一半的路径。
void Check(CancellationToken stop) { if (stop.Requested()) throw std::runtime_error("winning paths cancelled"); }
/// 两种已知图来源的编译期只读视图，原正式图直接借用EventSummary而不深拷贝。
/// @tparam Graph BattleGraph或WinningPathGraph，保持具体节点/边类型，不做运行期擦除。
template<class Graph> class GraphRecords {
public:
  /// @param graph 只读拥有者；视图与所有span不得超过graph生命周期。
  explicit GraphRecords(const Graph& graph) : graph_(graph) {}
  /// @return 原节点只读span，不复制BattleState。
  [[nodiscard]] auto Nodes() const {
    if constexpr (std::is_same_v<Graph, BattleGraph>) return graph_.Nodes();
    else return std::span{graph_.nodes};
  }
  /// @return 原边只读span，不复制大型事件历史。
  [[nodiscard]] auto Edges() const {
    if constexpr (std::is_same_v<Graph, BattleGraph>) return graph_.Edges();
    else return std::span{graph_.edges};
  }
  /// @return 原SCC分类/身份span，空列表不改为推测分类。
  [[nodiscard]] auto Components() const {
    if constexpr (std::is_same_v<Graph, BattleGraph>) return graph_.Components();
    else return std::span{graph_.components};
  }
  /// @return 原顺序的保护原因span。
  [[nodiscard]] auto Truncations() const {
    if constexpr (std::is_same_v<Graph, BattleGraph>) return graph_.Truncations();
    else return std::span{graph_.truncations};
  }
  /// @return 正式BFS根0或记录明确原根，只提升身份不改变图。
  [[nodiscard]] ProjectionNodeId Root() const {
    if constexpr (std::is_same_v<Graph, BattleGraph>) return {0};
    else return graph_.root;
  }
private:
  const Graph& graph_;
};
/// @tparam Id 已知正式图或记录节点身份；@param id 原节点身份；@param count 完整节点数。
/// @return 精确有界下标，不截断大整数。
template<class Id> std::size_t NodeIndex(const Id& id, std::size_t count) {
  const Integer value = id.value;
  if (value < 0 || value >= count) throw std::invalid_argument("winning path node is outside graph");
  return value.convert_to<std::size_t>();
}
/// @param outcome 原节点类别；@return 原is_terminal，仅确定胜负/平局为true，unknown仍非终局。
bool Terminal(GraphOutcome outcome) {
  return outcome == GraphOutcome::attacker_win || outcome == GraphOutcome::defender_win || outcome == GraphOutcome::draw;
}
/// @param side 可空侧；@return 原事件排序所用空串或稳定侧标识。
std::string SideKey(std::optional<BattleSide> side) { return side ? (*side == BattleSide::attacker ? "attacker" : "defender") : ""; }
/// @param value 可空原来源；@return Python `value or fallback`，兼容合法外部历史的空值。
std::string TextOr(const std::optional<std::string>& value, const char* fallback) { return value && !value->empty() ? *value : fallback; }
/// @param battler 根节点的一侧；@return 原机械配置字段，raw透明标识不覆盖UNKNOWN。
WinningPathConfigurationSide ConfigurationSide(const BattlerState& battler) {
  constexpr std::array<std::string_view, 9> abilities{"unknown", "technician", "adaptability", "thick_fat", "filter", "solid_rock", "sniper", "multiscale", "inner_focus"};
  constexpr std::array<std::string_view, 6> items{"unknown", "life_orb", "choice_band", "choice_specs", "expert_belt", "eviolite"};
  const auto& spec = battler.View().spec.View();
  WinningPathConfigurationSide result{spec.pokemon_id, spec.name, spec.pokemon.level,
      std::string{abilities.at(static_cast<std::size_t>(spec.pokemon.ability))}, std::string{items.at(static_cast<std::size_t>(spec.pokemon.item))}, {}};
  for (const auto& move : spec.moves) result.move_ids.push_back(move.View().move_id);
  std::ranges::sort(result.move_ids);
  return result;
}
/// @param side 已验证枚举字符串和整数配置；@return 原sort_keys/compact JSON，无展示名或rawcontext。
std::string ConfigurationIdentity(const WinningPathConfigurationSide& side) {
  std::string text = "{\"ability\":\"" + side.ability_identifier + "\",\"item\":\"" + side.item_identifier + "\",\"level\":" + std::to_string(side.level) + ",\"move_ids\":[";
  for (std::size_t index = 0; index < side.move_ids.size(); ++index) {
    if (index != 0) text += ',';
    text += std::to_string(side.move_ids[index]);
  }
  return text + "],\"pokemon_id\":" + std::to_string(side.pokemon_id) + '}';
}
/// @param reason 已验证原终止或截断原因；@return 原稳定wire名称，不改写未知节点语义。
std::string Reason(const GraphStopReason& reason) {
  constexpr std::array<std::string_view, 4> terminal{"knockout", "mutual-knockout", "no-legal-action", "cycle-guard"};
  constexpr std::array<std::string_view, 3> truncated{"max-turns", "max-nodes", "max-edges"};
  return std::visit([&](auto value) -> std::string {
    if constexpr (std::is_same_v<decltype(value), BattleTermination>) return std::string{terminal.at(static_cast<std::size_t>(value))};
    else return std::string{truncated.at(static_cast<std::size_t>(value))};
  }, reason);
}
/// @param path 一条原替代历史；@return 原selected整体缺失时才fallback used，之后各取首个actor。
WinningJointActionAlternative Alternative(const WeightedEventPath& path) {
  const bool selected = std::ranges::any_of(path.events, [](const auto& event) {
    const auto* battle = std::get_if<BattleEvent>(&event); return battle && battle->View().kind == BattleEventKind::move_selected;
  });
  const auto kind = selected ? BattleEventKind::move_selected : BattleEventKind::move_used;
  std::array<const BattleEventData*, 2> actions{};
  for (const auto& event : path.events) if (const auto* battle = std::get_if<BattleEvent>(&event)) {
    const auto& data = battle->View();
    if (data.kind == kind && data.actor) {
      auto& action = actions.at(static_cast<std::size_t>(*data.actor));
      if (!action) action = &data;
    }
  }
  return {actions[0] ? actions[0]->move_id : std::nullopt, actions[1] ? actions[1]->move_id : std::nullopt,
      actions[0] ? actions[0]->source_identifier : std::nullopt, actions[1] ? actions[1]->source_identifier : std::nullopt};
}
/// @param graph 原完整节点；@param edge 一条正式边；@return 原按完整候选去重后stable_key排序的回合行动。
template<class Graph, class Edge> WinningJointActionStep ActionStep(const GraphRecords<Graph>& graph, const Edge& edge) {
  std::vector<WinningJointActionAlternative> alternatives;
  for (const auto& path : edge.events.Paths()) {
    auto value = Alternative(path);
    if (std::ranges::find(alternatives, value) == alternatives.end()) alternatives.push_back(std::move(value));
  }
  if (alternatives.empty()) alternatives.push_back({std::nullopt, std::nullopt, std::nullopt, std::nullopt});
  std::stable_sort(alternatives.begin(), alternatives.end(), [](const auto& left, const auto& right) { return left.StableKey() < right.StableKey(); });
  const auto exact = alternatives.size() == 1 ? std::optional{alternatives.front()} : std::nullopt;
  return {graph.Nodes()[NodeIndex(edge.source, graph.Nodes().size())].state.View().turn_number, exact, std::move(alternatives)};
}
/// @param kind 原事实种类；@return 原默认展示的七类关键事件，不能从随机文字推断。
bool KeyKind(BattleEventKind kind) {
  return kind == BattleEventKind::miss || kind == BattleEventKind::action_blocked || kind == BattleEventKind::ability_triggered ||
      kind == BattleEventKind::item_triggered || kind == BattleEventKind::status_applied || kind == BattleEventKind::status_prevented || kind == BattleEventKind::fainted;
}
/// @param event 关键事实；@return 原字符串/空串/0排序元组，不使用enum声明顺序。
auto KeyEventOrder(const WinningPathKeyEvent& event) {
  return std::tuple{std::string{BattleEventName(event.kind)}, SideKey(event.actor), SideKey(event.target), event.move_id.value_or(0), TextOr(event.source_identifier, "")};
}
/// @tparam Value 拥有值；@param values 待排序去重的结果集合；以完整值相等去重。
template<class Value> void SortUnique(std::vector<Value>& values) {
  std::ranges::sort(values); values.erase(std::unique(values.begin(), values.end()), values.end());
}
/// 一条原有限DFS walk，edges存原序列下标，visited只用于同一walk循环检查。
struct Walk { std::size_t node; std::vector<std::size_t> edges; std::set<std::size_t> visited; Rational probability; };
/// 一个实际获胜walk及绝对概率；没有把替代事件条件概率再次乘入正式边。
struct RawPath { std::vector<std::size_t> edges; Rational probability; };
/// 原枚举完整结果；truncated与存在cycle reference是两个独立事实。
struct Enumeration { std::vector<RawPath> paths; std::vector<WinningPathCycleReference> cycles; bool truncated = false; };
/// @param graph 只读正式图；@param query 原winner/遍历预算；@param stop 取消；@return 原顺序DFS结果。
template<class Graph> Enumeration Enumerate(const GraphRecords<Graph>& graph, const WinningPathQuery& query, CancellationToken stop) {
  std::vector<std::vector<std::size_t>> outgoing(graph.Nodes().size());
  for (std::size_t index = 0; index < graph.Edges().size(); ++index) outgoing.at(NodeIndex(graph.Edges()[index].source, graph.Nodes().size())).push_back(index);
  std::vector<std::optional<ComponentId>> components(graph.Nodes().size());
  for (const auto& component : graph.Components()) for (const auto& node : component.nodes) components.at(NodeIndex(node, graph.Nodes().size())) = component.id;
  const auto root = NodeIndex(graph.Root(), graph.Nodes().size());
  std::vector<Walk> stack{{root, {}, {root}, Rational{1}}};
  using CycleKey = std::tuple<std::size_t, Integer, std::size_t, std::size_t>;
  std::map<CycleKey, WinningPathCycleReference> cycles;
  Enumeration result;
  std::size_t traversed = 0;
  while (!stack.empty()) {
    Check(stop);
    auto walk = std::move(stack.back()); stack.pop_back();
    // 原判定为第N+1次pop才truncated；避免size_t上限的计数溢出。
    if (traversed == query.max_traversed_walks) { result.truncated = true; break; }
    ++traversed;
    const auto& node = graph.Nodes()[walk.node];
    if (Terminal(node.outcome)) {
      const auto desired = query.winner == BattleSide::attacker ? GraphOutcome::attacker_win : GraphOutcome::defender_win;
      if (node.outcome == desired) result.paths.push_back({std::move(walk.edges), std::move(walk.probability)});
      continue;
    }
    for (auto iterator = outgoing[walk.node].rbegin(); iterator != outgoing[walk.node].rend(); ++iterator) {
      Check(stop);
      const auto& edge = graph.Edges()[*iterator]; const auto target = NodeIndex(edge.target, graph.Nodes().size());
      if (walk.visited.contains(target)) {
        cycles.insert_or_assign(CycleKey{walk.node, edge.id.value, target, walk.edges.size()},
            WinningPathCycleReference{{Integer{edge.source.value}}, {Integer{edge.id.value}}, {Integer{edge.target.value}}, walk.edges.size(), components[target]});
      } else {
        auto next = walk; next.node = target; next.edges.push_back(*iterator); next.visited.insert(target); next.probability *= edge.probability;
        stack.push_back(std::move(next));
      }
    }
  }
  for (auto& [key, cycle] : cycles) { (void)key; result.cycles.push_back(std::move(cycle)); }
  std::ranges::sort(result.cycles, [](const auto& left, const auto& right) {
    return std::tuple{left.prefix_depth, left.source.value, left.edge.value, left.target.value} < std::tuple{right.prefix_depth, right.source.value, right.edge.value, right.target.value};
  });
  return result;
}
/// 仅在聚合过程中存在的最大代表概率；不发布为多余公开字段。
struct Accumulator { WinningPathGroup group; Rational representative_probability{0}; };
/// @param graph 原图；@param configuration 唯一配置；@param paths 原序walk；@param stop 取消。
/// @return 未分页的真实完整组，离散值收集全部替代历史而非仅代表历史。
template<class Graph> std::vector<WinningPathGroup> GroupPaths(const GraphRecords<Graph>& graph, const WinningPathConfiguration& configuration,
    const std::vector<RawPath>& paths, CancellationToken stop) {
  std::map<std::string, Accumulator> accumulators;
  for (const auto& path : paths) {
    Check(stop);
    std::vector<WinningJointActionStep> actions;
    std::string payload = configuration.configuration_key + '|';
    for (const auto index : path.edges) { if (!actions.empty()) payload += '|'; actions.push_back(ActionStep(graph, graph.Edges()[index])); payload += actions.back().StableKey(); }
    const auto key = "wp-" + detail::Sha256(payload).substr(0, 24);
    const auto terminal_index = (path.edges.empty() ? NodeIndex(graph.Root(), graph.Nodes().size()) : NodeIndex(graph.Edges()[path.edges.back()].target, graph.Nodes().size()));
    const auto& terminal = graph.Nodes()[terminal_index];
    auto [iterator, inserted] = accumulators.try_emplace(key, Accumulator{WinningPathGroup{key, terminal.state.View().turn_number, Rational{0}, Integer{0}, Integer{0}, {}, {}, std::move(actions), {}, {}, {}, {}, {}}});
    (void)inserted;
    auto& accumulator = iterator->second; auto& group = accumulator.group;
    group.probability += path.probability; ++group.raw_path_count;
    Integer histories = 1;
    for (const auto index : path.edges) {
      Check(stop);
      const auto& edge = graph.Edges()[index]; histories *= edge.events.Paths().size();
      for (const auto& history : edge.events.Paths()) for (const auto& event : history.events) if (const auto* battle = std::get_if<BattleEvent>(&event)) {
        const auto& data = battle->View();
        if (data.kind == BattleEventKind::damage && data.value) group.damage_values.push_back(*data.value);
        if (KeyKind(data.kind)) group.key_events.push_back({data.kind, data.actor, data.target, data.move_id, data.source_identifier});
      }
    }
    group.raw_history_count_estimate += histories;
    group.terminal_turn = std::min(group.terminal_turn, terminal.state.View().turn_number);
    group.terminal_node_ids.push_back({Integer{terminal.id.value}});
    if (terminal.reason) group.terminal_reasons.push_back(Reason(*terminal.reason));
    group.attacker_remaining_hp_values.push_back(terminal.state.View().attacker.View().current_hp);
    group.defender_remaining_hp_values.push_back(terminal.state.View().defender.View().current_hp);
    if (path.probability > accumulator.representative_probability) {
      accumulator.representative_probability = path.probability; group.representative_path.clear();
      for (const auto index : path.edges) { const auto& edge = graph.Edges()[index]; group.representative_path.push_back({{Integer{edge.source.value}}, {Integer{edge.id.value}}, {Integer{edge.target.value}}}); }
    }
  }
  std::vector<WinningPathGroup> groups;
  for (auto& [key, accumulator] : accumulators) {
    (void)key; Check(stop); auto& group = accumulator.group;
    SortUnique(group.terminal_reasons); SortUnique(group.damage_values); SortUnique(group.attacker_remaining_hp_values); SortUnique(group.defender_remaining_hp_values);
    std::ranges::sort(group.terminal_node_ids, {}, &ProjectionNodeId::value);
    group.terminal_node_ids.erase(std::unique(group.terminal_node_ids.begin(), group.terminal_node_ids.end()), group.terminal_node_ids.end());
    std::stable_sort(group.key_events.begin(), group.key_events.end(), [](const auto& left, const auto& right) { return KeyEventOrder(left) < KeyEventOrder(right); });
    group.key_events.erase(std::unique(group.key_events.begin(), group.key_events.end()), group.key_events.end());
    groups.push_back(std::move(group));
  }
  return groups;
}
/// @param groups 当前页真实路径组；@param stop 同源取消；@return 原递归前缀模型，以平坦临时arena构造避免查找别名失效。
WinningPathPrefixNode Prefix(const std::vector<WinningPathGroup>& groups, CancellationToken stop) {
  /// 临时arena单元只拥有一个前缀及其有序子下标，不向公开结果泄露可变别名。
  struct Mutable { WinningPathPrefixNode node; std::map<std::string, std::size_t> children; };
  std::vector<Mutable> arena{{WinningPathPrefixNode{"root", 0, std::nullopt, Rational{0}, Integer{0}, {}, {}}, {}}};
  for (const auto& group : groups) {
    Check(stop); std::size_t current = 0;
    arena[current].node.probability += group.probability; arena[current].node.raw_path_count += group.raw_path_count;
    for (std::size_t index = 0; index < group.actions.size(); ++index) {
      Check(stop); const auto& action = group.actions[index]; const auto stable_key = action.StableKey();
      const auto found = arena[current].children.find(stable_key);
      std::size_t child;
      if (found == arena[current].children.end()) {
        child = arena.size(); const auto prefix_key = "prefix-" + detail::Sha256(arena[current].node.prefix_key + '|' + stable_key).substr(0, 20);
        arena[current].children.emplace(stable_key, child);
        arena.push_back({WinningPathPrefixNode{prefix_key, index + 1, action, Rational{0}, Integer{0}, {}, {}}, {}});
      } else child = found->second;
      current = child; arena[current].node.probability += group.probability; arena[current].node.raw_path_count += group.raw_path_count;
    }
    arena[current].node.terminal_path_keys.push_back(group.path_key);
  }
  for (std::size_t remaining = arena.size(); remaining > 0; --remaining) {
    Check(stop); auto& value = arena[remaining - 1]; std::ranges::sort(value.node.terminal_path_keys);
    for (const auto& [key, child] : value.children) { (void)key; value.node.children.push_back(std::move(arena[child].node)); }
  }
  return std::move(arena.front().node);
}
/// @param graph 原完整图；@param stop 取消；@return 唯一正式求解器使用的拓扑，不接受外部胜率。
template<class Graph> ProbabilityGraph Topology(const GraphRecords<Graph>& graph, CancellationToken stop) {
  std::vector<ProbabilityNode> nodes; std::vector<ProbabilityEdge> edges;
  for (std::size_t index = 0; index < graph.Nodes().size(); ++index) {
    Check(stop); const auto& node = graph.Nodes()[index];
    if (node.id.value != index) throw std::invalid_argument("winning paths require original contiguous node IDs");
    nodes.push_back({node.outcome, node.state.View().rules.View().cycle_resolution});
  }
  std::set<Integer> identities;
  for (const auto& edge : graph.Edges()) {
    Check(stop);
    const Integer identity = edge.id.value;
    if (identity < 0 || !identities.insert(identity).second) throw std::invalid_argument("winning path edge IDs must be unique and nonnegative");
    edges.push_back({{NodeIndex(edge.source, nodes.size())}, {NodeIndex(edge.target, nodes.size())}, edge.probability});
  }
  return ProbabilityGraph{std::move(nodes), std::move(edges), {NodeIndex(graph.Root(), graph.Nodes().size())}, std::vector<GraphTruncation>{graph.Truncations().begin(), graph.Truncations().end()}};
}
/// @param graph 原图及原SCC分类；@param topology 已完整校验的拓扑；@param observer 原胜者；@param stop 取消。
/// @return 复用Core求解器的原胜率；原缺失封闭SCC分类时保留原奇异不可用，不能擅自补成零胜率。
template<class Graph> GraphSolution SolveOriginalGraph(const GraphRecords<Graph>& graph, const ProbabilityGraph& topology, BattleSide observer, CancellationToken stop) {
  // 原solver把传入CLOSED_CYCLE节点视作吸收平局。这里只投影该既有边界事实，不实现第二套方程。
  std::vector<ProbabilityNode> nodes(topology.Nodes().begin(), topology.Nodes().end());
  for (const auto& component : graph.Components()) if (component.kind == ComponentKind::closed_cycle)
    for (const auto& id : component.nodes) {
      Check(stop); auto& node = nodes.at(NodeIndex(id, nodes.size()));
      if (node.outcome == GraphOutcome::non_terminal) node.outcome = GraphOutcome::draw;
    }
  std::vector<ProbabilityEdge> edges;
  for (const auto& edge : topology.Edges()) if (!Terminal(nodes[edge.source.value].outcome)) edges.push_back(edge);
  const ProbabilityGraph absorbing{std::move(nodes), std::move(edges), topology.Root(), std::vector<GraphTruncation>{graph.Truncations().begin(), graph.Truncations().end()}};
  // 原未完成图先于SCC/奇异判定，不因缺少分类而改变不可用类别。
  if (!graph.Truncations().empty() || std::ranges::any_of(absorbing.Nodes(), [](const auto& node) { return node.outcome == GraphOutcome::unknown; }))
    return SolveGraph(absorbing, observer, std::nullopt, stop);
  for (const auto& component : AnalyzeComponents(absorbing, stop)) if (component.kind == ComponentKind::closed_cycle)
    return UnavailableGraph{GraphSolveStatus::singular_system, {"exact absorption equation is singular; check SCC classification and closed recurrent classes"}};
  return SolveGraph(absorbing, observer, std::nullopt, stop);
}
} // namespace

std::string WinningJointActionAlternative::StableKey() const {
  return std::to_string(attacker_move_id.value_or(0)) + ':' + std::to_string(defender_move_id.value_or(0)) + ':' + TextOr(attacker_source_identifier, "none") + ':' + TextOr(defender_source_identifier, "none");
}
std::string WinningJointActionStep::StableKey() const {
  std::string result = "turn-" + std::to_string(turn_number) + ':';
  for (std::size_t index = 0; index < alternatives.size(); ++index) { if (index != 0) result += '|'; result += alternatives[index].StableKey(); }
  return result;
}
namespace {
/// @param graph 同一静态只读来源；@return 原配置/SHA，不复制状态或事件。
template<class Graph> WinningPathConfiguration Describe(const GraphRecords<Graph>& graph) {
  const auto& state = graph.Nodes()[NodeIndex(graph.Root(), graph.Nodes().size())].state.View();
  auto attacker = ConfigurationSide(state.attacker), defender = ConfigurationSide(state.defender);
  const auto canonical = "{\"attacker\":" + ConfigurationIdentity(attacker) + ",\"defender\":" + ConfigurationIdentity(defender) + '}';
  return {"cfg-" + detail::Sha256(canonical).substr(0, 24), std::move(attacker), std::move(defender)};
}
/// @param graph 两种原图只读来源；@param query 原完整查询；@param stop 取消；@return 同一原算法结果。
template<class Graph> WinningPathGroupsResult Run(const GraphRecords<Graph>& graph, const WinningPathQuery& query, CancellationToken stop) {
  Check(stop);
  if (query.graph_id.empty() || query.calculation_revision.empty()) throw std::invalid_argument("winning path identifiers must be nonempty");
  if (query.winner != BattleSide::attacker && query.winner != BattleSide::defender) throw std::invalid_argument("winning path winner is unsupported");
  if (query.sort != WinningPathSort::shortest_high_probability) throw std::invalid_argument("winning path sort is unsupported");
  if (query.limit < 1 || query.limit > 100 || query.offset < 0 || query.max_traversed_walks == 0) throw std::invalid_argument("invalid winning path pagination or traversal budget");
  const auto topology = Topology(graph, stop);
  auto configuration = Describe(graph);
  auto enumeration = Enumerate(graph, query, stop);
  auto groups = GroupPaths(graph, configuration, enumeration.paths, stop);
  std::ranges::sort(groups, [](const auto& left, const auto& right) {
    if (left.terminal_turn != right.terminal_turn) return left.terminal_turn < right.terminal_turn;
    if (left.probability != right.probability) return left.probability > right.probability;
    return left.path_key < right.path_key;
  });
  const auto start = query.offset < groups.size() ? query.offset.convert_to<std::size_t>() : groups.size();
  const auto count = std::min(query.limit, groups.size() - start);
  std::vector<WinningPathGroup> page;
  for (std::size_t index = start; index < start + count; ++index) { Check(stop); page.push_back(std::move(groups[index])); }
  const Integer next = query.offset + count;
  const bool more = next < groups.size();
  const auto solution = SolveOriginalGraph(graph, topology, query.winner, stop);
  Check(stop);
  const auto* solved = std::get_if<SolvedGraph>(&solution);
  const std::optional<Rational> winner_probability = solved ? std::optional{solved->win} : std::nullopt;
  Rational returned{0}; for (const auto& group : page) returned += group.probability;
  const auto coverage = winner_probability && *winner_probability > Rational{0} ? std::optional{Rational{returned / *winner_probability}} : std::nullopt;
  const bool complete = graph.Truncations().empty() && solved && enumeration.cycles.empty() && !enumeration.truncated;
  auto prefix = Prefix(page, stop);
  return {query.graph_id, query.calculation_revision, query.winner, query.sort, std::move(configuration), winner_probability,
      returned, coverage, std::move(page), std::move(prefix), std::move(enumeration.cycles), more ? std::optional<Integer>{next} : std::nullopt,
      more, complete, enumeration.truncated};
}
} // namespace
WinningPathConfiguration DescribeWinningPathConfiguration(const WinningPathGraph& graph) { return Describe(GraphRecords{graph}); }
WinningPathConfiguration DescribeWinningPathConfiguration(const BattleGraph& graph) { return Describe(GraphRecords{graph}); }
WinningPathGroupsResult ListWinningPathGroups(const WinningPathGraph& graph, const WinningPathQuery& query, CancellationToken stop) {
  return Run(GraphRecords{graph}, query, stop);
}
WinningPathGroupsResult ListWinningPathGroups(const BattleGraph& graph, const WinningPathQuery& query, CancellationToken stop) {
  return Run(GraphRecords{graph}, query, stop);
}
} // namespace pbi
