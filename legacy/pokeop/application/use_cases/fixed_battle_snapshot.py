"""按固定配置快照单步展开战斗树，不等待全局异步求解完成。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.application import state_graph_projection as projection
from pokeop.application.configuration_space import ConfigurationSpace
from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphEdge,
    StateGraphNode,
)
from pokeop.application.state_graph_exploration import (
    ExplorationCursor,
    ExplorationPathStep,
)
from pokeop.application.state_graph_projection import ProbabilityProjection
from pokeop.application.use_cases.battle_exploration._support import (
    expand_group,
    list_group_summaries,
)
from pokeop.application.use_cases.battle_exploration.models import (
    BattleExplorationPosition,
    BattleReport,
    BattleReportStep,
    BattleTransitionGroupsResult,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BATTLE_INFERENCE_CALCULATION_REVISION,
    BattleInferenceExecutionError,
    InferFixedOneOnOneBattleCommand,
    InferOneOnOneBattleUseCase,
)
from pokeop.application.use_cases.infer_one_on_one_battle import _core
from pokeop.domain.battle.inference_outcome import TerminationReason
from pokeop.domain.battle.state import BattlePhase, BattleState
from pokeop.domain.battle.transitions import WeightedTransition


SNAPSHOT_GRAPH_ID = "fixed-one-on-one-snapshot"


@dataclass(frozen=True, slots=True)
class FixedBattleSnapshotStepResult:
    """保存一次固定配置快照展开后的树节点、分支和战报。

    Args:
        groups: 当前快照节点的全部分支组；每组都携带 outcomes，前端可本地展开。
        report: 从起点到当前快照的结构化战报。
    """

    groups: BattleTransitionGroupsResult
    report: BattleReport


@dataclass(slots=True)
class ExpandFixedBattleSnapshotUseCase:
    """从固定配置起点重放 cursor，并只展开当前节点的一层可能性。

    该用例不读取、保存或求解完整状态图；每次请求都从根状态重放用户选择过的
    局部 edge 序列，因此可以与后台异步全局胜率任务并行运行。
    """

    inference_use_case: InferOneOnOneBattleUseCase

    def execute(
        self,
        command: InferFixedOneOnOneBattleCommand,
        cursor: ExplorationCursor,
    ) -> FixedBattleSnapshotStepResult:
        """展开 cursor 当前快照的一层分支。

        Args:
            command: 双方固定配置、策略和规则轴。
            cursor: 从起点开始的局部 edge 序列；edge_id 表示当步展开结果序号。

        Returns:
            同形于完整图探索响应的当前节点、分支组和战报。
        """
        configuration_space = self._configuration_space(command)
        configuration = configuration_space.equivalence_classes[0].representative
        expander = _core._PolicyDrivenBattleStateExpander(
            turn_resolver=_core.BattleEventStandardMoveTurnResolver(
                effects=self.inference_use_case._effects(configuration)
            ),
            attacker_policy=_core._policy(command.attacker_policy),
            defender_policy=_core._policy(command.defender_policy),
        )
        root_state = _core._initial_state(configuration, command.rules)
        current_state, cumulative_probability, report_steps = self._replay(
            root_state,
            expander,
            cursor,
        )
        current_node = _node(
            node_id=cursor.current_node_id,
            state=current_state,
        )
        outgoing = self._expand_current(current_node, expander)
        position = BattleExplorationPosition(
            graph_id=SNAPSHOT_GRAPH_ID,
            calculation_revision=BATTLE_INFERENCE_CALCULATION_REVISION,
            cursor=cursor,
            node=projection._node_detail(
                current_node,
                has_outgoing_edges=bool(outgoing),
            ),
            cumulative_probability=ProbabilityProjection.from_fraction(
                cumulative_probability
            ),
        )
        group_summaries = list_group_summaries(current_node, outgoing)
        groups = tuple(
            expand_group(
                graph_id=SNAPSHOT_GRAPH_ID,
                node=current_node,
                edges=outgoing,
                cumulative_probability=cumulative_probability,
                group_id=group.group_id,
            )
            for group in group_summaries
        )
        report = BattleReport(
            graph_id=SNAPSHOT_GRAPH_ID,
            calculation_revision=BATTLE_INFERENCE_CALCULATION_REVISION,
            root_node_id=0,
            current_node_id=int(cursor.current_node_id),
            depth=cursor.depth,
            cumulative_probability=ProbabilityProjection.from_fraction(
                cumulative_probability
            ),
            steps=tuple(report_steps),
        )
        return FixedBattleSnapshotStepResult(
            groups=BattleTransitionGroupsResult(
                position=position,
                transition_groups=groups,
            ),
            report=report,
        )

    def _configuration_space(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> ConfigurationSpace:
        """把固定请求还原为唯一行为配置空间。

        Args:
            command: HTTP 层已构造的固定推演命令。

        Returns:
            只包含一个行为等价类的配置空间。
        """
        attacker_loaded = self.inference_use_case._load(
            command.rules,
            command.attacker.pokemon_id,
        )
        defender_loaded = self.inference_use_case._load(
            command.rules,
            command.defender.pokemon_id,
        )
        self.inference_use_case._validate_item(
            command.attacker.item_identifier,
            attacker_loaded,
        )
        self.inference_use_case._validate_item(
            command.defender.item_identifier,
            defender_loaded,
        )
        configuration_space = self.inference_use_case._configuration_generator().execute(
            _core.GenerateConfigurationSpaceCommand(
                attacker=self.inference_use_case._fixed_space_command(
                    command.attacker,
                    command.rules.level,
                ),
                defender=self.inference_use_case._fixed_space_command(
                    command.defender,
                    command.rules.level,
                ),
                max_raw_configuration_pairs=1,
            ),
            attacker_profile=self.inference_use_case._configuration_profile(
                attacker_loaded.pokemon,
                command.rules,
            ),
            defender_profile=self.inference_use_case._configuration_profile(
                defender_loaded.pokemon,
                command.rules,
            ),
        )
        if len(configuration_space.equivalence_classes) != 1:
            raise BattleInferenceExecutionError(
                "fixed battle snapshot command must resolve to one behavior configuration"
            )
        return configuration_space

    def _replay(
        self,
        root_state: BattleState,
        expander: _core._PolicyDrivenBattleStateExpander,
        cursor: ExplorationCursor,
    ) -> tuple[BattleState, Fraction, list[BattleReportStep]]:
        """从根状态按局部 edge 序列重放到当前快照。

        Args:
            root_state: 固定配置的初始满 HP、满 PP 状态。
            expander: 与本次请求策略一致的单节点展开器。
            cursor: 前端提交的局部 edge 序列。
        Returns:
            当前状态、累计概率和每一步结构化战报。
        """
        state = root_state
        cumulative_probability = Fraction(1, 1)
        report_steps: list[BattleReportStep] = []
        source_node_id = GraphNodeId(0)
        for depth, step in enumerate(cursor.steps, start=1):
            if step.source_node_id != source_node_id:
                raise BattleInferenceExecutionError(
                    "snapshot cursor source node does not match replayed path"
                )
            source_node = _node(node_id=source_node_id, state=state)
            transitions = expander.expand(source_node.state)
            outgoing = self._edges_from_transitions(source_node, transitions)
            edge_index = int(step.edge_id)
            if edge_index < 0 or edge_index >= len(outgoing):
                raise BattleInferenceExecutionError(
                    "snapshot cursor edge_id is not available from current state"
                )
            edge = outgoing[edge_index]
            if edge.target_node_id != step.target_node_id:
                raise BattleInferenceExecutionError(
                    "snapshot cursor target node does not match replayed edge"
                )
            cumulative_probability *= edge.probability
            report_steps.append(
                BattleReportStep(
                    depth=depth,
                    source_node_id=int(edge.source_node_id),
                    edge_id=int(edge.edge_id),
                    target_node_id=int(edge.target_node_id),
                    edge_probability=ProbabilityProjection.from_fraction(
                        edge.probability
                    ),
                    cumulative_probability=ProbabilityProjection.from_fraction(
                        cumulative_probability
                    ),
                    event_paths=tuple(
                        projection._event_path_detail(node=source_node, path=path)
                        for path in edge.event_summary.paths
                    ),
                )
            )
            state = transitions[edge_index].state
            source_node_id = edge.target_node_id
        return state, cumulative_probability, report_steps

    def _expand_current(
        self,
        node: StateGraphNode,
        expander: _core._PolicyDrivenBattleStateExpander,
    ) -> tuple[StateGraphEdge, ...]:
        """把当前状态展开为局部编号的一层出边。

        Args:
            node: 当前快照节点。
            expander: 与请求策略一致的状态转移展开器。

        Returns:
            edge_id 从 0 开始的局部出边；target_node_id 只在当前路径下稳定。
        """
        if node.is_terminal:
            return ()
        transitions = expander.expand(node.state)
        return self._edges_from_transitions(node, transitions)

    def _edges_from_transitions(
        self,
        node: StateGraphNode,
        transitions: tuple[WeightedTransition[BattleState], ...],
    ) -> tuple[StateGraphEdge, ...]:
        """把即时转移转换成当前快照使用的局部图边。

        Args:
            node: 当前快照节点。
            transitions: expander 返回的后继状态和事件摘要。

        Returns:
            只包含投影所需字段的局部 StateGraphEdge 元组。
        """
        return tuple(
            StateGraphEdge(
                edge_id=GraphEdgeId(index),
                source_node_id=node.node_id,
                target_node_id=_target_node_id(node.node_id, index),
                probability=transition.probability,
                event_summary=transition.event_summary,
                source_key=transition.source_key,
            )
            for index, transition in enumerate(transitions)
        )


def _target_node_id(source_node_id: GraphNodeId, edge_index: int) -> GraphNodeId:
    """根据当前路径节点和局部 edge 序号生成下一层展示节点 ID。"""
    return GraphNodeId((int(source_node_id) + 1) * 10_000 + edge_index)


def _node(*, node_id: GraphNodeId, state: BattleState) -> StateGraphNode:
    """把一个即时 BattleState 包装成投影层需要的轻量 graph node。"""
    outcome, reason = _classify_state(state)
    return StateGraphNode(
        node_id=node_id,
        state=state,
        state_key=state.state_key,
        outcome=outcome,
        termination_reason=reason,
    )


def _classify_state(
    state: BattleState,
) -> tuple[GraphNodeOutcome, TerminationReason | None]:
    """按 HP 和终局阶段判断即时状态的基础终局语义。"""
    attacker_fainted = state.attacker.current_hp == 0
    defender_fainted = state.defender.current_hp == 0
    if attacker_fainted and defender_fainted:
        return GraphNodeOutcome.DRAW, TerminationReason.MUTUAL_KNOCKOUT
    if attacker_fainted:
        return GraphNodeOutcome.DEFENDER_WIN, TerminationReason.KNOCKOUT
    if defender_fainted:
        return GraphNodeOutcome.ATTACKER_WIN, TerminationReason.KNOCKOUT
    if state.phase is BattlePhase.TERMINAL:
        return GraphNodeOutcome.DRAW, TerminationReason.NO_LEGAL_ACTION
    return GraphNodeOutcome.NON_TERMINAL, None


__all__ = [
    "ExpandFixedBattleSnapshotUseCase",
    "FixedBattleSnapshotStepResult",
    "SNAPSHOT_GRAPH_ID",
]
