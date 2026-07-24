from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphEdge,
    StateGraphNode,
    StateGraphStatistics,
    StateGraphTerminalCounts,
)
from pokeop.application.state_graph_projection import (
    ProbabilityProjection,
    StateGraphProjectionUseCase,
    TransitionGroupKind,
)
from pokeop.application.state_graph_exploration import StateGraphExplorationUseCase
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide, TerminationReason
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.state import (
    BattleFieldState,
    BattlePhase,
    BattleState,
    StatStages,
)
from pokeop.domain.battle.status.state import (
    CombatantStatus,
    ConfusionStatus,
    FlinchStatus,
    SleepStatus,
)
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
)
from pokeop.domain.battle.weather import Weather
from tests.domain.battle.effect_test_helpers import build_effect_test_battle_state


def _node(
    node_id: int,
    state: BattleState,
    *,
    outcome: GraphNodeOutcome = GraphNodeOutcome.NON_TERMINAL,
    termination_reason: TerminationReason | None = None,
) -> StateGraphNode:
    """构造使用真实 ``BattleState`` 的连续状态图节点。

    Args:
        node_id: 当前测试图中的从 0 开始连续节点 ID。
        state: 当前节点完整不可变战斗状态。
        outcome: 当前节点终局分类。
        termination_reason: 终局节点的稳定结束原因。

    Returns:
        使用 ``state.state_key`` 参与语义归并的正式图节点。
    """
    return StateGraphNode(
        node_id=GraphNodeId(node_id),
        state=state,
        state_key=state.state_key,
        outcome=outcome,
        termination_reason=termination_reason,
    )


def _edge(
    edge_id: int,
    source_node_id: int,
    target_node_id: int,
    probability: Fraction,
    paths: tuple[tuple[TransitionEvent, ...], ...],
    *,
    source_key: str | None = None,
) -> StateGraphEdge:
    """构造一条带精确概率和原始替代事件路径的正式图边。

    Args:
        edge_id: 当前测试图中的连续边 ID。
        source_node_id: 边起点节点 ID。
        target_node_id: 边终点节点 ID。
        probability: 已按相同后继状态归并后的局部精确概率。
        paths: 到达该后继节点的一条或多条原始事件路径。
        source_key: 可选的稳定解释来源键。

    Returns:
        可供 application projection 读取的不可变状态图边。
    """
    return StateGraphEdge(
        edge_id=GraphEdgeId(edge_id),
        source_node_id=GraphNodeId(source_node_id),
        target_node_id=GraphNodeId(target_node_id),
        probability=probability,
        event_summary=TransitionEventSummary(paths),
        source_key=source_key,
    )


def _graph(
    nodes: tuple[StateGraphNode, ...],
    edges: tuple[StateGraphEdge, ...],
) -> StateGraphBuildResult:
    """构造 projection 测试所需的最小完整图 artifact。

    Args:
        nodes: 按 node ID 连续排列的正式节点。
        edges: 按 edge ID 连续排列的正式边。

    Returns:
        不包含 SCC 详情、但统计字段与节点分类一致的完整图结果。
    """
    attacker_wins = sum(
        node.outcome is GraphNodeOutcome.ATTACKER_WIN for node in nodes
    )
    defender_wins = sum(
        node.outcome is GraphNodeOutcome.DEFENDER_WIN for node in nodes
    )
    draws = sum(node.outcome is GraphNodeOutcome.DRAW for node in nodes)
    non_terminal = sum(
        node.outcome is GraphNodeOutcome.NON_TERMINAL for node in nodes
    )
    unknown = sum(node.outcome is GraphNodeOutcome.UNKNOWN for node in nodes)
    return StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=nodes,
        edges=edges,
        components=(),
        statistics=StateGraphStatistics(
            unique_state_count=len(nodes),
            edge_count=len(edges),
            max_turn_number=max(node.state.turn_number for node in nodes),
            terminal_counts=StateGraphTerminalCounts(
                attacker_wins=attacker_wins,
                defender_wins=defender_wins,
                draws=draws,
                non_terminal=non_terminal,
                unknown=unknown,
            ),
            closed_cycle_count=0,
            terminal_reachable_cycle_count=0,
        ),
    )


