"""使用状态图 builder 和精确 solver 执行单个配置对。"""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from pokeop.application.configuration_space import (
    BattleConfiguration,
    PokemonBattleConfiguration,
)
from pokeop.application.solver.graph_solver import (
    BattleGraphSolver,
    PurePythonBattleGraphSolver,
)
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.solver.graph_explanation import build_root_action_pair_explanation
from pokeop.application.solver.summary_state_graph import SummaryStateGraphBuilder
from pokeop.application.use_cases.infer_one_on_one_battle import BattleActionPolicyKind
from pokeop.application.use_cases.stream_configuration_pairs.models import (
    ConfigurationPairGraphArtifact,
    ConfigurationPairProgressObserver,
    ConfigurationPairRuntimeProgress,
    ConfigurationPairStreamError,
    ConfigurationPairWorkItem,
    DiscardConfigurationPairProgressObserver,
    StateGraphToConfigurationPairProgressObserver,
)
from pokeop.domain.battle.action_policy import (
    ActionPolicy,
    FirstLegalActionPolicy,
    UniformRandomPolicy,
)
from pokeop.domain.battle.actions import BattleAction
from pokeop.domain.battle.effects.factories import (
    BattleEffectAbstractFactory,
    PokemonChampionEffectFactory,
)
from pokeop.domain.battle.effects.protocols import BattleEffect
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.specs import PokemonSpec
from pokeop.domain.battle.state import BattleState, BattlerState
from pokeop.domain.battle.structured_turn_resolver import (
    BattleEventStandardMoveTurnResolver,
)
from pokeop.domain.battle.transitions import (
    TransitionEventSummary,
    WeightedTransition,
    merge_equivalent_transitions,
)


@dataclass(frozen=True, slots=True)
class _PolicyDrivenBattleStateExpander:
    """组合双方行动策略与完整回合 resolver，生成状态图后继分布。"""

    turn_resolver: BattleEventStandardMoveTurnResolver
    attacker_policy: ActionPolicy[BattleAction]
    defender_policy: ActionPolicy[BattleAction]
    progress_observer: ConfigurationPairProgressObserver

    def expand(self, state: BattleState) -> tuple[WeightedTransition[BattleState], ...]:
        """返回玩家策略概率与回合内部随机概率相乘后的归一化后继。

        Args:
            state: 当前不可变战斗状态。

        Returns:
            当前节点全部合法行动组合和随机分支的精确后继。
        """
        attacker_actions = self.turn_resolver.legal_actions(state, BattleSide.ATTACKER)
        defender_actions = self.turn_resolver.legal_actions(state, BattleSide.DEFENDER)
        attacker_distribution = self.attacker_policy.distribution_for(attacker_actions)
        defender_distribution = self.defender_policy.distribution_for(defender_actions)
        attacker_distribution.validate_legal_actions(attacker_actions)
        defender_distribution.validate_legal_actions(defender_actions)

        transitions: list[WeightedTransition[BattleState]] = []
        total_action_pairs = (
            len(attacker_distribution.selections) * len(defender_distribution.selections)
        )
        completed_action_pairs = 0
        for attacker_selection in attacker_distribution.selections:
            for defender_selection in defender_distribution.selections:
                resolution = self.turn_resolver.resolve(
                    state,
                    attacker_selection.action,
                    defender_selection.action,
                )
                policy_probability = (
                    attacker_selection.probability * defender_selection.probability
                )
                for transition in resolution.transitions:
                    transitions.append(
                        WeightedTransition(
                            probability=policy_probability * transition.probability,
                            state=transition.state,
                            event_summary=transition.event_summary,
                            source_key=transition.source_key
                            or "battle.policy-and-turn",
                        )
                    )
                completed_action_pairs += 1
                self.progress_observer.write_runtime_progress(
                    ConfigurationPairRuntimeProgress(
                        phase="expanding_actions",
                        node_count=0,
                        edge_count=0,
                        expanded_node_count=0,
                        frontier_count=0,
                        action_pair_completed_count=completed_action_pairs,
                        action_pair_total_count=total_action_pairs,
                    )
                )
        return merge_equivalent_transitions(transitions)


