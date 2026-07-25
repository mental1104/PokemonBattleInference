"""将完整战斗状态图投影为渐进探索所需的 JSON 友好读取模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from hashlib import sha256
from typing import Iterable

from pokeop.application.joint_action_metadata import (
    JointActionProbabilityMetadata,
    JointActionProbabilityMetadataError,
    is_joint_action_probability_event,
    joint_action_probability_from_path,
)
from pokeop.application.solver.models import (
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphEdge,
    StateGraphNode,
)
from pokeop.application.state_graph_exploration import (
    ExplorationCursor,
    StateGraphExplorationUseCase,
)
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.state import BattlerState, StatStages
from pokeop.domain.battle.status.state import (
    BadPoisonStatus,
    BurnStatus,
    ConfusionStatus,
    FlinchStatus,
    FreezeStatus,
    InfatuationStatus,
    NonVolatileStatus,
    ParalysisStatus,
    PoisonStatus,
    SleepStatus,
    VolatileStatus,
)
from pokeop.domain.battle.transitions import TransitionEvent, TransitionEventType


class StateGraphProjectionError(ValueError):
    """表示状态图无法形成稳定的 application 读取投影。"""


class TransitionGroupKind(str, Enum):
    """标识一组出边最先发生分叉的业务或随机机制。"""

    ACTION_SELECTION = "action-selection"
    ACTION_ORDER = "action-order"
    HIT_CHECK = "hit-check"
    DAMAGE_DISTRIBUTION = "damage-distribution"
    SECONDARY_EFFECT = "secondary-effect"
    COMPOSITE = "composite"


@dataclass(frozen=True, slots=True)
class ProbabilityProjection:
    """保存可安全传给 JavaScript 的精确概率投影。

    Args:
        numerator: 约分后分子的十进制字符串，不受 JavaScript 安全整数范围限制。
        denominator: 约分后分母的十进制字符串，不受 JavaScript 安全整数范围限制。
        decimal: 供展示和排序使用的浮点近似值，不能用于精确概率运算。
        percent: ``decimal * 100`` 的百分比近似值。
    """

    numerator: str
    denominator: str
    decimal: float
    percent: float

    @classmethod
    def from_fraction(cls, probability: Fraction) -> "ProbabilityProjection":
        """把精确 ``Fraction`` 转换为 JSON 安全投影。

        Args:
            probability: 待投影的非负精确概率。

        Returns:
            分子分母使用字符串、同时附带展示近似值的新投影。

        Raises:
            StateGraphProjectionError: 输入不是 ``Fraction`` 或概率小于 0 时抛出。
        """
        if not isinstance(probability, Fraction):
            raise StateGraphProjectionError("probability must use fractions.Fraction")
        if probability < 0:
            raise StateGraphProjectionError("probability must not be negative")
        decimal = float(probability)
        return cls(
            numerator=str(probability.numerator),
            denominator=str(probability.denominator),
            decimal=decimal,
            percent=decimal * 100,
        )


@dataclass(frozen=True, slots=True)
class MoveSlotDetail:
    """保存一个招式槽当前可观察的 PP、禁用和锁定状态。"""

    move_id: int
    current_pp: int
    max_pp: int
    disabled: bool
    locked: bool


@dataclass(frozen=True, slots=True)
class StatusDetail:
    """使用显式可空字段投影当前已实现的主状态或临时状态。

    Args:
        kind: 状态枚举的稳定字符串值。
        turns_asleep: 睡眠已持续回合数，仅睡眠状态使用。
        toxic_counter: 剧毒累计计数，仅剧毒状态使用。
        turns_remaining: 混乱等临时状态的剩余回合数。
        source_id: 着迷等状态记录的来源标识。
    """

    kind: str
    turns_asleep: int | None = None
    toxic_counter: int | None = None
    turns_remaining: int | None = None
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class StatStagesDetail:
    """保存七类能力等级的 JSON 友好快照。"""

    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int
    accuracy: int
    evasion: int


@dataclass(frozen=True, slots=True)
class BattlerDetail:
    """保存一方完整但不泄漏 domain 对象的节点状态摘要。"""

    pokemon_id: int
    name: str
    ability: str
    item: str
    current_hp: int
    max_hp: int
    moves: tuple[MoveSlotDetail, ...]
    major_status: StatusDetail | None
    volatile_statuses: tuple[StatusDetail, ...]
    stat_stages: StatStagesDetail
    last_move_id: int | None
    choice_lock_move_id: int | None
    item_consumed: bool
    first_turn: bool


@dataclass(frozen=True, slots=True)
class SideConditionsDetail:
    """保存一侧当前已经建模的屏障状态。"""

    reflect: bool
    light_screen: bool
    aurora_veil: bool


@dataclass(frozen=True, slots=True)
class BattleFieldDetail:
    """保存天气、场地以及稳定双方视角的边侧状态。"""

    weather: str | None
    terrain: str | None
    attacker_side_conditions: SideConditionsDetail
    defender_side_conditions: SideConditionsDetail


@dataclass(frozen=True, slots=True)
class BattleNodeDetail:
    """保存前端无需理解 domain 类型即可展示的完整节点详情。"""

    node_id: int
    turn_number: int
    phase: str
    outcome: str
    termination_reason: str | None
    attacker: BattlerDetail
    defender: BattlerDetail
    field: BattleFieldDetail
    terminal: bool
    has_outgoing_edges: bool


@dataclass(frozen=True, slots=True)
class RandomResultDetail:
    """保存一条原始随机事件的稳定来源、结果和值。"""

    event_type: str
    event_id: str
    outcome_id: str
    numeric_value: int | None


@dataclass(frozen=True, slots=True)
class BattleEventDetail:
    """把 domain ``BattleEvent`` 转换为无对象引用的 application DTO。"""

    kind: str
    turn_number: int
    actor: str | None
    target: str | None
    move_id: int | None
    source_identifier: str | None
    value: int | None
    before_value: int | None
    after_value: int | None


@dataclass(frozen=True, slots=True)
class DamageRandomMetadata:
    """解释一条伤害随机路径使用的规则集原始值和最终 HP 变化。

    Args:
        raw_roll_index: 规则集随机档位序列中的从 0 开始索引。
        raw_roll_value: 规则集明确提供的百分制原始随机值，例如 85 到 100。
        final_damage: 伤害公式与全部倍率取整后产生的最终伤害值。
        actual_hp_loss: HP 在 0 处截断后真正扣除的数值。
    """

    raw_roll_index: int
    raw_roll_value: int
    final_damage: int
    actual_hp_loss: int


@dataclass(frozen=True, slots=True)
class JointActionDetail:
    """描述联合行动中一侧已选择的类型化行动。

    Args:
        side: ``attacker`` 或 ``defender`` 稳定侧别。
        action_type: ``move``、``struggle`` 或 ``pass``。
        move_id: 普通招式 ID；挣扎和 pass 为 None。
    """

    side: str
    action_type: str
    move_id: int | None


@dataclass(frozen=True, slots=True)
class ActionResolutionDetail:
    """描述一侧行动在一条紧凑随机结果中的实际执行状态。

    Args:
        side: 行动所属稳定侧别。
        move_id: 普通招式 ID；挣扎和 pass 为 None。
        action_type: 行动来源类型。
        order_position: 最终执行顺序；未产生排序事件时为 None。
        status: ``executed``、``blocked``、``cancelled`` 或 ``passed``。
        hit: 已执行攻击是否命中；不适用时为 None。
        reason: 阻断或取消原因；正常执行时为 None。
    """

    side: str
    move_id: int | None
    action_type: str
    order_position: int | None
    status: str
    hit: bool | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class StatusEffectSummary:
    """描述状态施加或阻止结果，供前端以紧凑标签展示。"""

    result: str
    source_side: str | None
    target_side: str | None
    source_identifier: str | None


@dataclass(frozen=True, slots=True)
class CompactRandomResult:
    """把等价事件路径压缩为一项离散、结构化的随机结果摘要。

    同一目标状态、行动执行结果、最终伤害和状态效果相同的路径会合并，并保留所有
    原始伤害随机档值，避免把 16 档离散语义误写成连续区间。
    """

    target_node_id: int
    action_resolutions: tuple[ActionResolutionDetail, ...]
    order_reason: str
    critical_hit: bool | None
    raw_roll_values: tuple[int, ...]
    final_damage_values: tuple[int, ...]
    actual_hp_losses: tuple[int, ...]
    status_effects: tuple[StatusEffectSummary, ...]
    path_count: int


@dataclass(frozen=True, slots=True)
class TransitionEventPathDetail:
    """保存到达同一后继状态的一条原始事件替代路径。"""

    random_results: tuple[RandomResultDetail, ...]
    damage_rolls: tuple[DamageRandomMetadata, ...]
    battle_events: tuple[BattleEventDetail, ...]


@dataclass(frozen=True, slots=True)
class TransitionLabelFields:
    """保存 presenter 生成可读分支标签所需的结构化字段。"""

    selected_move_ids: tuple[int, ...]
    acting_sides: tuple[str, ...]
    target_sides: tuple[str, ...]
    result_keys: tuple[str, ...]
    source_identifiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransitionOutcome:
    """表示联合行动下一个已经按后继状态归并的可前进随机结果。"""

    edge_id: int
    target_node_id: int
    probability: ProbabilityProjection
    joint_probability: ProbabilityProjection
    cumulative_probability: ProbabilityProjection
    label_fields: TransitionLabelFields
    raw_random_values: tuple[int, ...]
    random_results: tuple[RandomResultDetail, ...]
    damage_rolls: tuple[DamageRandomMetadata, ...]
    compact_results: tuple[CompactRandomResult, ...]
    battle_event_paths: tuple[tuple[BattleEventDetail, ...], ...]
    event_paths: tuple[TransitionEventPathDetail, ...]


@dataclass(frozen=True, slots=True)
class TransitionGroupSummary:
    """保存一个分支组可在收起状态直接展示的伤害区间。"""

    minimum_damage: int | None
    maximum_damage: int | None
    minimum_hp_loss: int | None
    maximum_hp_loss: int | None


@dataclass(frozen=True, slots=True)
class TransitionGroup:
    """表示一个双方联合行动及其按需展开的紧凑随机结果。"""

    group_id: str
    kind: TransitionGroupKind
    label_key: str
    probability: ProbabilityProjection
    selection_probability: ProbabilityProjection
    attacker_action: JointActionDetail | None
    defender_action: JointActionDetail | None
    raw_result_count: int
    distinct_outcome_count: int
    summary: TransitionGroupSummary
    expanded: bool
    outcomes: tuple[TransitionOutcome, ...]


@dataclass(frozen=True, slots=True)
class BattleNodeProjection:
    """聚合游标当前节点详情和默认折叠的出边分组。"""

    node: BattleNodeDetail
    cumulative_probability: ProbabilityProjection
    transition_groups: tuple[TransitionGroup, ...]


@dataclass(frozen=True, slots=True)
class _TransitionGroupKey:
    """保存稳定分组类别、来源判别键和可选联合行动。"""

    kind: TransitionGroupKind
    discriminator: str
    attacker_action: JointActionDetail | None = None
    defender_action: JointActionDetail | None = None


@dataclass(frozen=True, slots=True)
class _TransitionContribution:
    """保存一个联合行动到一条正式状态边的精确概率与事件路径。"""

    edge: StateGraphEdge
    paths: tuple[tuple[TransitionEvent, ...], ...]
    selection_probability: Fraction
    random_probability: Fraction


@dataclass(slots=True)
class _TransitionGroupAccumulator:
    """在投影当前节点期间暂存同一联合行动的状态边贡献。"""

    key: _TransitionGroupKey
    contributions: list[_TransitionContribution]


@dataclass(frozen=True, slots=True)
class StateGraphProjectionUseCase:
    """在完整图与真实 exploration 游标之上构造节点和概率分支投影。

    Args:
        graph_id: 当前完整图的稳定 application 标识。
        graph: #52 保留、#60 可交由 graph store 管理的完整状态图 artifact。
    """

    graph_id: str
    graph: StateGraphBuildResult

    def __post_init__(self) -> None:
        """复用 exploration 用例校验图标识、完整图类型和根节点。"""
        StateGraphExplorationUseCase(graph_id=self.graph_id, graph=self.graph)

    def project_cursor(
        self,
        cursor: ExplorationCursor,
        *,
        expanded_group_ids: Iterable[str] = (),
    ) -> BattleNodeProjection:
        """投影游标当前节点、累计概率和可展开分支组。

        Args:
            cursor: 由同一 ``graph_id`` 和完整图产生的真实边序列游标。
            expanded_group_ids: 本次读取需要展开 outcomes 的稳定 group ID；省略时全部组收起。

        Returns:
            不包含 domain 对象引用的当前节点读取投影。

        Raises:
            ExplorationCursorError: 游标跨图、路径断裂或引用非法边时由探索用例抛出。
            StateGraphProjectionError: 展开组标识为空白或累计概率非法时抛出。
        """
        explorer = StateGraphExplorationUseCase(graph_id=self.graph_id, graph=self.graph)
        node = explorer.current_node(cursor)
        cumulative_probability = explorer.cumulative_probability(cursor)
        return self._project(
            node=node,
            cumulative_probability=cumulative_probability,
            expanded_group_ids=_normalize_group_ids(expanded_group_ids),
        )

    def project_node(
        self,
        node_id: GraphNodeId,
        *,
        cumulative_probability: Fraction = Fraction(1, 1),
        expanded_group_ids: Iterable[str] = (),
    ) -> BattleNodeProjection:
        """直接按节点 ID 构造读取投影，供 graph store 查询用例复用。

        Args:
            node_id: 当前完整图中的正式节点 ID。
            cumulative_probability: 调用方已根据真实游标计算的根到当前节点概率。
            expanded_group_ids: 本次读取需要展开 outcomes 的稳定 group ID。

        Returns:
            节点详情、给定累计概率和当前出边组组成的读取投影。

        Raises:
            StateGraphError: 节点 ID 不属于当前完整图时由图模型抛出。
            StateGraphProjectionError: 累计概率不是 ``Fraction``、超出 ``[0, 1]`` 或组 ID 非法。
        """
        if not isinstance(cumulative_probability, Fraction):
            raise StateGraphProjectionError(
                "cumulative_probability must use fractions.Fraction"
            )
        if not 0 <= cumulative_probability <= 1:
            raise StateGraphProjectionError(
                "cumulative_probability must be in the interval [0, 1]"
            )
        return self._project(
            node=self.graph.node(node_id),
            cumulative_probability=cumulative_probability,
            expanded_group_ids=_normalize_group_ids(expanded_group_ids),
        )

    def _project(
        self,
        *,
        node: StateGraphNode,
        cumulative_probability: Fraction,
        expanded_group_ids: frozenset[str],
    ) -> BattleNodeProjection:
        """在完成游标或节点校验后构造公开读取 DTO。

        Args:
            node: 当前完整图中的正式节点。
            cumulative_probability: 根到当前用户路径的精确累计概率。
            expanded_group_ids: 已规范化的待展开 group ID 集合。

        Returns:
            当前节点详情、累计概率和稳定排序分支组。
        """
        outgoing_edges = tuple(
            edge
            for edge in self.graph.edges
            if edge.source_node_id == node.node_id
        )
        return BattleNodeProjection(
            node=_node_detail(node, has_outgoing_edges=bool(outgoing_edges)),
            cumulative_probability=ProbabilityProjection.from_fraction(
                cumulative_probability
            ),
            transition_groups=_transition_groups(
                node=node,
                outgoing_edges=outgoing_edges,
                cumulative_probability=cumulative_probability,
                expanded_group_ids=expanded_group_ids,
            ),
        )


def _node_detail(
    node: StateGraphNode,
    *,
    has_outgoing_edges: bool,
) -> BattleNodeDetail:
    """把正式图节点转换为不泄漏领域对象的完整状态摘要。

    Args:
        node: 待投影的正式 ``StateGraphNode``。
        has_outgoing_edges: 当前完整图中是否存在从该节点出发的边。

    Returns:
        包含双方动态状态、场地和终局信息的节点 DTO。
    """
    state = node.state
    return BattleNodeDetail(
        node_id=int(node.node_id),
        turn_number=state.turn_number,
        phase=state.phase.value,
        outcome=node.outcome.value,
        termination_reason=_enum_value(node.termination_reason),
        attacker=_battler_detail(state.attacker),
        defender=_battler_detail(state.defender),
        field=BattleFieldDetail(
            weather=_enum_value(state.field.weather),
            terrain=_enum_value(state.field.terrain),
            attacker_side_conditions=_side_conditions_detail(
                state.field.attacker_side_conditions
            ),
            defender_side_conditions=_side_conditions_detail(
                state.field.defender_side_conditions
            ),
        ),
        terminal=node.is_terminal,
        has_outgoing_edges=has_outgoing_edges,
    )


def _battler_detail(battler: BattlerState) -> BattlerDetail:
    """投影一方当前 HP、招式槽、状态、等级和锁定信息。

    Args:
        battler: 当前图节点中的不可变战斗方状态。

    Returns:
        仅包含基础类型和 application DTO 的一方详情。
    """
    return BattlerDetail(
        pokemon_id=battler.spec.pokemon_id,
        name=battler.spec.name,
        ability=_enum_value(battler.spec.ability) or "unknown",
        item=_enum_value(battler.spec.item) or "unknown",
        current_hp=battler.current_hp,
        max_hp=battler.spec.stats.hp,
        moves=tuple(
            MoveSlotDetail(
                move_id=slot.move_id,
                current_pp=slot.current_pp,
                max_pp=slot.max_pp,
                disabled=slot.is_disabled,
                locked=slot.is_locked,
            )
            for slot in battler.move_slots
        ),
        major_status=(
            _status_detail(battler.status.non_volatile)
            if battler.status.non_volatile is not None
            else None
        ),
        volatile_statuses=tuple(
            _status_detail(status)
            for status in sorted(
                battler.status.volatile,
                key=lambda value: value.kind.value,
            )
        ),
        stat_stages=_stat_stages_detail(battler.stat_stages),
        last_move_id=battler.last_move_id,
        choice_lock_move_id=battler.choice_lock_move_id,
        item_consumed=battler.item_consumed,
        first_turn=battler.is_first_turn,
    )


def _status_detail(status: NonVolatileStatus | VolatileStatus) -> StatusDetail:
    """按当前显式状态类型保留其附加计数或来源字段。

    Args:
        status: 一项已经由 ``CombatantStatus`` 校验的主状态或临时状态。

    Returns:
        与具体状态字段一一对应的稳定 ``StatusDetail``。

    Raises:
        StateGraphProjectionError: domain 新增状态类型但 projection 尚未显式适配时抛出。
    """
    if isinstance(status, SleepStatus):
        return StatusDetail(kind=status.kind.value, turns_asleep=status.turns_asleep)
    if isinstance(status, BadPoisonStatus):
        return StatusDetail(kind=status.kind.value, toxic_counter=status.toxic_counter)
    if isinstance(status, ConfusionStatus):
        return StatusDetail(
            kind=status.kind.value,
            turns_remaining=status.turns_remaining,
        )
    if isinstance(status, InfatuationStatus):
        return StatusDetail(kind=status.kind.value, source_id=status.source_id)
    if isinstance(
        status,
        (
            ParalysisStatus,
            BurnStatus,
            FreezeStatus,
            PoisonStatus,
            FlinchStatus,
        ),
    ):
        return StatusDetail(kind=status.kind.value)
    raise StateGraphProjectionError(
        f"unsupported combatant status projection: {type(status).__name__}"
    )


def _stat_stages_detail(stages: StatStages) -> StatStagesDetail:
    """把七类能力等级转换为基础整数 DTO。"""
    return StatStagesDetail(
        attack=stages.attack,
        defense=stages.defense,
        special_attack=stages.special_attack,
        special_defense=stages.special_defense,
        speed=stages.speed,
        accuracy=stages.accuracy,
        evasion=stages.evasion,
    )


def _side_conditions_detail(conditions: SideConditions) -> SideConditionsDetail:
    """把当前已建模的边侧屏障转换为布尔字段 DTO。"""
    return SideConditionsDetail(
        reflect=conditions.reflect,
        light_screen=conditions.light_screen,
        aurora_veil=conditions.aurora_veil,
    )


def _transition_groups(
    *,
    node: StateGraphNode,
    outgoing_edges: tuple[StateGraphEdge, ...],
    cumulative_probability: Fraction,
    expanded_group_ids: frozenset[str],
) -> tuple[TransitionGroup, ...]:
    """优先按双方联合行动分组，并在组内按目标状态保留随机结果。

    Args:
        node: 当前 source node，用于生成稳定 group ID 和伤害档元数据。
        outgoing_edges: 当前节点全部正式状态图边。
        cumulative_probability: 根到当前游标的精确累计概率。
        expanded_group_ids: 本次明确请求展开的联合行动 group ID。

    Returns:
        按联合行动稳定排序的默认折叠分支组；旧图缺少完整选招事件时保留原机制分组。
    """
    accumulators = _transition_group_accumulators(outgoing_edges)
    groups = tuple(
        _project_group(
            node=node,
            accumulator=accumulator,
            cumulative_probability=cumulative_probability,
            expanded_group_ids=expanded_group_ids,
        )
        for accumulator in accumulators
    )
    joint_groups = tuple(
        group for group in groups if group.attacker_action is not None
    )
    if joint_groups:
        total_selection_probability = sum(
            (
                Fraction(
                    int(group.selection_probability.numerator),
                    int(group.selection_probability.denominator),
                )
                for group in joint_groups
            ),
            start=Fraction(0, 1),
        )
        if total_selection_probability != 1:
            raise StateGraphProjectionError(
                "joint action selection probabilities must sum exactly to 1"
            )
    return tuple(
        sorted(
            groups,
            key=lambda group: (
                _GROUP_KIND_ORDER[group.kind],
                group.group_id,
            ),
        )
    )


def _transition_group_accumulators(
    outgoing_edges: tuple[StateGraphEdge, ...],
) -> tuple[_TransitionGroupAccumulator, ...]:
    """把正式图边拆分为联合行动贡献；旧事件路径使用兼容机制分组。"""
    if not outgoing_edges:
        return ()
    all_paths = tuple(
        path for edge in outgoing_edges for path in edge.event_summary.paths
    )
    has_complete_joint_action = any(
        _joint_action_signature(path) is not None for path in all_paths
    )
    if not has_complete_joint_action:
        return _legacy_group_accumulators(outgoing_edges)
    if any(_joint_action_signature(path) is None for path in all_paths):
        raise StateGraphProjectionError(
            "joint action projection requires both MOVE_SELECTED events on every path"
        )

    accumulators: dict[_TransitionGroupKey, _TransitionGroupAccumulator] = {}
    for edge in outgoing_edges:
        paths_by_action: dict[
            tuple[JointActionDetail, JointActionDetail],
            list[tuple[TransitionEvent, ...]],
        ] = {}
        for path in edge.event_summary.paths:
            signature = _joint_action_signature(path)
            if signature is None:
                raise StateGraphProjectionError(
                    "complete joint action path unexpectedly became unresolved"
                )
            paths_by_action.setdefault(signature, []).append(path)

        edge_joint_probability = Fraction(0, 1)
        for (attacker_action, defender_action), paths in paths_by_action.items():
            metadata = _consistent_joint_action_metadata(tuple(paths))
            if metadata is None:
                if len(paths_by_action) != 1:
                    raise StateGraphProjectionError(
                        "merged edge with multiple joint actions requires exact probability metadata"
                    )
                metadata = JointActionProbabilityMetadata(
                    selection_probability=Fraction(1, 1),
                    random_probability=edge.probability,
                )
            edge_joint_probability += (
                metadata.selection_probability * metadata.random_probability
            )
            key = _TransitionGroupKey(
                kind=TransitionGroupKind.ACTION_SELECTION,
                discriminator=(
                    f"{_action_discriminator(attacker_action)}|"
                    f"{_action_discriminator(defender_action)}"
                ),
                attacker_action=attacker_action,
                defender_action=defender_action,
            )
            accumulator = accumulators.get(key)
            if accumulator is None:
                accumulator = _TransitionGroupAccumulator(key=key, contributions=[])
                accumulators[key] = accumulator
            accumulator.contributions.append(
                _TransitionContribution(
                    edge=edge,
                    paths=tuple(paths),
                    selection_probability=metadata.selection_probability,
                    random_probability=metadata.random_probability,
                )
            )
        if edge_joint_probability != edge.probability:
            raise StateGraphProjectionError(
                "joint action probability metadata must reproduce the formal edge probability"
            )
    return tuple(accumulators.values())


def _legacy_group_accumulators(
    outgoing_edges: tuple[StateGraphEdge, ...],
) -> tuple[_TransitionGroupAccumulator, ...]:
    """为旧图和只关注随机机制的合成测试保留原首分叉分组。"""
    selection_signatures = {
        _selection_signature(path)
        for edge in outgoing_edges
        for path in edge.event_summary.paths
    }
    has_strategy_branch = len(selection_signatures) > 1
    accumulators: dict[_TransitionGroupKey, _TransitionGroupAccumulator] = {}
    for edge in outgoing_edges:
        key = _group_key_for_edge(edge, has_strategy_branch=has_strategy_branch)
        accumulator = accumulators.get(key)
        if accumulator is None:
            accumulator = _TransitionGroupAccumulator(key=key, contributions=[])
            accumulators[key] = accumulator
        accumulator.contributions.append(
            _TransitionContribution(
                edge=edge,
                paths=edge.event_summary.paths,
                selection_probability=Fraction(1, 1),
                random_probability=edge.probability,
            )
        )
    return tuple(accumulators.values())


def _consistent_joint_action_metadata(
    paths: tuple[tuple[TransitionEvent, ...], ...],
) -> JointActionProbabilityMetadata | None:
    """读取同一联合行动、同一正式边路径共享的精确概率元数据。"""
    try:
        values = _stable_unique(
            joint_action_probability_from_path(path) for path in paths
        )
    except JointActionProbabilityMetadataError as error:
        raise StateGraphProjectionError(str(error)) from error
    non_null_values = tuple(value for value in values if value is not None)
    if not non_null_values:
        return None
    if len(non_null_values) != 1 or len(values) != 1:
        raise StateGraphProjectionError(
            "joint action paths on one edge must share identical probability metadata"
        )
    return non_null_values[0]


def _joint_action_signature(
    path: tuple[TransitionEvent, ...],
) -> tuple[JointActionDetail, JointActionDetail] | None:
    """读取一条完整回合路径中双方各自唯一的行动选择。"""
    selected: dict[str, JointActionDetail] = {}
    for event in path:
        if not isinstance(event, BattleEvent):
            continue
        if event.kind is not BattleEventKind.MOVE_SELECTED or event.actor is None:
            continue
        side = event.actor.value
        action = JointActionDetail(
            side=side,
            action_type=event.source_identifier or "unknown",
            move_id=event.move_id,
        )
        existing = selected.get(side)
        if existing is not None and existing != action:
            raise StateGraphProjectionError(
                f"event path contains conflicting selected actions for {side}"
            )
        selected[side] = action
    attacker = selected.get(BattleSide.ATTACKER.value)
    defender = selected.get(BattleSide.DEFENDER.value)
    if attacker is None or defender is None:
        return None
    return (attacker, defender)


def _action_discriminator(action: JointActionDetail) -> str:
    """把一侧行动转换为稳定 group ID 判别片段。"""
    move_id = action.move_id if action.move_id is not None else "none"
    return f"{action.side}:{action.action_type}:{move_id}"


def _group_key_for_edge(
    edge: StateGraphEdge,
    *,
    has_strategy_branch: bool,
) -> _TransitionGroupKey:
    """为没有完整联合行动事件的旧图选择首个真实分叉机制。"""
    if has_strategy_branch:
        return _TransitionGroupKey(
            kind=TransitionGroupKind.ACTION_SELECTION,
            discriminator="policy-selection",
        )

    first_events = {
        first
        for path in edge.event_summary.paths
        if (first := _first_random_event(path)) is not None
    }
    if len(first_events) == 1:
        event_type, event_id = next(iter(first_events))
        return _TransitionGroupKey(
            kind=_group_kind_for_event_type(event_type),
            discriminator=event_id,
        )
    if first_events:
        discriminator = "|".join(
            f"{event_type.value}:{event_id}"
            for event_type, event_id in sorted(
                first_events,
                key=lambda value: (value[0].value, value[1]),
            )
        )
        return _TransitionGroupKey(
            kind=TransitionGroupKind.COMPOSITE,
            discriminator=discriminator,
        )
    return _TransitionGroupKey(
        kind=TransitionGroupKind.COMPOSITE,
        discriminator=edge.source_key or "deterministic-transition",
    )


def _project_group(
    *,
    node: StateGraphNode,
    accumulator: _TransitionGroupAccumulator,
    cumulative_probability: Fraction,
    expanded_group_ids: frozenset[str],
) -> TransitionGroup:
    """把一个联合行动或兼容机制组投影为摘要和按需随机 outcomes。"""
    contributions = tuple(
        sorted(
            accumulator.contributions,
            key=lambda contribution: int(contribution.edge.edge_id),
        )
    )
    group_id = _group_id(node.node_id, accumulator.key)
    is_joint_action = accumulator.key.attacker_action is not None
    if is_joint_action:
        selection_probabilities = _stable_unique(
            contribution.selection_probability for contribution in contributions
        )
        if len(selection_probabilities) != 1:
            raise StateGraphProjectionError(
                "one joint action group must use one selection probability"
            )
        selection_probability = selection_probabilities[0]
        random_total = sum(
            (contribution.random_probability for contribution in contributions),
            start=Fraction(0, 1),
        )
        if random_total != 1:
            raise StateGraphProjectionError(
                "conditional random outcomes of one joint action must sum exactly to 1"
            )
        outcome_probabilities = tuple(
            contribution.random_probability for contribution in contributions
        )
    else:
        selection_probability = sum(
            (contribution.edge.probability for contribution in contributions),
            start=Fraction(0, 1),
        )
        outcome_probabilities = tuple(
            contribution.edge.probability / selection_probability
            for contribution in contributions
        )

    damage_rolls = tuple(
        damage
        for contribution in contributions
        for path in contribution.paths
        for damage in _damage_random_metadata(
            node=node,
            random_events=tuple(
                event
                for event in path
                if not isinstance(event, BattleEvent)
                and not is_joint_action_probability_event(event)
            ),
            battle_events=tuple(
                event for event in path if isinstance(event, BattleEvent)
            ),
        )
    )
    expanded = group_id in expanded_group_ids
    outcomes = (
        tuple(
            _project_outcome(
                node=node,
                contribution=contribution,
                selection_probability=selection_probability,
                random_probability=random_probability,
                cumulative_probability=cumulative_probability,
            )
            for contribution, random_probability in zip(
                contributions, outcome_probabilities, strict=True
            )
        )
        if expanded
        else ()
    )
    probability = ProbabilityProjection.from_fraction(selection_probability)
    return TransitionGroup(
        group_id=group_id,
        kind=accumulator.key.kind,
        label_key=_GROUP_LABEL_KEYS[accumulator.key.kind],
        probability=probability,
        selection_probability=probability,
        attacker_action=accumulator.key.attacker_action,
        defender_action=accumulator.key.defender_action,
        raw_result_count=sum(len(contribution.paths) for contribution in contributions),
        distinct_outcome_count=len(contributions),
        summary=_group_summary(damage_rolls),
        expanded=expanded,
        outcomes=outcomes,
    )


def _project_outcome(
    *,
    node: StateGraphNode,
    contribution: _TransitionContribution,
    selection_probability: Fraction,
    random_probability: Fraction,
    cumulative_probability: Fraction,
) -> TransitionOutcome:
    """投影联合行动下一个按目标 StateKey 归并的条件随机 outcome。"""
    event_paths = tuple(
        _event_path_detail(node=node, path=path) for path in contribution.paths
    )
    random_results = _stable_unique(
        result for path in event_paths for result in path.random_results
    )
    damage_rolls = tuple(
        damage for path in event_paths for damage in path.damage_rolls
    )
    battle_event_paths = tuple(path.battle_events for path in event_paths)
    joint_probability = selection_probability * random_probability
    return TransitionOutcome(
        edge_id=int(contribution.edge.edge_id),
        target_node_id=int(contribution.edge.target_node_id),
        probability=ProbabilityProjection.from_fraction(random_probability),
        joint_probability=ProbabilityProjection.from_fraction(joint_probability),
        cumulative_probability=ProbabilityProjection.from_fraction(
            cumulative_probability * joint_probability
        ),
        label_fields=_label_fields(event_paths),
        raw_random_values=_stable_unique(
            damage.raw_roll_value for damage in damage_rolls
        ),
        random_results=random_results,
        damage_rolls=damage_rolls,
        compact_results=_compact_random_results(
            node=node,
            paths=contribution.paths,
            target_node_id=int(contribution.edge.target_node_id),
        ),
        battle_event_paths=battle_event_paths,
        event_paths=event_paths,
    )


def _event_path_detail(
    *,
    node: StateGraphNode,
    path: tuple[TransitionEvent, ...],
) -> TransitionEventPathDetail:
    """投影一条替代路径中的随机结果、伤害事实和业务事件。

    Args:
        node: 路径发生前的 source node。
        path: ``TransitionEventSummary`` 保存的一条不可变原始事件路径。

    Returns:
        保持原顺序且不引用 domain 对象的路径 DTO。
    """
    random_events = tuple(
        event
        for event in path
        if not isinstance(event, BattleEvent)
        and not is_joint_action_probability_event(event)
    )
    battle_events = tuple(
        event
        for event in path
        if isinstance(event, BattleEvent)
    )
    return TransitionEventPathDetail(
        random_results=tuple(_random_result_detail(event) for event in random_events),
        damage_rolls=_damage_random_metadata(
            node=node,
            random_events=random_events,
            battle_events=battle_events,
        ),
        battle_events=tuple(_battle_event_detail(event) for event in battle_events),
    )


def _compact_random_results(
    *,
    node: StateGraphNode,
    paths: tuple[tuple[TransitionEvent, ...], ...],
    target_node_id: int,
) -> tuple[CompactRandomResult, ...]:
    """按行动执行、离散伤害和状态效果归并事件路径。"""
    accumulators: dict[
        tuple[
            tuple[ActionResolutionDetail, ...],
            str,
            bool | None,
            tuple[int, ...],
            tuple[int, ...],
            tuple[StatusEffectSummary, ...],
            int,
        ],
        tuple[list[int], int],
    ] = {}
    for path in paths:
        random_events = tuple(
            event
            for event in path
            if not isinstance(event, BattleEvent)
            and not is_joint_action_probability_event(event)
        )
        battle_events = tuple(
            event for event in path if isinstance(event, BattleEvent)
        )
        damage_rolls = _damage_random_metadata(
            node=node,
            random_events=random_events,
            battle_events=battle_events,
        )
        action_resolutions = _action_resolution_details(
            random_events=random_events,
            battle_events=battle_events,
        )
        order_reason = (
            "speed-tie-random"
            if any(
                event.event_type is TransitionEventType.SPEED_TIE
                for event in random_events
            )
            else "priority-modifier-speed"
        )
        critical_hit = _critical_hit_result(random_events)
        final_damage_values = tuple(
            metadata.final_damage for metadata in damage_rolls
        )
        actual_hp_losses = tuple(
            metadata.actual_hp_loss for metadata in damage_rolls
        )
        status_effects = _status_effect_summaries(battle_events)
        key = (
            action_resolutions,
            order_reason,
            critical_hit,
            final_damage_values,
            actual_hp_losses,
            status_effects,
            target_node_id,
        )
        raw_values = [metadata.raw_roll_value for metadata in damage_rolls]
        existing = accumulators.get(key)
        if existing is None:
            accumulators[key] = (raw_values, 1)
            continue
        merged_raw_values, path_count = existing
        for raw_value in raw_values:
            if raw_value not in merged_raw_values:
                merged_raw_values.append(raw_value)
        accumulators[key] = (merged_raw_values, path_count + 1)

    return tuple(
        CompactRandomResult(
            target_node_id=key[6],
            action_resolutions=key[0],
            order_reason=key[1],
            critical_hit=key[2],
            raw_roll_values=tuple(raw_values),
            final_damage_values=key[3],
            actual_hp_losses=key[4],
            status_effects=key[5],
            path_count=path_count,
        )
        for key, (raw_values, path_count) in accumulators.items()
    )


def _action_resolution_details(
    *,
    random_events: tuple[TransitionEvent, ...],
    battle_events: tuple[BattleEvent, ...],
) -> tuple[ActionResolutionDetail, ...]:
    """从结构化事件推导双方最终顺序、命中、阻断和濒死取消结果。"""
    selected = tuple(
        event
        for event in battle_events
        if event.kind is BattleEventKind.MOVE_SELECTED and event.actor is not None
    )
    order_positions = {
        event.actor.value: event.value
        for event in battle_events
        if event.kind is BattleEventKind.ACTION_ORDERED
        and event.actor is not None
        and event.value is not None
    }
    used_sides = {
        event.actor.value
        for event in battle_events
        if event.kind is BattleEventKind.MOVE_USED and event.actor is not None
    }
    blocked_reasons = {
        event.actor.value: event.source_identifier or "action-blocked"
        for event in battle_events
        if event.kind is BattleEventKind.ACTION_BLOCKED and event.actor is not None
    }
    hit_results: dict[str, bool] = {}
    for event in battle_events:
        if event.actor is None:
            continue
        if event.kind is BattleEventKind.HIT:
            hit_results[event.actor.value] = True
        elif event.kind is BattleEventKind.MISS:
            hit_results[event.actor.value] = False
    fainted_sides = {
        event.actor.value
        for event in battle_events
        if event.kind is BattleEventKind.FAINTED and event.actor is not None
    }

    details: list[ActionResolutionDetail] = []
    for event in selected:
        side = event.actor.value if event.actor is not None else "unknown"
        action_type = event.source_identifier or "unknown"
        reason: str | None = None
        if action_type == "pass":
            status = "passed"
        elif side in used_sides:
            status = "executed"
        elif side in blocked_reasons:
            status = "blocked"
            reason = blocked_reasons[side]
        else:
            status = "cancelled"
            reason = (
                "fainted-before-action"
                if side in fainted_sides
                else "battle-ended-before-action"
                if fainted_sides
                else "not-executed"
            )
        details.append(
            ActionResolutionDetail(
                side=side,
                move_id=event.move_id,
                action_type=action_type,
                order_position=order_positions.get(side),
                status=status,
                hit=hit_results.get(side),
                reason=reason,
            )
        )
    return tuple(
        sorted(
            details,
            key=lambda detail: (
                detail.order_position is None,
                detail.order_position or 0,
                detail.side,
            ),
        )
    )


def _critical_hit_result(
    random_events: tuple[TransitionEvent, ...],
) -> bool | None:
    """从已存在的随机结果标识读取暴击语义；尚未建模时保持 None。"""
    tokens = tuple(
        f"{event.event_id}:{event.outcome_id}".lower() for event in random_events
    )
    if any("non-critical" in token or "no-crit" in token for token in tokens):
        return False
    if any("critical" in token or ":crit" in token for token in tokens):
        return True
    return None


def _status_effect_summaries(
    battle_events: tuple[BattleEvent, ...],
) -> tuple[StatusEffectSummary, ...]:
    """收集状态施加与阻止事实，忽略与状态无关的战报事件。"""
    return tuple(
        StatusEffectSummary(
            result=(
                "applied"
                if event.kind is BattleEventKind.STATUS_APPLIED
                else "prevented"
            ),
            source_side=event.actor.value if event.actor is not None else None,
            target_side=event.target.value if event.target is not None else None,
            source_identifier=event.source_identifier,
        )
        for event in battle_events
        if event.kind
        in {BattleEventKind.STATUS_APPLIED, BattleEventKind.STATUS_PREVENTED}
    )


def _damage_random_metadata(
    *,
    node: StateGraphNode,
    random_events: tuple[TransitionEvent, ...],
    battle_events: tuple[BattleEvent, ...],
) -> tuple[DamageRandomMetadata, ...]:
    """把伤害档位事件与随后记录的实际 HP loss 按发生顺序配对。

    Args:
        node: 伤害发生前的 source node，包含当前规则集的随机倍率序列。
        random_events: 当前替代路径中的非业务随机事件。
        battle_events: 当前替代路径中的结构化业务事件。

    Returns:
        每个合法 ``DAMAGE_ROLL`` 对应一项规则值、最终伤害和实际 HP loss。旧的非标准
        outcome ID 无法稳定定位规则档位时仍保留 ``random_results``，但不伪造伤害元数据。
    """
    damage_events = tuple(
        event
        for event in random_events
        if event.event_type is TransitionEventType.DAMAGE_ROLL
        and event.numeric_value is not None
    )
    actual_losses = tuple(
        event.value
        for event in battle_events
        if event.kind is BattleEventKind.DAMAGE
        and event.value is not None
        and event.source_identifier != "struggle-recoil"
    )
    multipliers = node.state.rules.damage_policy.random_damage_multipliers
    metadata: list[DamageRandomMetadata] = []
    for event_index, event in enumerate(damage_events):
        raw_roll_index = _raw_roll_index(event.outcome_id)
        if raw_roll_index is None or raw_roll_index >= len(multipliers):
            continue
        final_damage = event.numeric_value
        if final_damage is None:
            continue
        actual_hp_loss = (
            actual_losses[event_index]
            if event_index < len(actual_losses)
            else final_damage
        )
        metadata.append(
            DamageRandomMetadata(
                raw_roll_index=raw_roll_index,
                raw_roll_value=int(round(multipliers[raw_roll_index] * 100)),
                final_damage=final_damage,
                actual_hp_loss=actual_hp_loss,
            )
        )
    return tuple(metadata)


def _raw_roll_index(outcome_id: str) -> int | None:
    """从 domain 伤害事件的稳定 outcome ID 读取从 0 开始的档位索引。

    Args:
        outcome_id: ``damage_rolls_to_transitions`` 生成的 ``roll-{index}`` 标识。

    Returns:
        合法非负索引；其他自定义伤害事件返回 None，避免 projection 猜测规则值。
    """
    prefix = "roll-"
    if not outcome_id.startswith(prefix):
        return None
    raw_index = outcome_id[len(prefix) :]
    if not raw_index.isdecimal():
        return None
    return int(raw_index)


def _random_result_detail(event: TransitionEvent) -> RandomResultDetail:
    """把一条非业务随机事件转换为稳定基础字段 DTO。"""
    return RandomResultDetail(
        event_type=event.event_type.value,
        event_id=event.event_id,
        outcome_id=event.outcome_id,
        numeric_value=event.numeric_value,
    )


def _battle_event_detail(event: BattleEvent) -> BattleEventDetail:
    """把一条结构化业务事件转换为稳定基础字段 DTO。"""
    return BattleEventDetail(
        kind=event.kind.value,
        turn_number=event.turn_number,
        actor=event.actor.value if event.actor is not None else None,
        target=event.target.value if event.target is not None else None,
        move_id=event.move_id,
        source_identifier=event.source_identifier,
        value=event.value,
        before_value=event.before_value,
        after_value=event.after_value,
    )


def _label_fields(
    paths: tuple[TransitionEventPathDetail, ...],
) -> TransitionLabelFields:
    """从全部替代路径收集 presenter 可稳定使用的去重标签字段。"""
    battle_events = tuple(
        event
        for path in paths
        for event in path.battle_events
    )
    return TransitionLabelFields(
        selected_move_ids=_stable_unique(
            event.move_id
            for event in battle_events
            if event.kind == BattleEventKind.MOVE_SELECTED.value
            and event.move_id is not None
        ),
        acting_sides=_stable_unique(
            event.actor
            for event in battle_events
            if event.actor is not None
        ),
        target_sides=_stable_unique(
            event.target
            for event in battle_events
            if event.target is not None
        ),
        result_keys=_stable_unique(
            result.outcome_id
            for path in paths
            for result in path.random_results
        ),
        source_identifiers=_stable_unique(
            event.source_identifier
            for event in battle_events
            if event.source_identifier is not None
        ),
    )


def _selection_signature(
    path: tuple[TransitionEvent, ...],
) -> tuple[tuple[str | None, int | None, str | None], ...]:
    """读取一条完整回合路径中双方稳定选招组合。"""
    return tuple(
        (
            event.actor.value if event.actor is not None else None,
            event.move_id,
            event.source_identifier,
        )
        for event in path
        if isinstance(event, BattleEvent)
        and event.kind is BattleEventKind.MOVE_SELECTED
    )


def _first_random_event(
    path: tuple[TransitionEvent, ...],
) -> tuple[TransitionEventType, str] | None:
    """返回一条路径中首个非 ``BattleEvent`` 随机机制及其来源。"""
    for event in path:
        if isinstance(event, BattleEvent):
            continue
        if event.event_type is TransitionEventType.CUSTOM:
            continue
        return (event.event_type, event.event_id)
    return None


def _group_kind_for_event_type(
    event_type: TransitionEventType,
) -> TransitionGroupKind:
    """把 domain 随机事件类别显式映射为 application 分支组类别。"""
    match event_type:
        case TransitionEventType.SPEED_TIE:
            return TransitionGroupKind.ACTION_ORDER
        case TransitionEventType.HIT_CHECK:
            return TransitionGroupKind.HIT_CHECK
        case TransitionEventType.DAMAGE_ROLL:
            return TransitionGroupKind.DAMAGE_DISTRIBUTION
        case TransitionEventType.SECONDARY_EFFECT:
            return TransitionGroupKind.SECONDARY_EFFECT
        case TransitionEventType.CUSTOM:
            return TransitionGroupKind.COMPOSITE
    return TransitionGroupKind.COMPOSITE


def _group_id(node_id: GraphNodeId, key: _TransitionGroupKey) -> str:
    """根据 source node、类别和随机来源生成稳定且 URL 友好的 group ID。"""
    payload = f"{int(node_id)}|{key.kind.value}|{key.discriminator}"
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"tg-{int(node_id)}-{key.kind.value}-{digest}"


def _group_summary(
    damage_rolls: tuple[DamageRandomMetadata, ...],
) -> TransitionGroupSummary:
    """根据组内全部原始伤害路径构造可选最小/最大值摘要。"""
    if not damage_rolls:
        return TransitionGroupSummary(
            minimum_damage=None,
            maximum_damage=None,
            minimum_hp_loss=None,
            maximum_hp_loss=None,
        )
    damages = tuple(metadata.final_damage for metadata in damage_rolls)
    hp_losses = tuple(metadata.actual_hp_loss for metadata in damage_rolls)
    return TransitionGroupSummary(
        minimum_damage=min(damages),
        maximum_damage=max(damages),
        minimum_hp_loss=min(hp_losses),
        maximum_hp_loss=max(hp_losses),
    )


def _normalize_group_ids(group_ids: Iterable[str]) -> frozenset[str]:
    """冻结待展开 group ID，并拒绝空白或非字符串值。"""
    normalized = frozenset(group_ids)
    if any(
        not isinstance(group_id, str)
        or not group_id
        or group_id != group_id.strip()
        for group_id in normalized
    ):
        raise StateGraphProjectionError(
            "expanded_group_ids must contain normalized non-empty strings"
        )
    return normalized


def _stable_unique(values: Iterable[object]) -> tuple:
    """按首次出现顺序冻结可哈希值，并避免 set 打乱 presenter 顺序。"""
    result: list[object] = []
    seen: set[object] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _enum_value(value: Enum | None) -> str | None:
    """读取枚举稳定值；None 保持为空，避免 DTO 泄漏枚举对象。"""
    if value is None:
        return None
    return str(value.value)


_GROUP_LABEL_KEYS: dict[TransitionGroupKind, str] = {
    TransitionGroupKind.ACTION_SELECTION: "battle.transition.action-selection",
    TransitionGroupKind.ACTION_ORDER: "battle.transition.action-order",
    TransitionGroupKind.HIT_CHECK: "battle.transition.hit-check",
    TransitionGroupKind.DAMAGE_DISTRIBUTION: "battle.transition.damage-distribution",
    TransitionGroupKind.SECONDARY_EFFECT: "battle.transition.secondary-effect",
    TransitionGroupKind.COMPOSITE: "battle.transition.composite",
}

_GROUP_KIND_ORDER: dict[TransitionGroupKind, int] = {
    TransitionGroupKind.ACTION_SELECTION: 0,
    TransitionGroupKind.ACTION_ORDER: 1,
    TransitionGroupKind.HIT_CHECK: 2,
    TransitionGroupKind.DAMAGE_DISTRIBUTION: 3,
    TransitionGroupKind.SECONDARY_EFFECT: 4,
    TransitionGroupKind.COMPOSITE: 5,
}


__all__ = [
    "BattleEventDetail",
    "ActionResolutionDetail",
    "BattleFieldDetail",
    "BattleNodeDetail",
    "BattleNodeProjection",
    "BattlerDetail",
    "CompactRandomResult",
    "DamageRandomMetadata",
    "JointActionDetail",
    "MoveSlotDetail",
    "ProbabilityProjection",
    "RandomResultDetail",
    "SideConditionsDetail",
    "StateGraphProjectionError",
    "StateGraphProjectionUseCase",
    "StatStagesDetail",
    "StatusDetail",
    "StatusEffectSummary",
    "TransitionEventPathDetail",
    "TransitionGroup",
    "TransitionGroupKind",
    "TransitionGroupSummary",
    "TransitionLabelFields",
    "TransitionOutcome",
]
