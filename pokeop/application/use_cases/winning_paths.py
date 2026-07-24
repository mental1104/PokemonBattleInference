"""按固定配置查询、归并并分页返回可解释的胜利行动路径。"""

from __future__ import annotations

import base64
import binascii
import json
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from hashlib import sha256
from typing import Iterable

from pokeop.application.battle_graph_store import BattleGraphStore
from pokeop.application.solver.graph_solver import (
    BattleGraphSolveStatus,
    PurePythonBattleGraphSolver,
)
from pokeop.application.solver.models import (
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphEdge,
)
from pokeop.application.state_graph_exploration import ExplorationPathStep
from pokeop.application.state_graph_projection import ProbabilityProjection
from pokeop.application.use_cases.battle_exploration.errors import (
    IncompatibleCalculationRevisionError,
)
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.state import BattlerState


class WinningPathQueryError(ValueError):
    """表示胜利路径查询参数、分页游标或图内容违反稳定合同。"""


class WinningPathWinner(str, Enum):
    """标识调用方需要解释的固定获胜侧。"""

    ATTACKER = "attacker"
    DEFENDER = "defender"

    @property
    def graph_outcome(self) -> GraphNodeOutcome:
        """返回与当前胜者对应的状态图终局类别。"""
        if self is WinningPathWinner.ATTACKER:
            return GraphNodeOutcome.ATTACKER_WIN
        return GraphNodeOutcome.DEFENDER_WIN

    @property
    def observer(self) -> BattleSide:
        """返回精确图求解器使用的观察方。"""
        if self is WinningPathWinner.ATTACKER:
            return BattleSide.ATTACKER
        return BattleSide.DEFENDER


class WinningPathSort(str, Enum):
    """标识胜利路径组唯一公开的稳定排序策略。"""

    SHORTEST_HIGH_PROBABILITY = "shortest-high-probability"


@dataclass(frozen=True, slots=True)
class WinningPathConfigurationSide:
    """保存配置顶层身份中的一方 Pokémon、特性、道具和无序招式组。"""

    pokemon_id: int
    name: str
    level: int
    ability_identifier: str
    item_identifier: str
    move_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WinningPathConfiguration:
    """保存不会跨配置归并的稳定双方配置摘要。"""

    configuration_key: str
    attacker: WinningPathConfigurationSide
    defender: WinningPathConfigurationSide


@dataclass(frozen=True, slots=True)
class JointActionAlternative:
    """保存一条原始事件解释中双方本回合选择的联合行动。"""

    attacker_move_id: int | None
    defender_move_id: int | None
    attacker_source_identifier: str | None
    defender_source_identifier: str | None

    @property
    def stable_key(self) -> str:
        """返回不包含伤害档和 HP 结果的稳定联合行动键。"""
        return ":".join(
            (
                str(self.attacker_move_id or 0),
                str(self.defender_move_id or 0),
                self.attacker_source_identifier or "none",
                self.defender_source_identifier or "none",
            )
        )


@dataclass(frozen=True, slots=True)
class JointActionStep:
    """保存一个回合的联合行动身份和可解释的候选行动集合。"""

    turn_number: int
    attacker_move_id: int | None
    defender_move_id: int | None
    attacker_source_identifier: str | None
    defender_source_identifier: str | None
    ambiguous: bool
    alternatives: tuple[JointActionAlternative, ...]

    @property
    def stable_key(self) -> str:
        """返回用于行动序列前缀归并的稳定步骤键。"""
        alternatives = "|".join(item.stable_key for item in self.alternatives)
        return f"turn-{self.turn_number}:{alternatives}"


@dataclass(frozen=True, slots=True)
class WinningPathKeyEvent:
    """保存不依赖自由文本的关键命中、阻断、机制触发或终局事件摘要。"""

    kind: str
    actor: str | None
    target: str | None
    move_id: int | None
    source_identifier: str | None


