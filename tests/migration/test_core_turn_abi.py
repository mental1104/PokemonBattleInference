"""正式 C ABI 对照原结构化回合/固定战斗执行链，完整比较状态、事件、条件概率、图与解。"""
from __future__ import annotations

import random
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from pokeop.application.solver.graph_solver import BattleGraphSolveStatus
from pokeop.application.solver.models import GraphTruncationReason, StateGraphLimits
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.actions import StandardLegalActionGenerator
from pokeop.domain.battle.effects.protocols import EffectCoverageStatus
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.turn_phases import TurnPhase
from pokeop.domain.models.types import Type, TypeHelper
from tests.migration.test_core_actions_abi import Action, ActionStrategy, _ActionOracle
from tests.migration.test_core_battle_graph import BuildReply, BuildStatistics
from tests.migration.test_core_damage import ExactFraction, TypeEfficacySnapshot, damage_runner
from tests.migration.test_core_graph import ExpectedTurns
from tests.migration.test_core_state import BattleSnapshot, _StateOracle, _reference
from tests.migration.test_core_turn import FixedReply, Mode, TransitionReply, TurnLimits, _TurnCase, _TurnOracle


class _Contract(BaseModel):
    """固定边界冻结并拒绝未知字段，原始 JSON 到此结束。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExplicitSelection(_Contract):
    """完整显式双方行动，不与策略字段混用。"""
    mode: Literal["actions"] = "actions"
    attacker: Action
    defender: Action


class PolicySelection(_Contract):
    """正式玩家策略，概率仍由 Core 生成。"""
    mode: Literal["policies"] = "policies"
    attacker: ActionStrategy
    defender: ActionStrategy


class GeneratedLimits(_Contract):
    """旧在线应用默认生成图预算；None 回合限制继承 state.rules。"""
    max_nodes: int = 20000
    max_edges: int = 80000
    max_turns: int | None = None


class TurnOperation(_Contract):
    """正式单步回合操作，所有原状态 null 字段原样编码。"""
    kind: Literal["battle_turn"] = "battle_turn"
    state: BattleSnapshot
    type_chart: tuple[TypeEfficacySnapshot, ...]
    selection: Annotated[ExplicitSelection | PolicySelection, Field(discriminator="mode")]
    turn_limits: TurnLimits = TurnLimits()


class FixedOperation(_Contract):
    """真实自动构图操作，按需完整图，方程 None 保留原无限制语义。"""
    kind: Literal["fixed_battle"] = "fixed_battle"
    state: BattleSnapshot
    type_chart: tuple[TypeEfficacySnapshot, ...]
    attacker_policy: ActionStrategy
    defender_policy: ActionStrategy
    observer: BattleSide
    graph_limits: GeneratedLimits
    max_equation_nodes: int | None = None
    include_graph: Literal[True] = True


class TurnBatch(_Contract):
    """单个有界结果批次，避免把许多完整图挤入同一个 32MiB 输出。"""
    schema_version: Literal[1] = 1
    operations: tuple[Annotated[TurnOperation | FixedOperation, Field(discriminator="kind")], ...]


class CoverageAspect(_Contract):
    """明确尚未实现的子能力，名称不参与计算规则分发。"""
    source: Literal["move", "ability", "item", "status"]
    identifier: str
    capability: str


class TurnResult(_Contract):
    """全部真实后继与不可重排阶段，附带机制覆盖而不省略未知事实。"""
    kind: Literal["battle_turn"]
    transitions: tuple[TransitionReply, ...]
    phases: tuple[TurnPhase, ...]
    unsupported_aspects: tuple[CoverageAspect, ...]


class FixedResult(_Contract):
    """原概率结果和全图独立完整建模，不用无解概率零值填空。"""
    kind: Literal["fixed_battle"]
    observer: BattleSide
    status: BattleGraphSolveStatus
    win: ExactFraction | None
    loss: ExactFraction | None
    draw: ExactFraction | None
    closed_cycle: ExactFraction | None
    expected_turns: ExpectedTurns
    diagnostics: tuple[str, ...] = ()
    statistics: BuildStatistics
    truncations: tuple[GraphTruncationReason, ...]
    unsupported_aspects: tuple[CoverageAspect, ...]
    graph: BuildReply


class TurnEnvelope(_Contract):
    """当前正式版本与完整结果，错误或缺失 results 不能解码成成功。"""
    schema_version: Literal[1]
    engine_version: Literal["0.10.0"]
    rules_version: Literal["calculation-rules.v10"]
    results: tuple[Annotated[TurnResult | FixedResult, Field(discriminator="kind")], ...]


class _ABIOracle:
    """只调整传输形状，所有预期由已有原 Python oracle/工厂产生，不重写战斗算法。"""
    @staticmethod
    def request(case: _TurnCase) -> TurnBatch:
        """case 为原领域输入；返回正式 ABI 输入，完整保留状态 null、动作身份和知识。"""
        state = _StateOracle.snapshot(case.state)
        chart = tuple(TypeEfficacySnapshot(attacking=first, defending=second, percent=TypeHelper.get_type_efficacy(first, second)) for first in Type for second in Type)
        if case.mode is Mode.FIXED:
            operation = FixedOperation(state=state, type_chart=chart, attacker_policy=case.attacker_policy,
                defender_policy=case.defender_policy, observer=case.observer, max_equation_nodes=case.max_equation_nodes,
                graph_limits=GeneratedLimits(max_nodes=case.graph_limits.max_nodes or 20000,
                    max_edges=case.graph_limits.max_edges or 80000, max_turns=case.graph_limits.max_turns))
            return TurnBatch(operations=(operation,))
        if case.mode is Mode.RESOLVE:
            assert case.attacker_action is not None and case.defender_action is not None
            selection: ExplicitSelection | PolicySelection = ExplicitSelection(attacker=_ActionOracle.action(case.attacker_action), defender=_ActionOracle.action(case.defender_action))
        else:
            selection = PolicySelection(attacker=case.attacker_policy, defender=case.defender_policy)
        return TurnBatch(operations=(TurnOperation(state=state, type_chart=chart, selection=selection),))

    @staticmethod
    def compare(runner: Path, cases: tuple[_TurnCase, ...]) -> None:
        """runner 为当前已构建 ABI 程序；cases 的所有状态/事件/分数/图逐字段对照独立 Python。"""
        expected = tuple(_TurnOracle.expected(case) for case in cases)
        inputs = tuple(_ABIOracle.request(case) for case in cases)
        process = subprocess.run([str(runner.parent / "pbi_abi_vectors")], input="\n".join(value.model_dump_json() for value in inputs) + "\n",
            text=True, capture_output=True, check=True, timeout=180)
        lines = process.stdout.splitlines()
        assert len(lines) == len(expected)
        for case, line, reference in zip(cases, lines, expected, strict=True):
            envelope = TurnEnvelope.model_validate_json(line)
            assert len(envelope.results) == 1
            actual = envelope.results[0]
            if isinstance(reference, FixedReply):
                assert isinstance(actual, FixedResult)
                assert actual.graph == reference.graph
                assert actual.statistics == reference.graph.statistics and actual.truncations == reference.graph.truncations
                assert actual.observer == case.observer
                assert (actual.status, actual.win, actual.loss, actual.draw, actual.closed_cycle, actual.expected_turns) == (
                    reference.solution.status, reference.solution.win, reference.solution.loss, reference.solution.draw,
                    reference.solution.closed_cycle, reference.solution.expected_turns)
            else:
                assert isinstance(actual, TurnResult)
                assert actual.transitions == reference.transitions and actual.phases == reference.phases
            # 部分机制覆盖取自原工厂元数据；状态门禁缺口是新接口的显式说明，另有固定样本覆盖。
            reported = {(value.source, value.identifier, value.capability) for value in actual.unsupported_aspects if value.source != "status"}
            legacy = {(effect.coverage.source_kind.value, effect.coverage.identifier, aspect)
                for effect in _TurnOracle.resolver(case.state).effects for aspect in effect.coverage.unsupported_aspects}
            legacy.update((effect.coverage.source_kind.value, effect.coverage.identifier, capability.identifier)
                for effect in _TurnOracle.resolver(case.state).effects for capability in effect.coverage.capabilities
                if capability.status is EffectCoverageStatus.UNSUPPORTED)
            assert reported == legacy


class TestTurnABI:
    """正式入站合同走同 Core 真实回合，包含完整路径与原保护未知语义。"""
    def test_structured_turns_and_policies(self, damage_runner: Path) -> None:
        """damage_runner 为当前构建目录；32 显式回合、16 策略展开和完整16档回合逐字段精确一致。"""
        randomizer = random.Random(9033)
        cases: list[_TurnCase] = []
        generator = StandardLegalActionGenerator()
        for _ in range(32):
            state = _TurnOracle.random_state(randomizer)
            cases.append(_TurnCase(state, Mode.RESOLVE, randomizer.choice(generator.generate(state, BattleSide.ATTACKER)), randomizer.choice(generator.generate(state, BattleSide.DEFENDER))))
        for _ in range(16):
            cases.append(_TurnCase(_TurnOracle.random_state(randomizer), Mode.EXPAND,
                attacker_policy=randomizer.choice(tuple(ActionStrategy)), defender_policy=randomizer.choice(tuple(ActionStrategy))))
        state = _reference()
        cases.append(_TurnCase(state, Mode.RESOLVE, generator.generate(state, BattleSide.ATTACKER)[0], generator.generate(state, BattleSide.DEFENDER)[0]))
        _ABIOracle.compare(damage_runner, tuple(cases))

    def test_actual_fixed_graph_and_truncations(self, damage_runner: Path) -> None:
        """damage_runner 为当前 ABI；完整 fixed 图和三种预算截断对照原正式构图和 solver。"""
        state = _reference()
        for side in BattleSide:
            battler = state.battler(side)
            move = replace(battler.spec.moves[0], max_pp=1, accuracy=75)
            spec = replace(battler.spec, moves=(move,), ability=DamageAbility.MULTISCALE if side is BattleSide.DEFENDER else DamageAbility.TECHNICIAN)
            state = state.with_battler(side, replace(battler, spec=spec, current_hp=20,
                move_slots=(MoveSlotState(move.move_id, 1, 1, slot_id=9000 + move.move_id),)))
        state = replace(state, rules=replace(state.rules, damage_policy=replace(state.rules.damage_policy, random_damage_multipliers=(0.85, 1.0))))
        cases = tuple(_TurnCase(state, Mode.FIXED, graph_limits=limits) for limits in (
            StateGraphLimits(max_nodes=128, max_edges=512, max_turns=8), StateGraphLimits(max_nodes=1),
            StateGraphLimits(max_edges=1), StateGraphLimits(max_turns=1)))
        _ABIOracle.compare(damage_runner, cases)