def _damage_path(
    *,
    roll_index: int,
    final_damage: int,
    actual_hp_loss: int,
    event_id: str = "turn-1-attacker-move-418-damage",
) -> tuple[TransitionEvent, ...]:
    """构造一条包含原始伤害档、最终伤害和实际 HP loss 的路径。

    Args:
        roll_index: 当前规则集随机档位的从 0 开始索引。
        final_damage: 伤害公式与修正链计算后的最终伤害。
        actual_hp_loss: HP 下限截断后真实扣除值。
        event_id: 同一伤害随机事件的稳定来源标识。

    Returns:
        先记录随机档位、再记录结构化 DAMAGE 事实的事件路径。
    """
    return (
        TransitionEvent(
            event_type=TransitionEventType.DAMAGE_ROLL,
            event_id=event_id,
            outcome_id=f"roll-{roll_index}",
            numeric_value=final_damage,
        ),
        BattleEvent(
            kind=BattleEventKind.DAMAGE,
            turn_number=1,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
            move_id=418,
            source_identifier="move",
            value=actual_hp_loss,
        ),
    )


def _state_with_defender_hp(state: BattleState, hp: int) -> BattleState:
    """返回只替换防守方当前 HP 的不可变测试节点。"""
    return state.with_battler(
        BattleSide.DEFENDER,
        state.defender.with_current_hp(hp),
    )


def test_node_detail_projects_complete_json_friendly_battle_state() -> None:
    """节点详情测试使用真实巨钳螳螂与仙子伊布状态，在攻击方同时存在剩余 PP、禁用、讲究锁招、睡眠、混乱、畏缩、能力等级、上一招和非首回合标记，并在场地上设置天气、场地与双方屏障。投影必须完整保留这些会影响后续推演的事实，同时只返回字符串、整数、布尔值和 application DTO，不能把 BattleState、枚举或状态对象直接交给前端。"""
    state = build_effect_test_battle_state()
    attacker = state.attacker.with_choice_lock(418)
    attacker = attacker.with_move_slot(
        attacker.move_slot(418).with_current_pp(12).with_disabled()
    )
    attacker = replace(
        attacker,
        current_hp=123,
        stat_stages=StatStages(attack=2, defense=-1, speed=1),
        status=CombatantStatus(
            non_volatile=SleepStatus(turns_asleep=2),
            volatile=frozenset(
                (
                    ConfusionStatus(turns_remaining=3),
                    FlinchStatus(),
                )
            ),
        ),
        last_move_id=418,
        is_first_turn=False,
    )
    state = replace(
        state,
        attacker=attacker,
        field=BattleFieldState(
            weather=Weather.RAIN,
            terrain=Terrain.ELECTRIC,
            attacker_side_conditions=SideConditions(reflect=True),
            defender_side_conditions=SideConditions(
                light_screen=True,
                aurora_veil=True,
            ),
        ),
    )
    graph = _graph((_node(0, state),), ())
    explorer = StateGraphExplorationUseCase(graph_id="graph-detail", graph=graph)

    projection = StateGraphProjectionUseCase(
        graph_id="graph-detail",
        graph=graph,
    ).project_cursor(explorer.create_root_cursor())

    assert projection.node.node_id == 0
    assert projection.node.turn_number == 1
    assert projection.node.phase == "action-selection"
    assert projection.node.outcome == "non-terminal"
    assert projection.node.termination_reason is None
    assert projection.node.terminal is False
    assert projection.node.has_outgoing_edges is False
    assert projection.node.attacker.current_hp == 123
    assert projection.node.attacker.max_hp == 177
    assert projection.node.attacker.ability == "technician"
    assert projection.node.attacker.item == "choice_band"
    assert projection.node.attacker.moves[0].current_pp == 12
    assert projection.node.attacker.moves[0].disabled is True
    assert projection.node.attacker.moves[0].locked is True
    assert projection.node.attacker.major_status is not None
    assert projection.node.attacker.major_status.kind == "sleep"
    assert projection.node.attacker.major_status.turns_asleep == 2
    assert tuple(
        status.kind for status in projection.node.attacker.volatile_statuses
    ) == ("confusion", "flinch")
    assert projection.node.attacker.stat_stages.attack == 2
    assert projection.node.attacker.stat_stages.defense == -1
    assert projection.node.attacker.last_move_id == 418
    assert projection.node.attacker.choice_lock_move_id == 418
    assert projection.node.attacker.item_consumed is False
    assert projection.node.attacker.first_turn is False
    assert projection.node.field.weather == "rain"
    assert projection.node.field.terrain == "electric_terrain"
    assert projection.node.field.attacker_side_conditions.reflect is True
    assert projection.node.field.defender_side_conditions.light_screen is True
    assert projection.node.field.defender_side_conditions.aurora_veil is True
    assert projection.cumulative_probability.numerator == "1"
    assert projection.cumulative_probability.denominator == "1"
    assert projection.transition_groups == ()