@dataclass(frozen=True, slots=True)
class WinningPathGroup:
    """保存同一配置、同一联合行动序列归并后的胜利路径组。"""

    path_key: str
    terminal_turn: int
    probability: ProbabilityProjection
    raw_path_count: int
    raw_history_count_estimate: int
    terminal_reasons: tuple[str, ...]
    terminal_node_ids: tuple[int, ...]
    actions: tuple[JointActionStep, ...]
    representative_path: tuple[ExplorationPathStep, ...]
    damage_values: tuple[int, ...]
    attacker_remaining_hp_values: tuple[int, ...]
    defender_remaining_hp_values: tuple[int, ...]
    key_events: tuple[WinningPathKeyEvent, ...]


@dataclass(frozen=True, slots=True)
class WinningPathPrefixNode:
    """保存当前页胜利路径组构造出的压缩行动前缀树节点。"""

    prefix_key: str
    depth: int
    action: JointActionStep | None
    probability: ProbabilityProjection
    raw_path_count: int
    terminal_path_keys: tuple[str, ...]
    children: tuple["WinningPathPrefixNode", ...]


@dataclass(frozen=True, slots=True)
class WinningPathCycleReference:
    """保存遍历遇到的回边或重复节点，避免递归复制无限 walk。"""

    source_node_id: int
    edge_id: int
    target_node_id: int
    prefix_depth: int
    component_id: int | None


@dataclass(frozen=True, slots=True)
class WinningPathGroupsResult:
    """保存分页胜利路径组、前缀树、覆盖率和显式完整性语义。"""

    graph_id: str
    calculation_revision: str
    winner: WinningPathWinner
    sort: WinningPathSort
    configuration: WinningPathConfiguration
    winner_probability: ProbabilityProjection | None
    returned_probability: ProbabilityProjection
    returned_coverage: ProbabilityProjection | None
    path_groups: tuple[WinningPathGroup, ...]
    prefix_tree: WinningPathPrefixNode
    cycle_references: tuple[WinningPathCycleReference, ...]
    next_cursor: str | None
    has_more: bool
    query_complete: bool
    traversal_truncated: bool


@dataclass(frozen=True, slots=True)
class _RawWinningPath:
    """保存一次有限、无重复节点的根到目标终局 edge walk。"""

    edge_ids: tuple[int, ...]
    probability: Fraction


@dataclass(slots=True)
class _PathAccumulator:
    """在创建公开 DTO 前聚合同一联合行动序列的随机历史。"""

    path_key: str
    actions: tuple[JointActionStep, ...]
    probability: Fraction = Fraction(0, 1)
    raw_path_count: int = 0
    raw_history_count_estimate: int = 0
    terminal_turns: set[int] = field(default_factory=set)
    terminal_reasons: set[str] = field(default_factory=set)
    terminal_node_ids: set[int] = field(default_factory=set)
    damage_values: set[int] = field(default_factory=set)
    attacker_remaining_hp_values: set[int] = field(default_factory=set)
    defender_remaining_hp_values: set[int] = field(default_factory=set)
    key_events: set[WinningPathKeyEvent] = field(default_factory=set)
    representative_path: tuple[ExplorationPathStep, ...] = ()
    representative_probability: Fraction = Fraction(0, 1)


