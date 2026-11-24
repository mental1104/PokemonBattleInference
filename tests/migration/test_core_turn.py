"""真实 C++ 正式回合与固定战斗逐字段对照原结构化执行路径，不复制伤害或状态算法。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.application.solver.graph_solver import PurePythonBattleGraphSolver
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.solver.state_graph import StateGraphBuilder
from pokeop.application.use_cases.infer_one_on_one_battle._core import _PolicyDrivenBattleStateExpander
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.action_policy import ActionPolicy, FirstLegalActionPolicy, UniformRandomPolicy
from pokeop.domain.battle.actions import BattleAction, StandardLegalActionGenerator
from pokeop.domain.battle.effects.factories import PokemonChampionEffectFactory
from pokeop.domain.battle.effects.protocols import BattleEffect
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.state import BattleFieldState, BattleState, StatStages
from pokeop.domain.battle.status.state import BurnStatus, CombatantStatus, FlinchStatus, ParalysisStatus
from pokeop.domain.battle.structured_turn_resolver import BattleEventStandardMoveTurnResolver
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.transitions import WeightedTransition
from pokeop.domain.battle.turn_phases import STABLE_TURN_PHASES, TurnPhase
from pokeop.domain.battle.weather import Weather
from pokeop.domain.models.types import Type, TypeHelper
from tests.migration.test_core_actions_abi import Action, ActionStrategy, _ActionOracle
from tests.migration.test_core_battle_graph import BuildReply, WeightedPath, _BuildOracle
from tests.migration.test_core_damage import ExactFraction, TypeEfficacySnapshot
from tests.migration.test_core_graph import ExpectedTurns, GraphReply
from tests.migration.test_core_state import BattleSnapshot, _StateOracle, _reference


class _Contract(BaseModel):
    """冻结完整协议边界并拒绝多余字段，不允许缺失事实或未知结果伪通过。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Mode(str, Enum):
    """显式联合行动、完整策略展开和真实固定战斗三个不同验收入口。"""

    RESOLVE = "resolve"
    EXPAND = "expand"
    FIXED = "fixed"


class TurnLimits(_Contract):
    """当前测试不人为裁剪原 Python 概率；预算拒绝由原生/正式 ABI 专项检查。"""

    max_branches: int | None = None
    max_event_paths: int | None = None


class TurnInput(_Contract):
    """单条测试进程输入，内部状态/知识/行动全部有明确字段模型。"""

    mode: Mode
    state: BattleSnapshot
    type_chart: tuple[TypeEfficacySnapshot, ...]
    attacker_action: Action | None
    defender_action: Action | None
    attacker_policy: ActionStrategy
    defender_policy: ActionStrategy
    observer: BattleSide
    turn_limits: TurnLimits = TurnLimits()
    graph_limits: StateGraphLimits
    max_equation_nodes: int | None = None


class TransitionReply(_Contract):
    """每条完整概率、全部未来状态、每个事件字段/路径条件概率及来源。"""

    probability: ExactFraction
    state: BattleSnapshot
    paths: tuple[WeightedPath, ...]
    source_key: str | None


class TurnReply(_Contract):
    """完整回合/策略展开结果；阶段顺序和所有状态路径均逐项比较。"""

    kind: Literal["resolve", "expand"]
    transitions: tuple[TransitionReply, ...]
    phases: tuple[TurnPhase, ...]


class FixedReply(_Contract):
    """实际 Core 完整固定战斗：图、结构化事件、SCC、概率/期望或未知截断。"""

    kind: Literal["fixed"] = "fixed"
    graph: BuildReply
    solution: GraphReply


@dataclass(frozen=True)
class _TurnCase:
    """同一真实领域初始状态和选择合同，供旧公开执行器与 C++ 使用。"""

    state: BattleState
    mode: Mode
    attacker_action: BattleAction | None = None
    defender_action: BattleAction | None = None
    attacker_policy: ActionStrategy = ActionStrategy.uniform
    defender_policy: ActionStrategy = ActionStrategy.uniform
    observer: BattleSide = BattleSide.ATTACKER
    graph_limits: StateGraphLimits = StateGraphLimits()
    max_equation_nodes: int | None = None