def test_probability_projection_keeps_large_fraction_strings_js_safe() -> None:
    """精确概率合同使用远超 JavaScript Number 安全整数上限的分子和分母构造 Fraction，并要求 application 输出约分后的十进制字符串。decimal 与 percent 只承担展示近似值，不能替代字符串分子分母；因此测试同时验证大整数没有经过 float 往返、字符串与 Fraction 精确值一致，并确认百分比仍可供普通界面排序和快速展示。"""
    probability = Fraction((2**80) + 7, (2**96) + 33)

    projection = ProbabilityProjection.from_fraction(probability)

    assert projection.numerator == str(probability.numerator)
    assert projection.denominator == str(probability.denominator)
    assert projection.decimal == float(probability)
    assert projection.percent == float(probability) * 100
    assert int(projection.numerator) > 2**53
    assert int(projection.denominator) > 2**53


def test_sixteen_distinct_damage_rolls_form_one_collapsed_damage_group() -> None:
    """标准现代规则的 16 个伤害随机档分别到达 16 个不同 HP 节点，图中因此存在 16 条正式出边。application 必须把它们收敛为一个默认折叠的 DAMAGE_DISTRIBUTION 组，而不是让前端直接渲染 16 个兄弟节点；展开该组后仍应得到 16 个 outcome，并由 source node 的 DamagePolicy 明确投影 85 到 100 的原始随机值、最终伤害、实际 HP loss 和精确局部概率。"""
    source = build_effect_test_battle_state()
    damages = tuple(range(10, 26))
    target_states = tuple(
        _state_with_defender_hp(source, source.defender.current_hp - damage)
        for damage in damages
    )
    nodes = (_node(0, source),) + tuple(
        _node(index, state)
        for index, state in enumerate(target_states, start=1)
    )
    edges = tuple(
        _edge(
            index,
            0,
            index + 1,
            Fraction(1, 16),
            (
                _damage_path(
                    roll_index=index,
                    final_damage=damage,
                    actual_hp_loss=damage,
                ),
            ),
            source_key="damage.random-roll",
        )
        for index, damage in enumerate(damages)
    )
    graph = _graph(nodes, edges)
    use_case = StateGraphProjectionUseCase(graph_id="graph-distinct", graph=graph)

    collapsed = use_case.project_node(GraphNodeId(0))

    assert len(collapsed.transition_groups) == 1
    group = collapsed.transition_groups[0]
    assert group.kind is TransitionGroupKind.DAMAGE_DISTRIBUTION
    assert group.label_key == "battle.transition.damage-distribution"
    assert group.probability.numerator == "1"
    assert group.probability.denominator == "1"
    assert group.raw_result_count == 16
    assert group.distinct_outcome_count == 16
    assert group.expanded is False
    assert group.outcomes == ()
    assert group.summary.minimum_damage == 10
    assert group.summary.maximum_damage == 25
    assert group.summary.minimum_hp_loss == 10
    assert group.summary.maximum_hp_loss == 25

    expanded = use_case.project_node(
        GraphNodeId(0),
        expanded_group_ids=(group.group_id,),
    ).transition_groups[0]

    assert expanded.expanded is True
    assert len(expanded.outcomes) == 16
    assert {
        raw_value
        for outcome in expanded.outcomes
        for raw_value in outcome.raw_random_values
    } == set(range(85, 101))
    assert all(outcome.probability.numerator == "1" for outcome in expanded.outcomes)
    assert all(outcome.probability.denominator == "16" for outcome in expanded.outcomes)
    assert all(
        outcome.cumulative_probability.denominator == "16"
        for outcome in expanded.outcomes
    )