@dataclass(slots=True)
class _MutablePrefixNode:
    """在冻结前缀树 DTO 前暂存子节点和聚合统计。"""

    prefix_key: str
    depth: int
    action: JointActionStep | None
    probability: Fraction = Fraction(0, 1)
    raw_path_count: int = 0
    terminal_path_keys: list[str] = field(default_factory=list)
    children: dict[str, "_MutablePrefixNode"] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ListWinningPathGroupsUseCase:
    """按 graph store 中固定配置图查询有限、可分页的胜利行动路径组。"""

    graph_store: BattleGraphStore
    max_traversed_walks: int = 100_000

    def __post_init__(self) -> None:
        """校验 store 协议和有限遍历预算。"""
        if not isinstance(self.graph_store, BattleGraphStore):
            raise WinningPathQueryError("graph_store must implement BattleGraphStore")
        if (
            isinstance(self.max_traversed_walks, bool)
            or self.max_traversed_walks <= 0
        ):
            raise WinningPathQueryError("max_traversed_walks must be greater than 0")

    def execute(
        self,
        graph_id: str,
        calculation_revision: str,
        *,
        winner: WinningPathWinner,
        limit: int = 10,
        cursor: str | None = None,
        sort: WinningPathSort = WinningPathSort.SHORTEST_HIGH_PROBABILITY,
    ) -> WinningPathGroupsResult:
        """读取图、归并行动路径并返回一个稳定分页窗口。

        Args:
            graph_id: graph store 分配的稳定图标识。
            calculation_revision: 调用方支持的图计算语义版本。
            winner: 需要解释的固定获胜侧。
            limit: 本页最多返回的路径组数量，范围为 1 到 100。
            cursor: 上一页返回的不透明游标；首页为 None。
            sort: 当前只支持最短优先、组概率降序的稳定排序。

        Returns:
            包含配置摘要、Top-K 路径组、前缀树、概率覆盖与循环引用的结果。

        Raises:
            BattleGraphStoreError: 图不存在或过期时由 store 原样抛出。
            IncompatibleCalculationRevisionError: 计算版本不一致时抛出。
            WinningPathQueryError: 参数、游标或图求解合同非法时抛出。
        """
        _require_identifier(graph_id, "graph_id")
        _require_identifier(calculation_revision, "calculation_revision")
        if not isinstance(winner, WinningPathWinner):
            raise WinningPathQueryError("winner must be a WinningPathWinner")
        if not isinstance(sort, WinningPathSort):
            raise WinningPathQueryError("sort must be a WinningPathSort")
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise WinningPathQueryError("limit must be between 1 and 100")

        stored = self.graph_store.get(graph_id)
        if stored.calculation_revision != calculation_revision:
            raise IncompatibleCalculationRevisionError(
                graph_id,
                requested_revision=calculation_revision,
                stored_revision=stored.calculation_revision,
            )

        configuration = _configuration(stored.graph)
        offset = _decode_cursor(
            cursor,
            graph_id=graph_id,
            calculation_revision=calculation_revision,
            configuration_key=configuration.configuration_key,
            winner=winner,
            sort=sort,
        )
        raw_paths, cycle_references, traversal_truncated = _enumerate_winning_paths(
            stored.graph,
            winner=winner,
            max_traversed_walks=self.max_traversed_walks,
        )
        groups = _group_paths(stored.graph, configuration, raw_paths)
        ordered = tuple(
            sorted(
                groups,
                key=lambda group: (
                    group.terminal_turn,
                    -_projection_fraction(group.probability),
                    group.path_key,
                ),
            )
        )
        page = ordered[offset : offset + limit]
        next_offset = offset + len(page)
        has_more = next_offset < len(ordered)
        next_cursor = (
            _encode_cursor(
                graph_id=graph_id,
                calculation_revision=calculation_revision,
                configuration_key=configuration.configuration_key,
                winner=winner,
                sort=sort,
                offset=next_offset,
            )
            if has_more
            else None
        )

        solve_result = PurePythonBattleGraphSolver().solve(
            stored.graph,
            observer=winner.observer,
        )
        winner_probability = (
            solve_result.win_probability
            if solve_result.status is BattleGraphSolveStatus.SOLVED
            else None
        )
        returned_probability = sum(
            (_projection_fraction(group.probability) for group in page),
            start=Fraction(0, 1),
        )
        returned_coverage = (
            returned_probability / winner_probability
            if winner_probability is not None and winner_probability > 0
            else None
        )
        query_complete = (
            stored.graph.is_complete
            and solve_result.status is BattleGraphSolveStatus.SOLVED
            and not cycle_references
            and not traversal_truncated
        )
        return WinningPathGroupsResult(
            graph_id=graph_id,
            calculation_revision=calculation_revision,
            winner=winner,
            sort=sort,
            configuration=configuration,
            winner_probability=(
                ProbabilityProjection.from_fraction(winner_probability)
                if winner_probability is not None
                else None
            ),
            returned_probability=ProbabilityProjection.from_fraction(
                returned_probability
            ),
            returned_coverage=(
                ProbabilityProjection.from_fraction(returned_coverage)
                if returned_coverage is not None
                else None
            ),
            path_groups=page,
            prefix_tree=_build_prefix_tree(page),
            cycle_references=cycle_references,
            next_cursor=next_cursor,
            has_more=has_more,
            query_complete=query_complete,
            traversal_truncated=traversal_truncated,
        )