@dataclass(slots=True)
class _RootCachingExpander:
    """复用 root 预展开结果，避免归因采样导致 root 节点重复解析。

    Args:
        delegate: 正式行动策略 expander。
        root_state_key: 初始状态的稳定状态键。
        root_transitions: 已经为 root 计算过的完整后继分布。
    """

    delegate: _PolicyDrivenBattleStateExpander
    root_state_key: object
    root_transitions: tuple[WeightedTransition[BattleState], ...]
    root_consumed: bool = False

    def expand(self, state: BattleState) -> tuple[WeightedTransition[BattleState], ...]:
        """返回缓存的 root 后继或委托正常展开。

        Args:
            state: 当前待展开状态。

        Returns:
            完整精确后继分布。
        """
        if not self.root_consumed and state.state_key == self.root_state_key:
            self.root_consumed = True
            return self.root_transitions
        return self.delegate.expand(state)


@dataclass(slots=True)
class ExactConfigurationPairGraphExecutor:
    """用现有状态图 builder 和精确 solver 执行一个规范化配置对。

    Args:
        effect_factory: 当前规则集的招式、特性和道具 effect 工厂。
        solver: 接收完整或显式截断状态图的精确求解器。
    """

    effect_factory: BattleEffectAbstractFactory = field(
        default_factory=PokemonChampionEffectFactory
    )
    solver: BattleGraphSolver = field(default_factory=PurePythonBattleGraphSolver)

    def execute(
        self,
        work_item: ConfigurationPairWorkItem,
        *,
        rules: BattleInferenceRules,
        attacker_policy: BattleActionPolicyKind,
        defender_policy: BattleActionPolicyKind,
        observer: BattleSide,
        graph_limits: StateGraphLimits,
        progress_observer: ConfigurationPairProgressObserver | None = None,
    ) -> ConfigurationPairGraphArtifact:
        """构建配置对完整状态图，并立即交给精确 solver。

        Args:
            work_item: 已规范化且带稳定配置权重的配置对。
            rules: 当前规则集与 version group 轴。
            attacker_policy: 攻击方行动策略。
            defender_policy: 防守方行动策略。
            observer: 胜负概率观察方。
            graph_limits: 当前 pair 独立使用的节点、边和回合上限。
            progress_observer: 接收构图和求解阶段实时进度的观察者；None 时丢弃。

        Returns:
            同时持有图与求解结果的短生命周期 artifact。
        """
        runtime_observer = progress_observer or DiscardConfigurationPairProgressObserver()
        effects = _effects(work_item.configuration, self.effect_factory)
        expander = _PolicyDrivenBattleStateExpander(
            turn_resolver=BattleEventStandardMoveTurnResolver(effects=effects),
            attacker_policy=_policy(attacker_policy),
            defender_policy=_policy(defender_policy),
            progress_observer=runtime_observer,
        )
        initial_state = _initial_state(work_item.configuration, rules)
        root_transitions = expander.expand(initial_state)
        root_event_summary_by_state_key = {
            transition.state.state_key: transition.event_summary
            for transition in root_transitions
        }
        graph = SummaryStateGraphBuilder(
            expander=_RootCachingExpander(
                delegate=expander,
                root_state_key=initial_state.state_key,
                root_transitions=root_transitions,
            ),
            limits=graph_limits,
            progress_observer=StateGraphToConfigurationPairProgressObserver(
                runtime_observer
            ),
        ).build(initial_state)
        runtime_observer.write_runtime_progress(
            ConfigurationPairRuntimeProgress(
                phase="solving_probabilities",
                node_count=graph.statistics.unique_state_count,
                edge_count=graph.statistics.edge_count,
                expanded_node_count=graph.statistics.unique_state_count,
                frontier_count=0,
            )
        )
        return ConfigurationPairGraphArtifact(
            graph=graph,
            solve_result=self.solver.solve(graph, observer),
            explanation_json=_explanation_json(
                graph,
                root_event_summary_by_state_key,
            ),
        )