class _TurnOracle:
    """只组装原工厂与原实际执行器；不在测试中实现命中、伤害、排序、PP、效果或图算法。"""

    @staticmethod
    def policy(strategy: ActionStrategy) -> ActionPolicy[BattleAction]:
        """strategy 是原稳定标识；返回原实际玩家策略，不复制概率公式。"""
        return UniformRandomPolicy[BattleAction]() if strategy is ActionStrategy.uniform else FirstLegalActionPolicy[BattleAction]()

    @staticmethod
    def resolver(state: BattleState) -> BattleEventStandardMoveTurnResolver:
        """state 的全部配置效果交给原工厂，按实际 application 调用链稳定去重。"""
        factory = PokemonChampionEffectFactory()
        unique: dict[tuple[str, str], BattleEffect] = {}
        for battler in (state.attacker, state.defender):
            effects: list[BattleEffect] = [factory.create_move_effect(move.effect_identifier) for move in battler.spec.moves if move.effect_identifier is not None]
            effects.extend((factory.create_ability_effect(battler.spec.ability), factory.create_item_effect(battler.spec.item)))
            for effect in effects:
                unique.setdefault((effect.coverage.source_kind.value, effect.coverage.identifier), effect)
        return BattleEventStandardMoveTurnResolver(effects=tuple(unique.values()))

    @staticmethod
    def transition(value: WeightedTransition[BattleState]) -> TransitionReply:
        """value 是原正式转移；只投影完整事实与精确条件历史，不重算结果。"""
        return TransitionReply(probability=_StateOracle.fraction(value.probability), state=_StateOracle.snapshot(value.state), source_key=value.source_key,
            paths=tuple(WeightedPath(events=tuple(_BuildOracle.event(event) for event in path), probability=_StateOracle.fraction(probability))
                for probability, path in value.event_summary.weighted_paths))

    @classmethod
    def expected(cls, case: _TurnCase) -> TurnReply | FixedReply:
        """case 为完整真实输入；原 structured resolver/策略 expander/BFS/solver 产生全部预期。"""
        resolver = cls.resolver(case.state)
        expander = _PolicyDrivenBattleStateExpander(resolver, cls.policy(case.attacker_policy), cls.policy(case.defender_policy))
        if case.mode is Mode.RESOLVE:
            assert case.attacker_action is not None and case.defender_action is not None
            resolution = resolver.resolve(case.state, case.attacker_action, case.defender_action)
            return TurnReply(kind="resolve", transitions=tuple(cls.transition(value) for value in resolution.transitions), phases=resolution.phase_order)
        if case.mode is Mode.EXPAND:
            return TurnReply(kind="expand", transitions=tuple(cls.transition(value) for value in expander.expand(case.state)), phases=STABLE_TURN_PHASES)
        graph = StateGraphBuilder(expander, case.graph_limits).build(case.state)
        projected = _BuildOracle.graph(graph)
        solved = PurePythonBattleGraphSolver(case.max_equation_nodes).solve(graph, case.observer)
        solution = GraphReply(components=projected.components, status=solved.status,
            win=None if solved.win_probability is None else _StateOracle.fraction(solved.win_probability),
            loss=None if solved.loss_probability is None else _StateOracle.fraction(solved.loss_probability),
            draw=None if solved.draw_probability is None else _StateOracle.fraction(solved.draw_probability),
            closed_cycle=None if solved.closed_cycle_probability is None else _StateOracle.fraction(solved.closed_cycle_probability),
            expected_turns=ExpectedTurns(status=solved.expected_turns.status,
                value=None if solved.expected_turns.value is None else _StateOracle.fraction(solved.expected_turns.value)))
        return FixedReply(graph=projected, solution=solution)

    @classmethod
    def compare(cls, runner: Path, cases: tuple[_TurnCase, ...]) -> None:
        """runner 是真实 C++ 可执行文件；cases 同时交给旧原始执行链，全字段精确相等。"""
        chart = tuple(TypeEfficacySnapshot(attacking=first, defending=second, percent=TypeHelper.get_type_efficacy(first, second)) for first in Type for second in Type)
        inputs = tuple(TurnInput(mode=case.mode, state=_StateOracle.snapshot(case.state), type_chart=chart,
            attacker_action=None if case.attacker_action is None else _ActionOracle.action(case.attacker_action),
            defender_action=None if case.defender_action is None else _ActionOracle.action(case.defender_action),
            attacker_policy=case.attacker_policy, defender_policy=case.defender_policy, observer=case.observer,
            graph_limits=case.graph_limits, max_equation_nodes=case.max_equation_nodes) for case in cases)
        expected = tuple(cls.expected(case) for case in cases)
        process = subprocess.run([str(runner)], input="\n".join(value.model_dump_json() for value in inputs) + "\n",
            text=True, capture_output=True, check=True, timeout=180)
        lines = process.stdout.splitlines()
        assert len(lines) == len(expected)
        for index, (line, reference) in enumerate(zip(lines, expected, strict=True)):
            actual = FixedReply.model_validate_json(line) if isinstance(reference, FixedReply) else TurnReply.model_validate_json(line)
            assert actual == reference, f"formal turn case {index} did not match"

    @staticmethod
    def random_state(randomizer: random.Random) -> BattleState:
        """randomizer 为固定种子；返回覆盖真实 PP/锁招/状态/天气/效果的合法原领域状态。"""
        state = _reference()
        for side in BattleSide:
            battler = state.battler(side)
            moves = tuple(replace(move, accuracy=randomizer.choice((None, 25, 50, 75, 100)), priority=randomizer.choice((-1, 0, 1, 3)),
                effect_identifier=randomizer.choice((None, "ice_punch", "fake_out", "brick_break"))) for move in battler.spec.moves)
            item = randomizer.choice(tuple(DamageItem))
            spec = replace(battler.spec, moves=moves, ability=randomizer.choice(tuple(DamageAbility)), item=item)
            slots = tuple(replace(slot, current_pp=randomizer.choice((0, 1, 2)), is_disabled=randomizer.randrange(8) == 0) for slot in battler.move_slots)
            volatile = (FlinchStatus(),) if randomizer.randrange(7) == 0 else ()
            major = randomizer.choice((None, BurnStatus(), ParalysisStatus()))
            battler = replace(battler, spec=spec, current_hp=randomizer.choice((0, 1, spec.stats.hp, max(1, spec.stats.hp // 2))),
                move_slots=slots, is_first_turn=randomizer.choice((False, True)), item_consumed=randomizer.choice((False, True)),
                status=CombatantStatus(major, frozenset(volatile)), stat_stages=StatStages(speed=randomizer.randint(-3, 3), attack=randomizer.randint(-3, 3)))
            if item is DamageItem.CHOICE_BAND and not battler.item_consumed and randomizer.choice((False, True)):
                battler = battler.with_choice_lock(randomizer.choice(moves).move_id)
            state = state.with_battler(side, battler)
        policy = replace(state.rules.damage_policy, random_damage_multipliers=randomizer.choice(((0.85, 0.93, 1.0), (0.0, 0.5, 1.0), (1.1, 0.4, 0.9))))
        field = BattleFieldState(weather=randomizer.choice((None, *Weather)), terrain=randomizer.choice((None, *Terrain)),
            attacker_side_conditions=SideConditions(reflect=randomizer.choice((False, True))), defender_side_conditions=SideConditions(light_screen=randomizer.choice((False, True))))
        return replace(state, rules=replace(state.rules, damage_policy=policy), field=field, turn_number=randomizer.randint(1, 10))


@pytest.fixture(scope="module")
def turn_runner() -> Path:
    """返回真实正式回合 runner，显式构建配置错误必须 FAIL，默认未构建才说明性跳过。"""
    configured = os.environ.get("PBI_CORE_VECTOR_RUNNER")
    directory = Path(configured).parent if configured else Path(__file__).resolve().parents[2] / "build/core"
    runner = directory / "pbi_turn_vectors"
    if not runner.is_file() or not os.access(runner, os.X_OK):
        if configured:
            pytest.fail("configured core build must contain pbi_turn_vectors")
        pytest.skip("run make test-core to enable formal turn differential tests")
    return runner


class TestCoreTurn:
    """正式原调用链的完整回合/策略/固定图差分，不用测试脚本作为战斗结果。"""

    def test_generated_structured_turns_and_policy_expansion(self, turn_runner: Path) -> None:
        """turn_runner 为真实 Core；96 显式行动与32完整策略展开，逐字段比较所有状态和事件。"""
        randomizer = random.Random(310673)
        cases: list[_TurnCase] = []
        generator = StandardLegalActionGenerator()
        for _ in range(96):
            state = _TurnOracle.random_state(randomizer)
            cases.append(_TurnCase(state, Mode.RESOLVE, randomizer.choice(generator.generate(state, BattleSide.ATTACKER)),
                randomizer.choice(generator.generate(state, BattleSide.DEFENDER))))
        for _ in range(32):
            state = _TurnOracle.random_state(randomizer)
            cases.append(_TurnCase(state, Mode.EXPAND, attacker_policy=randomizer.choice(tuple(ActionStrategy)), defender_policy=randomizer.choice(tuple(ActionStrategy))))
        _TurnOracle.compare(turn_runner, tuple(cases))

    def test_actual_fixed_battle_graph_and_unknown_budgets(self, turn_runner: Path) -> None:
        """turn_runner 为真实 Core；完整正式回合→策略→BFS→SCC→精确解，三类限额仍是未知。"""
        original = _reference()
        for side in BattleSide:
            battler = original.battler(side)
            moves = (replace(battler.spec.moves[0], max_pp=1, accuracy=75),)
            spec = replace(battler.spec, moves=moves, ability=DamageAbility.MULTISCALE if side is BattleSide.DEFENDER else DamageAbility.TECHNICIAN)
            battler = replace(battler, spec=spec, current_hp=20, move_slots=(MoveSlotState(moves[0].move_id, 1, 1, slot_id=9000 + moves[0].move_id),))
            original = original.with_battler(side, battler)
        original = replace(original, rules=replace(original.rules, damage_policy=replace(original.rules.damage_policy, random_damage_multipliers=(0.85, 1.0))))
        cases = [_TurnCase(original, Mode.FIXED, graph_limits=StateGraphLimits(max_nodes=128, max_edges=512, max_turns=8))]
        cases.extend(_TurnCase(original, Mode.FIXED, graph_limits=limits) for limits in (
            StateGraphLimits(max_nodes=1), StateGraphLimits(max_edges=1), StateGraphLimits(max_turns=1)))
        _TurnOracle.compare(turn_runner, tuple(cases))

    def test_full_sixteen_rolls_tie_and_dynamic_effect_boundaries(self, turn_runner: Path) -> None:
        """turn_runner 为真实 Core；完整16档及同速/免疫/动态特性/最后PP逐项比较全部替代事件历史。"""
        original = _reference()
        states = [original]
        defender = replace(original.defender, spec=replace(original.defender.spec, stats=replace(original.defender.spec.stats, speed=original.attacker.spec.stats.speed)))
        states.append(original.with_battler(BattleSide.DEFENDER, defender))
        first = original.attacker.spec.moves[0]
        fake_spec = replace(original.attacker.spec, moves=(replace(first, effect_identifier="fake_out", priority=3), *original.attacker.spec.moves[1:]))
        fake = original.with_battler(BattleSide.ATTACKER, replace(original.attacker, spec=fake_spec))
        states.append(fake)
        states.append(fake.with_battler(BattleSide.ATTACKER, fake.attacker.mark_first_turn_complete()))
        immune = fake.with_battler(BattleSide.DEFENDER, replace(fake.defender, spec=replace(fake.defender.spec, ability=DamageAbility.INNER_FOCUS)))
        states.append(immune)
        multiscale = original.with_battler(BattleSide.DEFENDER, replace(original.defender, spec=replace(original.defender.spec, ability=DamageAbility.MULTISCALE)))
        states.extend((multiscale, multiscale.with_battler(BattleSide.DEFENDER, multiscale.defender.with_current_hp(multiscale.defender.current_hp - 1))))
        empty_pp = original
        last_pp = original
        for side in BattleSide:
            battler = original.battler(side)
            empty_pp = empty_pp.with_battler(side, replace(battler, move_slots=tuple(replace(slot, current_pp=0) for slot in battler.move_slots)))
            last_pp = last_pp.with_battler(side, battler.with_move_slot(replace(battler.move_slots[0], current_pp=1)))
        states.extend((empty_pp, last_pp))
        inaccurate = original
        for side in BattleSide:
            battler = original.battler(side)
            moves = (replace(battler.spec.moves[0], accuracy=75), *battler.spec.moves[1:])
            inaccurate = inaccurate.with_battler(side, replace(battler, spec=replace(battler.spec, moves=moves)))
        states.append(inaccurate)
        states.append(original.with_battler(BattleSide.ATTACKER, original.attacker.with_current_hp(0)))
        normal_fake_spec = replace(fake.attacker.spec, moves=(replace(fake.attacker.spec.moves[0], move=replace(fake.attacker.spec.moves[0].move, type=Type.NORMAL)), *fake.attacker.spec.moves[1:]))
        ghost = fake.with_battler(BattleSide.ATTACKER, replace(fake.attacker, spec=normal_fake_spec))
        ghost = ghost.with_battler(BattleSide.DEFENDER, replace(ghost.defender, spec=replace(ghost.defender.spec, types=(Type.GHOST,))))
        states.append(ghost)
        generator = StandardLegalActionGenerator()
        cases = tuple(_TurnCase(state, Mode.RESOLVE, generator.generate(state, BattleSide.ATTACKER)[0], generator.generate(state, BattleSide.DEFENDER)[0]) for state in states)
        _TurnOracle.compare(turn_runner, cases)