def test_rounded_duplicate_rolls_keep_four_raw_paths_but_two_outcomes() -> None:
    """该场景模拟四个原始随机值在伤害取整后只形成 10 与 11 两种最终伤害，因此 domain 图已经把相同后继状态的两个档位各自归并到同一条边。projection 必须报告 raw_result_count 为 4、distinct_outcome_count 为 2，并在两个 outcome 内分别保留 85/86 与 87/88；同时从给定 3/5 游标概率继续乘以局部 1/2，得到精确 3/10 累计概率。"""
    source = build_effect_test_battle_state()
    damage_ten = _state_with_defender_hp(source, source.defender.current_hp - 10)
    damage_eleven = _state_with_defender_hp(source, source.defender.current_hp - 11)
    graph = _graph(
        (
            _node(0, source),
            _node(1, damage_ten),
            _node(2, damage_eleven),
        ),
        (
            _edge(
                0,
                0,
                1,
                Fraction(1, 2),
                (
                    _damage_path(
                        roll_index=0,
                        final_damage=10,
                        actual_hp_loss=10,
                    ),
                    _damage_path(
                        roll_index=1,
                        final_damage=10,
                        actual_hp_loss=10,
                    ),
                ),
            ),
            _edge(
                1,
                0,
                2,
                Fraction(1, 2),
                (
                    _damage_path(
                        roll_index=2,
                        final_damage=11,
                        actual_hp_loss=11,
                    ),
                    _damage_path(
                        roll_index=3,
                        final_damage=11,
                        actual_hp_loss=11,
                    ),
                ),
            ),
        ),
    )
    use_case = StateGraphProjectionUseCase(graph_id="graph-rounded", graph=graph)
    collapsed = use_case.project_node(
        GraphNodeId(0),
        cumulative_probability=Fraction(3, 5),
    )
    group_id = collapsed.transition_groups[0].group_id

    group = use_case.project_node(
        GraphNodeId(0),
        cumulative_probability=Fraction(3, 5),
        expanded_group_ids=(group_id,),
    ).transition_groups[0]

    assert group.raw_result_count == 4
    assert group.distinct_outcome_count == 2
    assert tuple(outcome.raw_random_values for outcome in group.outcomes) == (
        (85, 86),
        (87, 88),
    )
    assert all(
        outcome.cumulative_probability.numerator == "3"
        and outcome.cumulative_probability.denominator == "10"
        for outcome in group.outcomes
    )
    assert tuple(
        tuple(metadata.final_damage for metadata in outcome.damage_rolls)
        for outcome in group.outcomes
    ) == ((10, 10), (11, 11))


def test_all_knockout_rolls_merge_to_one_outcome_and_preserve_actual_hp_loss() -> None:
    """防守方只剩 5 HP，而 16 个最终伤害档从 5 递增到 20，所有路径都会到达同一个 0 HP 终局节点。状态图只应保留一条概率为 1 的边，projection 也只生成一个 outcome，但必须继续保留 16 条原始 roll metadata；每条 metadata 的 final_damage 各不相同，actual_hp_loss 却都严格等于 5，从而明确区分公式伤害与 HP 下限截断后的真实扣血。"""
    initial = build_effect_test_battle_state()
    source = _state_with_defender_hp(initial, 5)
    fainted = _state_with_defender_hp(source, 0).with_phase(BattlePhase.TERMINAL)
    paths = tuple(
        _damage_path(
            roll_index=index,
            final_damage=damage,
            actual_hp_loss=5,
        )
        for index, damage in enumerate(range(5, 21))
    )
    graph = _graph(
        (
            _node(0, source),
            _node(
                1,
                fainted,
                outcome=GraphNodeOutcome.ATTACKER_WIN,
                termination_reason=TerminationReason.KNOCKOUT,
            ),
        ),
        (_edge(0, 0, 1, Fraction(1, 1), paths),),
    )
    use_case = StateGraphProjectionUseCase(graph_id="graph-ko", graph=graph)
    collapsed_group = use_case.project_node(GraphNodeId(0)).transition_groups[0]

    group = use_case.project_node(
        GraphNodeId(0),
        expanded_group_ids=(collapsed_group.group_id,),
    ).transition_groups[0]
    outcome = group.outcomes[0]

    assert group.raw_result_count == 16
    assert group.distinct_outcome_count == 1
    assert group.summary.minimum_damage == 5
    assert group.summary.maximum_damage == 20
    assert group.summary.minimum_hp_loss == 5
    assert group.summary.maximum_hp_loss == 5
    assert outcome.target_node_id == 1
    assert outcome.probability.numerator == "1"
    assert len(outcome.damage_rolls) == 16
    assert tuple(metadata.raw_roll_value for metadata in outcome.damage_rolls) == tuple(
        range(85, 101)
    )
    assert tuple(metadata.final_damage for metadata in outcome.damage_rolls) == tuple(
        range(5, 21)
    )
    assert {metadata.actual_hp_loss for metadata in outcome.damage_rolls} == {5}


