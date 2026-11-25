"""原透明工厂真实回合/固定图与Core显式UNKNOWN假设的完整差分。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import pytest

from pokeop.application.battle_inference_effect_factory import NeutralUnsupportedAbilityEffect, TransparentPokemonChampionEffectFactory
from pokeop.application.solver.graph_solver import PurePythonBattleGraphSolver
from pokeop.application.solver.models import GraphTruncationReason, StateGraphLimits
from pokeop.application.solver.state_graph import StateGraphBuilder
from pokeop.application.use_cases.infer_one_on_one_battle._core import _PolicyDrivenBattleStateExpander
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import BattlePokemon
from pokeop.domain.battle.effects.protocols import BattleEffect
from pokeop.domain.battle.grounding import GroundingState
from pokeop.domain.battle.inference_outcome import BattleSide, TerminationReason
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.state import BattlePhase, BattleState
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.structured_turn_resolver import BattleEventStandardMoveTurnResolver
from pokeop.domain.battle.turn_phases import STABLE_TURN_PHASES, TurnPhase
from pokeop.domain.models.types import Type, TypeHelper
from tests.migration.test_core_actions_abi import Action, ActionStrategy
from tests.migration.test_core_battle_graph import BuildReply, BuildStatistics, EdgeReply, NodeReply, WeightedPath, _BuildOracle
from tests.migration.test_core_damage import ExactFraction, PokemonSnapshot, TypeEfficacySnapshot, _DamageOracle
from tests.migration.test_core_graph import Component, ExpectedTurns, GraphNodeOutcome, GraphReply
from tests.migration.test_core_state import BattleSnapshot, BattlerSnapshot, FieldSnapshot, MoveSpecSnapshot, RulesSnapshot, SlotSnapshot, SpecSnapshot, Stages, StatusSnapshot, _Contract, _StateOracle, _reference
from tests.migration.test_core_turn import FixedReply, Mode, TransitionReply, TurnLimits, TurnReply, _TurnOracle


SelectedAbility = DamageAbility | Literal["none", "pressure", "pickpocket"]


class _RawPokemon(_Contract):
    """可重放状态保留原始真实能力；与机械DamagePokemon字段语义明确分开。"""

    level: int
    types: tuple[Type, ...]
    stats: StatValues
    ability: SelectedAbility
    item: DamageItem | Literal["none"]
    can_evolve: bool
    grounding: GroundingState | None

    def mechanical(self, name: str) -> PokemonSnapshot:
        """仅用于独立对照：调用原解析与既有UNKNOWN wire投影，不在测试复制能力解释规则。"""
        return _DamageOracle.pokemon(BattlePokemon(name, self.level, self.types, self.stats, ability=DamageAbility.from_identifier(self.ability),
            item=DamageItem.from_identifier(self.item), can_evolve=self.can_evolve, grounding_state=self.grounding))


class _RawSpec(_Contract):
    """明确透明上下文与原始能力的完整配置记录，额外假设不进入原UNKNOWN StateKey。"""

    pokemon_id: int
    name: str
    pokemon: _RawPokemon
    moves: tuple[MoveSpecSnapshot, ...]
    ability_context: Literal["transparent_inference"] | None = None

    def mechanical(self) -> SpecSnapshot:
        """按原已验证UNKNOWN解析投影完整配置，保留所有非能力字段。"""
        return SpecSnapshot(pokemon_id=self.pokemon_id, name=self.name, pokemon=self.pokemon.mechanical(self.name), moves=self.moves)


class _RawBattler(_Contract):
    """完整可重放一侧，不能仅比较HP而漏掉PP、锁招、状态或原始能力。"""

    spec: _RawSpec
    current_hp: int
    move_slots: tuple[SlotSnapshot, ...]
    stages: Stages
    status: StatusSnapshot
    last_move_id: int | None
    choice_lock_move_id: int | None
    item_consumed: bool
    is_first_turn: bool

    def mechanical(self) -> BattlerSnapshot:
        """投影原完整机械一侧，raw身份另由check_raw逐状态独立检查。"""
        return BattlerSnapshot(spec=self.spec.mechanical(), current_hp=self.current_hp, move_slots=self.move_slots, stages=self.stages,
            status=self.status, last_move_id=self.last_move_id, choice_lock_move_id=self.choice_lock_move_id, item_consumed=self.item_consumed, is_first_turn=self.is_first_turn)


class _RawState(_Contract):
    """完整正式状态形状，透明仅增加明确假设事实，不替换任何规则或动态字段。"""

    attacker: _RawBattler
    defender: _RawBattler
    rules: RulesSnapshot
    turn_number: int
    field: FieldSnapshot
    phase: BattlePhase

    def mechanical(self) -> BattleSnapshot:
        """按原UNKNOWN合同投影整节点以与原完整图逐字段比较。"""
        return BattleSnapshot(attacker=self.attacker.mechanical(), defender=self.defender.mechanical(), rules=self.rules,
            turn_number=self.turn_number, field=self.field, phase=self.phase)

    def check_raw(self, selected: tuple[SelectedAbility, SelectedAbility]) -> None:
        """用原真实工厂判断是否中性占位，核对每侧原始标识和显式假设未被丢弃。"""
        factory = TransparentPokemonChampionEffectFactory()
        for battler, identifier in zip((self.attacker, self.defender), selected, strict=True):
            assert battler.spec.pokemon.ability == identifier
            effect = factory.create_ability_effect(identifier)
            expected = "transparent_inference" if isinstance(effect, NeutralUnsupportedAbilityEffect) else None
            assert battler.spec.ability_context == expected


class _RawTurnInput(_Contract):
    """复用既有真实turn runner输入，直接传raw能力和上下文而非在测试外端清空。"""

    mode: Mode
    state: _RawState
    type_chart: tuple[TypeEfficacySnapshot, ...]
    attacker_action: Action | None = None
    defender_action: Action | None = None
    attacker_policy: ActionStrategy
    defender_policy: ActionStrategy
    observer: BattleSide
    turn_limits: TurnLimits = TurnLimits()
    graph_limits: StateGraphLimits
    max_equation_nodes: int | None = None


class _RawTransition(_Contract):
    """完整条件转移，raw状态与全部事件/来源保留后再对照原机械投影。"""

    probability: ExactFraction
    state: _RawState
    paths: tuple[WeightedPath, ...]
    source_key: str | None

    def mechanical(self) -> TransitionReply:
        """只转换原UNKNOWN投影，概率与每条事件历史不做任何运算或归并。"""
        return TransitionReply(probability=self.probability, state=self.state.mechanical(), paths=self.paths, source_key=self.source_key)


class _RawTurnReply(_Contract):
    """真实回合所有后继与十一阶段，禁止只比较一条代表路径。"""

    kind: Literal["resolve", "expand"]
    transitions: tuple[_RawTransition, ...]
    phases: tuple[TurnPhase, ...]


class _RawNode(_Contract):
    """图节点完整状态/终局/前驱和代表路径，ID顺序必须与原BFS完全一致。"""

    id: int
    state: _RawState
    outcome: GraphNodeOutcome
    reason: TerminationReason | GraphTruncationReason | None
    predecessor_node: int | None
    predecessor_edge: int | None
    path: tuple[int, ...]

    def mechanical(self) -> NodeReply:
        """只转换原UNKNOWN状态投影，BFS身份和完整路径保持原值。"""
        return NodeReply(id=self.id, state=self.state.mechanical(), outcome=self.outcome, reason=self.reason,
            predecessor_node=self.predecessor_node, predecessor_edge=self.predecessor_edge, path=self.path)


class _RawGraph(_Contract):
    """完整真实图的严格边界，概率/事件/SCC和所有资源统计均不能缺失。"""

    nodes: tuple[_RawNode, ...]
    edges: tuple[EdgeReply, ...]
    components: tuple[Component, ...]
    truncations: tuple[GraphTruncationReason, ...]
    statistics: BuildStatistics

    def mechanical(self) -> BuildReply:
        """保持所有正式图字段，只将节点能力按原解析归为UNKNOWN供独立等价比较。"""
        return BuildReply(nodes=tuple(node.mechanical() for node in self.nodes), edges=self.edges, components=self.components,
            truncations=self.truncations, statistics=self.statistics)


class _RawFixedReply(_Contract):
    """真实固定回合→BFS→SCC→精确解，unknown截断与数学平局明确不同。"""

    kind: Literal["fixed"]
    graph: _RawGraph
    solution: GraphReply


@dataclass(frozen=True)
class _Case:
    """同一原状态和真实selected能力供两实现使用，选招策略也保持唯一事实源。"""

    state: BattleState
    selected: tuple[SelectedAbility, SelectedAbility]
    mode: Mode
    attacker_policy: ActionStrategy = ActionStrategy.uniform
    defender_policy: ActionStrategy = ActionStrategy.uniform
    observer: BattleSide = BattleSide.ATTACKER
    limits: StateGraphLimits = StateGraphLimits()


class _TransparentOracle:
    """原透明工厂/标准回合/策略/BFS/solver负责全部计算，本类只有完整边界投影。"""

    @staticmethod
    def raw_battler(snapshot: BattlerSnapshot, selected: SelectedAbility) -> _RawBattler:
        """仅把真实selected标识与原完整状态字段送给Core，不在外端执行UNKNOWN归一。"""
        pokemon = snapshot.spec.pokemon
        raw = _RawPokemon(level=pokemon.level, types=pokemon.types, stats=pokemon.stats, ability=selected, item=pokemon.item,
            can_evolve=pokemon.can_evolve, grounding=pokemon.grounding)
        return _RawBattler(spec=_RawSpec(pokemon_id=snapshot.spec.pokemon_id, name=snapshot.spec.name, pokemon=raw, moves=snapshot.spec.moves,
            ability_context="transparent_inference"), current_hp=snapshot.current_hp, move_slots=snapshot.move_slots, stages=snapshot.stages,
            status=snapshot.status, last_move_id=snapshot.last_move_id, choice_lock_move_id=snapshot.choice_lock_move_id,
            item_consumed=snapshot.item_consumed, is_first_turn=snapshot.is_first_turn)

    @classmethod
    def request(cls, case: _Case) -> _RawTurnInput:
        """知识直接取原TypeHelper，完整raw state/策略/保护不携带已求解结果。"""
        state = _StateOracle.snapshot(case.state)
        raw = _RawState(attacker=cls.raw_battler(state.attacker, case.selected[0]), defender=cls.raw_battler(state.defender, case.selected[1]),
            rules=state.rules, turn_number=state.turn_number, field=state.field, phase=state.phase)
        chart = tuple(TypeEfficacySnapshot(attacking=first, defending=second, percent=TypeHelper.get_type_efficacy(first, second)) for first in Type for second in Type)
        return _RawTurnInput(mode=case.mode, state=raw, type_chart=chart, attacker_policy=case.attacker_policy, defender_policy=case.defender_policy,
            observer=case.observer, graph_limits=case.limits)

    @staticmethod
    def resolver(case: _Case) -> BattleEventStandardMoveTurnResolver:
        """实际调用原Transparent工厂创建原始selected特性effects，不从已归UNKNOWN的Spec猜回真实能力。"""
        factory = TransparentPokemonChampionEffectFactory()
        effects: list[BattleEffect] = []
        for battler, selected in zip((case.state.attacker, case.state.defender), case.selected, strict=True):
            effects.extend(factory.create_move_effect(move.effect_identifier) for move in battler.spec.moves if move.effect_identifier is not None)
            effects.extend((factory.create_ability_effect(selected), factory.create_item_effect(battler.spec.item)))
        unique: dict[tuple[str, str], BattleEffect] = {}
        for effect in effects:
            unique.setdefault((effect.coverage.source_kind.value, effect.coverage.identifier), effect)
        return BattleEventStandardMoveTurnResolver(effects=tuple(unique.values()))

    @classmethod
    def expected(cls, case: _Case) -> TurnReply | FixedReply:
        """原完整回合/策略/BFS/SCC/精确解产生全部预期，不复制未知投影或概率算法。"""
        expander = _PolicyDrivenBattleStateExpander(cls.resolver(case), _TurnOracle.policy(case.attacker_policy), _TurnOracle.policy(case.defender_policy))
        if case.mode is Mode.EXPAND:
            return TurnReply(kind="expand", transitions=tuple(_TurnOracle.transition(value) for value in expander.expand(case.state)), phases=STABLE_TURN_PHASES)
        graph = StateGraphBuilder(expander, case.limits).build(case.state)
        projected = _BuildOracle.graph(graph)
        solved = PurePythonBattleGraphSolver().solve(graph, case.observer)
        solution = GraphReply(components=projected.components, status=solved.status,
            win=None if solved.win_probability is None else _StateOracle.fraction(solved.win_probability),
            loss=None if solved.loss_probability is None else _StateOracle.fraction(solved.loss_probability),
            draw=None if solved.draw_probability is None else _StateOracle.fraction(solved.draw_probability),
            closed_cycle=None if solved.closed_cycle_probability is None else _StateOracle.fraction(solved.closed_cycle_probability),
            expected_turns=ExpectedTurns(status=solved.expected_turns.status, value=None if solved.expected_turns.value is None else _StateOracle.fraction(solved.expected_turns.value)))
        return FixedReply(graph=projected, solution=solution)

    @classmethod
    def compare(cls, runner: Path, cases: tuple[_Case, ...]) -> None:
        """逐行真实Core完整比较，并单独验证所有后继raw身份与透明假设保留。"""
        process = subprocess.run([str(runner)], input="".join(cls.request(case).model_dump_json() + "\n" for case in cases), text=True, capture_output=True, check=True, timeout=120)
        lines = process.stdout.splitlines()
        assert len(lines) == len(cases)
        for line, case in zip(lines, cases, strict=True):
            if case.mode is Mode.FIXED:
                actual = _RawFixedReply.model_validate_json(line)
                for node in actual.graph.nodes:
                    node.state.check_raw(case.selected)
                assert FixedReply(graph=actual.graph.mechanical(), solution=actual.solution) == cls.expected(case)
            else:
                actual_turn = _RawTurnReply.model_validate_json(line)
                for transition in actual_turn.transitions:
                    transition.state.check_raw(case.selected)
                assert TurnReply(kind=actual_turn.kind, transitions=tuple(value.mechanical() for value in actual_turn.transitions), phases=actual_turn.phases) == cls.expected(case)


@pytest.fixture
def transparent_turn_runner() -> Path:
    """明确外部真实Core编译入口，缺少时skip，不运行内存替代实现。"""
    value = os.getenv("PBI_TRANSPARENT_TURN_RUNNER")
    if value is None:
        pytest.skip("PBI_TRANSPARENT_TURN_RUNNER is required")
    runner = Path(value)
    assert runner.is_file()
    return runner


class TestCoreTransparentAbilities:
    """原UNKNOWN StateKey、raw身份保留以及透明真实完整回合/图的精确等价。"""

    def test_original_unknown_projection_is_identical(self) -> None:
        """实际原from_identifier与SpecKey比较证明None/none/unknown及两透明标识原本相等。"""
        original = _reference().defender.spec
        specs = tuple(replace(original, ability=DamageAbility.from_identifier(identifier)) for identifier in (None, "none", "unknown", "pressure", "pickpocket"))
        assert all(spec.ability is DamageAbility.UNKNOWN for spec in specs)
        assert all(spec.state_key == specs[0].state_key for spec in specs)
        factory = TransparentPokemonChampionEffectFactory()
        for identifier in ("pressure", "pickpocket"):
            effect = factory.create_ability_effect(identifier)
            assert isinstance(effect, NeutralUnsupportedAbilityEffect)
            assert effect.coverage.identifier == identifier
            assert tuple(capability.identifier for capability in effect.coverage.capabilities) == ("real_ability_behavior",)

    def test_real_transparent_turns_and_fixed_graphs(self, transparent_turn_runner: Path) -> None:
        """48原透明策略回合与12完整固定图/保护，逐字段比较所有状态、概率、事件与解。"""
        rng = random.Random(60501)
        selections: tuple[SelectedAbility, ...] = ("pressure", "pickpocket", "none", DamageAbility.MULTISCALE, DamageAbility.INNER_FOCUS, DamageAbility.TECHNICIAN)
        cases: list[_Case] = []
        for index in range(48):
            selected = (selections[index % len(selections)], selections[(index // len(selections)) % len(selections)])
            state = _TurnOracle.random_state(rng)
            for side, ability in zip(BattleSide, selected, strict=True):
                battler = state.battler(side)
                state = state.with_battler(side, replace(battler, spec=replace(battler.spec, ability=DamageAbility.from_identifier(ability))))
            cases.append(_Case(state, selected, Mode.EXPAND, rng.choice(tuple(ActionStrategy)), rng.choice(tuple(ActionStrategy))))
        for index in range(12):
            selected = ("pressure", "pickpocket") if index % 2 == 0 else (DamageAbility.INNER_FOCUS, "pressure")
            state = _reference()
            for side, ability in zip(BattleSide, selected, strict=True):
                battler = state.battler(side)
                moves = (replace(battler.spec.moves[0], max_pp=1, accuracy=75),)
                spec = replace(battler.spec, ability=DamageAbility.from_identifier(ability), moves=moves)
                state = state.with_battler(side, replace(battler, spec=spec, current_hp=20,
                    move_slots=(MoveSlotState(moves[0].move_id, 1, 1, slot_id=9000 + moves[0].move_id),)))
            state = replace(state, rules=replace(state.rules, damage_policy=replace(state.rules.damage_policy, random_damage_multipliers=(0.85, 1.0))))
            limits = (StateGraphLimits(max_nodes=128, max_edges=512, max_turns=8), StateGraphLimits(max_nodes=1), StateGraphLimits(max_edges=1), StateGraphLimits(max_turns=1))[index % 4]
            cases.append(_Case(state, selected, Mode.FIXED, limits=limits, observer=rng.choice(tuple(BattleSide))))
        _TransparentOracle.compare(transparent_turn_runner, tuple(cases))