def _configuration(graph: StateGraphBuildResult) -> WinningPathConfiguration:
    """从根节点提取当前 graph 唯一固定配置身份。"""
    root = graph.node(graph.root_node_id).state
    attacker = _configuration_side(root.attacker)
    defender = _configuration_side(root.defender)
    payload = {
        "attacker": {
            "pokemon_id": attacker.pokemon_id,
            "level": attacker.level,
            "ability": attacker.ability_identifier,
            "item": attacker.item_identifier,
            "move_ids": attacker.move_ids,
        },
        "defender": {
            "pokemon_id": defender.pokemon_id,
            "level": defender.level,
            "ability": defender.ability_identifier,
            "item": defender.item_identifier,
            "move_ids": defender.move_ids,
        },
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return WinningPathConfiguration(
        configuration_key=f"cfg-{digest}",
        attacker=attacker,
        defender=defender,
    )


def _configuration_side(battler: BattlerState) -> WinningPathConfigurationSide:
    """把根节点一方 domain 配置转换为稳定基础类型摘要。"""
    spec = battler.spec
    return WinningPathConfigurationSide(
        pokemon_id=spec.pokemon_id,
        name=spec.name,
        level=spec.level,
        ability_identifier=spec.ability.value,
        item_identifier=spec.item.value,
        move_ids=tuple(sorted(move.move_id for move in spec.moves)),
    )


def _enumerate_winning_paths(
    graph: StateGraphBuildResult,
    *,
    winner: WinningPathWinner,
    max_traversed_walks: int,
) -> tuple[
    tuple[_RawWinningPath, ...],
    tuple[WinningPathCycleReference, ...],
    bool,
]:
    """有限枚举无重复节点 walk，并把重复节点压缩为循环引用。"""
    outgoing: dict[GraphNodeId, list[StateGraphEdge]] = defaultdict(list)
    for edge in graph.edges:
        outgoing[edge.source_node_id].append(edge)
    component_by_node = {
        node_id: int(component.component_id)
        for component in graph.components
        for node_id in component.node_ids
    }
    stack: list[tuple[GraphNodeId, tuple[int, ...], frozenset[GraphNodeId], Fraction]] = [
        (graph.root_node_id, (), frozenset((graph.root_node_id,)), Fraction(1, 1))
    ]
    paths: list[_RawWinningPath] = []
    cycles: dict[tuple[int, int, int, int], WinningPathCycleReference] = {}
    traversed_walks = 0
    truncated = False

    while stack:
        node_id, edge_ids, visited, probability = stack.pop()
        traversed_walks += 1
        if traversed_walks > max_traversed_walks:
            truncated = True
            break
        node = graph.node(node_id)
        if node.is_terminal:
            if node.outcome is winner.graph_outcome:
                paths.append(_RawWinningPath(edge_ids=edge_ids, probability=probability))
            continue

        for edge in reversed(outgoing.get(node_id, [])):
            if edge.target_node_id in visited:
                cycle = WinningPathCycleReference(
                    source_node_id=int(edge.source_node_id),
                    edge_id=int(edge.edge_id),
                    target_node_id=int(edge.target_node_id),
                    prefix_depth=len(edge_ids),
                    component_id=component_by_node.get(edge.target_node_id),
                )
                cycles[
                    (
                        cycle.source_node_id,
                        cycle.edge_id,
                        cycle.target_node_id,
                        cycle.prefix_depth,
                    )
                ] = cycle
                continue
            stack.append(
                (
                    edge.target_node_id,
                    edge_ids + (int(edge.edge_id),),
                    visited | frozenset((edge.target_node_id,)),
                    probability * edge.probability,
                )
            )
    return (
        tuple(paths),
        tuple(
            sorted(
                cycles.values(),
                key=lambda item: (
                    item.prefix_depth,
                    item.source_node_id,
                    item.edge_id,
                    item.target_node_id,
                ),
            )
        ),
        truncated,
    )


def _group_paths(
    graph: StateGraphBuildResult,
    configuration: WinningPathConfiguration,
    raw_paths: Iterable[_RawWinningPath],
) -> tuple[WinningPathGroup, ...]:
    """按配置键和联合行动序列归并有限终局 edge walks。"""
    edges = {int(edge.edge_id): edge for edge in graph.edges}
    accumulators: dict[str, _PathAccumulator] = {}
    for raw_path in raw_paths:
        path_edges = tuple(edges[edge_id] for edge_id in raw_path.edge_ids)
        actions = tuple(
            _joint_action_step(graph, edge, depth=index)
            for index, edge in enumerate(path_edges, start=1)
        )
        payload = configuration.configuration_key + "|" + "|".join(
            action.stable_key for action in actions
        )
        path_key = f"wp-{sha256(payload.encode('utf-8')).hexdigest()[:24]}"
        accumulator = accumulators.get(path_key)
        if accumulator is None:
            accumulator = _PathAccumulator(path_key=path_key, actions=actions)
            accumulators[path_key] = accumulator
        terminal = (
            graph.node(path_edges[-1].target_node_id)
            if path_edges
            else graph.node(graph.root_node_id)
        )
        accumulator.probability += raw_path.probability
        accumulator.raw_path_count += 1
        accumulator.raw_history_count_estimate += _event_history_count(path_edges)
        accumulator.terminal_turns.add(terminal.state.turn_number)
        accumulator.terminal_node_ids.add(int(terminal.node_id))
        if terminal.termination_reason is not None:
            accumulator.terminal_reasons.add(terminal.termination_reason.value)
        accumulator.attacker_remaining_hp_values.add(terminal.state.attacker.current_hp)
        accumulator.defender_remaining_hp_values.add(terminal.state.defender.current_hp)
        accumulator.damage_values.update(_damage_values(path_edges))
        accumulator.key_events.update(_key_events(path_edges))
        if raw_path.probability > accumulator.representative_probability:
            accumulator.representative_probability = raw_path.probability
            accumulator.representative_path = tuple(
                ExplorationPathStep(
                    source_node_id=edge.source_node_id,
                    edge_id=edge.edge_id,
                    target_node_id=edge.target_node_id,
                )
                for edge in path_edges
            )

    return tuple(
        WinningPathGroup(
            path_key=item.path_key,
            terminal_turn=min(item.terminal_turns),
            probability=ProbabilityProjection.from_fraction(item.probability),
            raw_path_count=item.raw_path_count,
            raw_history_count_estimate=item.raw_history_count_estimate,
            terminal_reasons=tuple(sorted(item.terminal_reasons)),
            terminal_node_ids=tuple(sorted(item.terminal_node_ids)),
            actions=item.actions,
            representative_path=item.representative_path,
            damage_values=tuple(sorted(item.damage_values)),
            attacker_remaining_hp_values=tuple(
                sorted(item.attacker_remaining_hp_values)
            ),
            defender_remaining_hp_values=tuple(
                sorted(item.defender_remaining_hp_values)
            ),
            key_events=tuple(
                sorted(
                    item.key_events,
                    key=lambda event: (
                        event.kind,
                        event.actor or "",
                        event.target or "",
                        event.move_id or 0,
                        event.source_identifier or "",
                    ),
                )
            ),
        )
        for item in accumulators.values()
    )


def _joint_action_step(
    graph: StateGraphBuildResult,
    edge: StateGraphEdge,
    *,
    depth: int,
) -> JointActionStep:
    """从一条正式边的全部事件解释中提取联合行动，不读取伤害结果。"""
    alternatives = tuple(
        sorted(
            {
                _joint_action_alternative(path)
                for path in edge.event_summary.paths
            },
            key=lambda item: item.stable_key,
        )
    )
    if not alternatives:
        alternatives = (JointActionAlternative(None, None, None, None),)
    exact = alternatives[0] if len(alternatives) == 1 else None
    source_node = graph.node(edge.source_node_id)
    return JointActionStep(
        turn_number=source_node.state.turn_number,
        attacker_move_id=exact.attacker_move_id if exact is not None else None,
        defender_move_id=exact.defender_move_id if exact is not None else None,
        attacker_source_identifier=(
            exact.attacker_source_identifier if exact is not None else None
        ),
        defender_source_identifier=(
            exact.defender_source_identifier if exact is not None else None
        ),
        ambiguous=len(alternatives) > 1,
        alternatives=alternatives,
    )


def _joint_action_alternative(
    path: tuple[object, ...],
) -> JointActionAlternative:
    """从一条原始事件路径提取双方 MOVE_SELECTED，缺失时回退到 MOVE_USED。"""
    selected = _action_events(path, BattleEventKind.MOVE_SELECTED)
    events = selected or _action_events(path, BattleEventKind.MOVE_USED)
    attacker = next(
        (event for event in events if event.actor is BattleSide.ATTACKER),
        None,
    )
    defender = next(
        (event for event in events if event.actor is BattleSide.DEFENDER),
        None,
    )
    return JointActionAlternative(
        attacker_move_id=attacker.move_id if attacker is not None else None,
        defender_move_id=defender.move_id if defender is not None else None,
        attacker_source_identifier=(
            attacker.source_identifier if attacker is not None else None
        ),
        defender_source_identifier=(
            defender.source_identifier if defender is not None else None
        ),
    )


def _action_events(
    path: tuple[object, ...],
    kind: BattleEventKind,
) -> tuple[BattleEvent, ...]:
    """按原始顺序筛选指定类别的结构化行动事件。"""
    return tuple(
        event
        for event in path
        if isinstance(event, BattleEvent) and event.kind is kind
    )


def _event_history_count(edges: tuple[StateGraphEdge, ...]) -> int:
    """估算一条 edge walk 对应的原始事件替代路径组合数量。"""
    count = 1
    for edge in edges:
        count *= len(edge.event_summary.paths)
    return count


def _damage_values(edges: tuple[StateGraphEdge, ...]) -> set[int]:
    """收集全部替代解释中离散可达的最终伤害事实。"""
    return {
        event.value
        for edge in edges
        for path in edge.event_summary.paths
        for event in path
        if isinstance(event, BattleEvent)
        and event.kind is BattleEventKind.DAMAGE
        and event.value is not None
    }


def _key_events(edges: tuple[StateGraphEdge, ...]) -> set[WinningPathKeyEvent]:
    """收集值得默认展示的结构化关键事件，不使用自由文本解析。"""
    key_kinds = {
        BattleEventKind.MISS,
        BattleEventKind.ACTION_BLOCKED,
        BattleEventKind.ABILITY_TRIGGERED,
        BattleEventKind.ITEM_TRIGGERED,
        BattleEventKind.STATUS_APPLIED,
        BattleEventKind.STATUS_PREVENTED,
        BattleEventKind.FAINTED,
    }
    return {
        WinningPathKeyEvent(
            kind=event.kind.value,
            actor=event.actor.value if event.actor is not None else None,
            target=event.target.value if event.target is not None else None,
            move_id=event.move_id,
            source_identifier=event.source_identifier,
        )
        for edge in edges
        for path in edge.event_summary.paths
        for event in path
        if isinstance(event, BattleEvent) and event.kind in key_kinds
    }


def _build_prefix_tree(
    groups: tuple[WinningPathGroup, ...],
) -> WinningPathPrefixNode:
    """仅根据当前页路径组构造有界行动前缀树。"""
    root = _MutablePrefixNode(prefix_key="root", depth=0, action=None)
    for group in groups:
        probability = _projection_fraction(group.probability)
        current = root
        current.probability += probability
        current.raw_path_count += group.raw_path_count
        for depth, action in enumerate(group.actions, start=1):
            prefix_payload = f"{current.prefix_key}|{action.stable_key}"
            prefix_key = f"prefix-{sha256(prefix_payload.encode('utf-8')).hexdigest()[:20]}"
            child = current.children.get(action.stable_key)
            if child is None:
                child = _MutablePrefixNode(
                    prefix_key=prefix_key,
                    depth=depth,
                    action=action,
                )
                current.children[action.stable_key] = child
            child.probability += probability
            child.raw_path_count += group.raw_path_count
            current = child
        current.terminal_path_keys.append(group.path_key)
    return _freeze_prefix_node(root)


def _freeze_prefix_node(node: _MutablePrefixNode) -> WinningPathPrefixNode:
    """把可变前缀树递归转换为稳定排序的不可变 DTO。"""
    children = tuple(
        _freeze_prefix_node(child)
        for _, child in sorted(node.children.items(), key=lambda item: item[0])
    )
    return WinningPathPrefixNode(
        prefix_key=node.prefix_key,
        depth=node.depth,
        action=node.action,
        probability=ProbabilityProjection.from_fraction(node.probability),
        raw_path_count=node.raw_path_count,
        terminal_path_keys=tuple(sorted(node.terminal_path_keys)),
        children=children,
    )


def _encode_cursor(
    *,
    graph_id: str,
    calculation_revision: str,
    configuration_key: str,
    winner: WinningPathWinner,
    sort: WinningPathSort,
    offset: int,
) -> str:
    """编码绑定不可变 graph、配置、胜者和排序的 URL-safe 分页游标。"""
    payload = {
        "v": 1,
        "graph_id": graph_id,
        "calculation_revision": calculation_revision,
        "configuration_key": configuration_key,
        "winner": winner.value,
        "sort": sort.value,
        "offset": offset,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str | None,
    *,
    graph_id: str,
    calculation_revision: str,
    configuration_key: str,
    winner: WinningPathWinner,
    sort: WinningPathSort,
) -> int:
    """校验不透明游标仍属于同一图、配置、胜者和排序。"""
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or not cursor or cursor != cursor.strip():
        raise WinningPathQueryError("cursor must be a normalized string or None")
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode(
                "utf-8"
            )
        )
    except (UnicodeError, binascii.Error, json.JSONDecodeError, ValueError) as error:
        raise WinningPathQueryError("cursor is malformed") from error
    expected = {
        "v": 1,
        "graph_id": graph_id,
        "calculation_revision": calculation_revision,
        "configuration_key": configuration_key,
        "winner": winner.value,
        "sort": sort.value,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise WinningPathQueryError("cursor does not belong to this winning-path query")
    offset = payload.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise WinningPathQueryError("cursor offset must be a non-negative integer")
    return offset


def _projection_fraction(probability: ProbabilityProjection) -> Fraction:
    """从 JSON 安全概率投影恢复 application 内部精确 Fraction。"""
    return Fraction(int(probability.numerator), int(probability.denominator))


def _require_identifier(value: str, field_name: str) -> None:
    """拒绝空值、非字符串或携带首尾空白的稳定标识。"""
    if not isinstance(value, str) or not value or value != value.strip():
        raise WinningPathQueryError(
            f"{field_name} must be a non-empty normalized string"
        )


__all__ = [
    "JointActionAlternative",
    "JointActionStep",
    "ListWinningPathGroupsUseCase",
    "WinningPathConfiguration",
    "WinningPathConfigurationSide",
    "WinningPathCycleReference",
    "WinningPathGroup",
    "WinningPathGroupsResult",
    "WinningPathKeyEvent",
    "WinningPathPrefixNode",
    "WinningPathQueryError",
    "WinningPathSort",
    "WinningPathWinner",
]