def test_hit_and_miss_share_one_hit_check_group_with_structured_events() -> None:
    """命中路径先记录同一 accuracy event 的 hit 结果，再继续记录伤害档和 DAMAGE/HIT 业务事件；未命中路径只记录同一 accuracy event 的 miss 结果和 MISS 业务事件。虽然命中路径还包含下游伤害随机，两个正式出边的首个分叉机制相同，因此必须形成一个 HIT_CHECK group，展开后得到两个 outcome，并完整保留命中、未命中及伤害事件而不是解析临时文案。"""
    source = build_effect_test_battle_state()
    hit_state = _state_with_defender_hp(source, source.defender.current_hp - 10)
    miss_state = source.with_phase(BattlePhase.END_OF_TURN)
    accuracy_event_id = "turn-1-attacker-move-418-accuracy"
    hit_path = (
        TransitionEvent(
            event_type=TransitionEventType.HIT_CHECK,
            event_id=accuracy_event_id,
            outcome_id="hit",
        ),
        TransitionEvent(
            event_type=TransitionEventType.DAMAGE_ROLL,
            event_id="turn-1-attacker-move-418-damage",
            outcome_id="roll-0",
            numeric_value=10,
        ),
        BattleEvent(
            kind=BattleEventKind.HIT,
            turn_number=1,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
            move_id=418,
            source_identifier="move",
        ),
        BattleEvent(
            kind=BattleEventKind.DAMAGE,
            turn_number=1,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
            move_id=418,
            source_identifier="move",
            value=10,
        ),
    )
    miss_path = (
        TransitionEvent(
            event_type=TransitionEventType.HIT_CHECK,
            event_id=accuracy_event_id,
            outcome_id="miss",
        ),
        BattleEvent(
            kind=BattleEventKind.MISS,
            turn_number=1,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
            move_id=418,
            source_identifier="move",
        ),
    )
    graph = _graph(
        (_node(0, source), _node(1, hit_state), _node(2, miss_state)),
        (
            _edge(0, 0, 1, Fraction(3, 4), (hit_path,)),
            _edge(1, 0, 2, Fraction(1, 4), (miss_path,)),
        ),
    )
    use_case = StateGraphProjectionUseCase(graph_id="graph-accuracy", graph=graph)
    group_id = use_case.project_node(GraphNodeId(0)).transition_groups[0].group_id

    group = use_case.project_node(
        GraphNodeId(0),
        expanded_group_ids=(group_id,),
    ).transition_groups[0]

    assert group.kind is TransitionGroupKind.HIT_CHECK
    assert group.raw_result_count == 2
    assert group.distinct_outcome_count == 2
    assert tuple(outcome.probability.numerator for outcome in group.outcomes) == (
        "3",
        "1",
    )
    assert tuple(outcome.probability.denominator for outcome in group.outcomes) == (
        "4",
        "4",
    )
    assert {
        result.outcome_id
        for outcome in group.outcomes
        for result in outcome.random_results
    } == {"hit", "miss", "roll-0"}
    assert {
        event.kind
        for outcome in group.outcomes
        for path in outcome.battle_event_paths
        for event in path
    } == {"hit", "damage", "miss"}