def _explanation_json(
    graph,
    root_event_summary_by_state_key: dict[object, TransitionEventSummary],
) -> str | None:
    """为成功完整图生成可持久化的总结型归因 JSON。

    Args:
        graph: worker 刚构建完成的轻量 summary 状态图。
        root_event_summary_by_state_key: root 后继状态键到事件摘要的映射。

    Returns:
        完整图返回紧凑 JSON 文本；截断图不产生归因，避免误导用户。
    """
    if not graph.is_complete:
        return None
    try:
        payload = build_root_action_pair_explanation(
            graph=graph,
            root_event_summary_by_state_key=root_event_summary_by_state_key,
        )
    except Exception:
        # 归因是完成页解释增强，不能让已求得的完整精确概率因为解释投影失败而丢失。
        return None
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _policy(kind: BattleActionPolicyKind) -> ActionPolicy[BattleAction]:
    """根据显式策略枚举创建无状态行动策略。

    Args:
        kind: 固定首项或全部合法行动等概率策略。

    Returns:
        满足 domain ActionPolicy 协议的不可变策略对象。
    """
    if kind is BattleActionPolicyKind.FIRST_LEGAL:
        return FirstLegalActionPolicy[BattleAction]()
    if kind is BattleActionPolicyKind.UNIFORM_RANDOM:
        return UniformRandomPolicy[BattleAction]()
    raise ConfigurationPairStreamError(f"unsupported policy kind: {kind!r}")


def _effects(
    configuration: BattleConfiguration,
    effect_factory: BattleEffectAbstractFactory,
) -> tuple[BattleEffect, ...]:
    """为配置中的全部具体招式、特性和道具创建去重 effect 集合。

    Args:
        configuration: 已规范化的双方固定配置。
        effect_factory: 当前规则集机制工厂。

    Returns:
        可直接注入完整回合 resolver 的去重 effect 元组。
    """
    effects: list[BattleEffect] = []
    for pokemon in (configuration.attacker, configuration.defender):
        for configured_move in pokemon.moves:
            if configured_move.effect_identifier is not None:
                effects.append(
                    effect_factory.create_move_effect(
                        configured_move.effect_identifier
                    )
                )
        effects.append(effect_factory.create_ability_effect(pokemon.ability_identifier))
        effects.append(
            effect_factory.create_item_effect(
                None if pokemon.item_identifier == "none" else pokemon.item_identifier
            )
        )
    unique: dict[tuple[str, str], BattleEffect] = {}
    for effect in effects:
        key = (effect.coverage.source_kind.value, effect.coverage.identifier)
        unique.setdefault(key, effect)
    return tuple(unique.values())


def _initial_state(
    configuration: BattleConfiguration,
    rules: BattleInferenceRules,
) -> BattleState:
    """把双方 application 配置转换为满 HP、满 PP 的初始状态。

    Args:
        configuration: 已验证的双方固定配置。
        rules: 状态键必须保留的完整推演规则。

    Returns:
        处于第一回合行动选择阶段的不可变战斗状态。
    """
    return BattleState(
        attacker=_initial_battler(configuration.attacker),
        defender=_initial_battler(configuration.defender),
        rules=rules,
    )


def _initial_battler(configuration: PokemonBattleConfiguration) -> BattlerState:
    """为一侧配置创建满 HP、满 PP 的动态状态。

    Args:
        configuration: 一侧不可变 application 配置。

    Returns:
        可直接进入 BattleState 的 BattlerState。
    """
    spec = PokemonSpec(
        pokemon_id=configuration.pokemon_id,
        name=configuration.name,
        level=configuration.level,
        types=configuration.types,
        stats=configuration.stats,
        ability=configuration.ability_identifier,
        item=configuration.item_identifier,
        moves=tuple(move.move_spec for move in configuration.moves),
        can_evolve=configuration.can_evolve,
    )
    return BattlerState(
        spec=spec,
        current_hp=spec.stats.hp,
        move_slots=tuple(
            MoveSlotState(
                move_id=move.move_id,
                current_pp=move.max_pp,
                max_pp=move.max_pp,
            )
            for move in spec.moves
        ),
    )


__all__ = ["ExactConfigurationPairGraphExecutor"]