def test_strategy_selection_variants_take_precedence_over_internal_randomness() -> None:
    """该测试明确使用合成选招事件，只验证 application 的策略分支投影，不声称第二个 move_id 在当前真实配置中合法。两条出边分别记录不同 MOVE_SELECTED 组合，并各自可以携带后续随机事件；由于用户最先需要理解和选择的是行动策略，projection 必须优先形成 ACTION_SELECTION group，保留两个 outcome 的 selected_move_ids，而不能被下游命中或伤害事件错误拆成多个随机组。"""
    source = build_effect_test_battle_state()
    first_target = source.with_phase(BattlePhase.ACTION_RESOLUTION)
    second_target = source.with_phase(BattlePhase.END_OF_TURN)

    def selection_path(move_id: int, outcome_id: str) -> tuple[TransitionEvent, ...]:
        """构造一个选招事实后跟随命中随机结果的合成事件路径。"""
        return (
            BattleEvent(
                kind=BattleEventKind.MOVE_SELECTED,
                turn_number=1,
                actor=BattleSide.ATTACKER,
                target=BattleSide.DEFENDER,
                move_id=move_id,
                source_identifier="move",
            ),
            TransitionEvent(
                event_type=TransitionEventType.HIT_CHECK,
                event_id=f"synthetic-move-{move_id}-accuracy",
                outcome_id=outcome_id,
            ),
        )

    graph = _graph(
        (
            _node(0, source),
            _node(1, first_target),
            _node(2, second_target),
        ),
        (
            _edge(0, 0, 1, Fraction(1, 2), (selection_path(418, "hit"),)),
            _edge(1, 0, 2, Fraction(1, 2), (selection_path(999, "miss"),)),
        ),
    )
    use_case = StateGraphProjectionUseCase(graph_id="graph-policy", graph=graph)
    group_id = use_case.project_node(GraphNodeId(0)).transition_groups[0].group_id

    group = use_case.project_node(
        GraphNodeId(0),
        expanded_group_ids=(group_id,),
    ).transition_groups[0]

    assert group.kind is TransitionGroupKind.ACTION_SELECTION
    assert group.label_key == "battle.transition.action-selection"
    assert group.distinct_outcome_count == 2
    assert tuple(
        outcome.label_fields.selected_move_ids for outcome in group.outcomes
    ) == ((418,), (999,))


def test_mixed_first_random_mechanisms_form_composite_group_and_keep_paths() -> None:
    """同一后继状态由两条替代路径到达：一条首先经历同速顺序随机，另一条首先经历命中判定，二者无法被诚实描述成单一命中、伤害、顺序或附加效果组。projection 应使用 COMPOSITE 作为稳定兜底类别，只生成一个已按后继节点归并的 outcome，并在 event_paths 中分别保留 speed_tie 与 hit_check 原始结果，确保后续 presenter 或调试工具能够看到组合来源而不丢失替代路径。"""
    source = build_effect_test_battle_state()
    target = source.with_phase(BattlePhase.END_OF_TURN)
    graph = _graph(
        (_node(0, source), _node(1, target)),
        (
            _edge(
                0,
                0,
                1,
                Fraction(1, 1),
                (
                    (
                        TransitionEvent(
                            event_type=TransitionEventType.SPEED_TIE,
                            event_id="turn-1-speed-tie",
                            outcome_id="attacker-first",
                        ),
                    ),
                    (
                        TransitionEvent(
                            event_type=TransitionEventType.HIT_CHECK,
                            event_id="turn-1-attacker-accuracy",
                            outcome_id="miss",
                        ),
                    ),
                ),
            ),
        ),
    )
    use_case = StateGraphProjectionUseCase(graph_id="graph-composite", graph=graph)
    group_id = use_case.project_node(GraphNodeId(0)).transition_groups[0].group_id

    group = use_case.project_node(
        GraphNodeId(0),
        expanded_group_ids=(group_id,),
    ).transition_groups[0]
    outcome = group.outcomes[0]

    assert group.kind is TransitionGroupKind.COMPOSITE
    assert group.raw_result_count == 2
    assert group.distinct_outcome_count == 1
    assert len(outcome.event_paths) == 2
    assert tuple(
        path.random_results[0].event_type for path in outcome.event_paths
    ) == ("speed_tie", "hit_check")
    assert tuple(
        path.random_results[0].outcome_id for path in outcome.event_paths
    ) == ("attacker-first", "miss")
