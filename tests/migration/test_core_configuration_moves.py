"""真实招式候选覆盖过滤、无序组合和成员权重逐字段差分。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.application.configuration_space.commands import MoveSpaceCommand, PokemonSpaceCommand
from pokeop.application.configuration_space.model_base import MechanismSupportStatus
from pokeop.application.configuration_space.move_provider import MoveSetDimensionProvider
from pokeop.application.configuration_space.projections import MoveConfigurationCandidate
from pokeop.application.configuration_space.provider_core import ConfigurationGenerationContext, MoveSetDimensionValue
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.effects.factories import PokemonChampionEffectFactory
from pokeop.domain.battle.effects.protocols import EffectCoverageStatus
from pokeop.domain.battle.specs import MoveSpec
from pokeop.domain.models.types import Type
from tests.application.configuration_space.helpers import _dragonite_profile


class _Contract(BaseModel):
    """稳定完整协议；拒绝额外字段并冻结结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Move(_Contract):
    """已读取的完整招式快照，JSON边界不推导机制。"""

    move_id: int
    name: str
    type: int
    category: int
    power: int
    max_pp: int
    priority: int
    accuracy: int | None
    effect_identifier: str | None


class Candidate(_Contract):
    """Repository合法候选与可执行机制覆盖分开存储。"""

    move_id: int
    identifier: str
    move: Move | None
    effect_identifier: str | None
    support: MechanismSupportStatus
    reason: str


class MoveInput(_Contract):
    """完整候选和原命令边界，不传预先过滤后的笛卡尔空间。"""

    candidates: tuple[Candidate, ...]
    requested_ids: tuple[int, ...]
    slot_counts: tuple[int, ...]
    max_raw_combinations: int


class ConfiguredMove(_Contract):
    """原行为签名repr排序键和第一代表名称。"""

    key: str
    name: str


class MoveClass(_Contract):
    """完整无序组合与归并前成员乘数。"""

    moves: tuple[ConfiguredMove, ...]
    member_count: str


class Coverage(_Contract):
    """每个合法候选的原覆盖字段和精确排除原因。"""

    identifier: str
    support: MechanismSupportStatus
    included: bool
    reason: str
    factory_status: EffectCoverageStatus | None


class MoveReply(_Contract):
    """成功分区，含所有被排除候选，不静默缩减覆盖报告。"""

    classes: tuple[MoveClass, ...]
    coverage: tuple[Coverage, ...]
    raw_combination_count: str


class ErrorReply(_Contract):
    """超预算等整体拒绝，不能携带局部空间。"""

    error: str


@dataclass(frozen=True)
class _Case:
    """唯一原候选事实源，供两侧独立计算消费。"""

    candidates: tuple[MoveConfigurationCandidate, ...]
    command: MoveSpaceCommand


class _Oracle:
    """使用原完整 provider；本类只投影进程输入/输出。"""

    @staticmethod
    def context(case: _Case) -> ConfigurationGenerationContext:
        """由只读case构造正式context，保留候选顺序与重复projection。"""
        return ConfigurationGenerationContext(
            profile=replace(_dragonite_profile(), moves=case.candidates),
            command=PokemonSpaceCommand(moves=case.command),
            effect_factory=PokemonChampionEffectFactory(), side="attacker",
        )

    @staticmethod
    def request(case: _Case) -> MoveInput:
        """将原候选转成未过滤完整快照；不计算组合或effect覆盖。"""
        candidates: list[Candidate] = []
        for value in case.candidates:
            spec = value.move_spec
            move = None if spec is None else Move(
                move_id=spec.move_id, name=spec.move.name, type=spec.move.type.value,
                category=tuple(MoveCategory).index(spec.move.category), power=spec.move.power,
                max_pp=spec.max_pp, priority=spec.priority, accuracy=spec.accuracy, effect_identifier=spec.effect_identifier,
            )
            candidates.append(Candidate(move_id=value.move_id, identifier=value.identifier, move=move,
                effect_identifier=value.effect_identifier, support=value.support_status, reason=value.support_reason))
        return MoveInput(candidates=tuple(candidates), requested_ids=case.command.candidate_move_ids,
            slot_counts=case.command.slot_counts, max_raw_combinations=case.command.max_raw_combinations)

    @classmethod
    def reference(cls, case: _Case) -> MoveReply:
        """真实原provider负责筛选、归并、组合、排序及预算。"""
        expansion = MoveSetDimensionProvider().expand(cls.context(case))
        classes: list[MoveClass] = []
        for value in expansion.values:
            assert isinstance(value, MoveSetDimensionValue)
            classes.append(MoveClass(moves=tuple(ConfiguredMove(key=repr(move.behavior_signature), name=move.move_spec.move.name)
                for move in value.moves), member_count=str(value.member_count)))
        return MoveReply(classes=tuple(classes), raw_combination_count=str(expansion.raw_member_count), coverage=tuple(
            Coverage(identifier=record.identifier, support=record.support_status, included=record.included,
                     reason=record.reason, factory_status=record.factory_status)
            for record in expansion.coverage_records
        ))

    @staticmethod
    def run(runner: Path, requests: tuple[MoveInput, ...]) -> tuple[MoveReply | ErrorReply, ...]:
        """单进程批量执行真实C++，逐条严格解析成功或失败。"""
        result = subprocess.run([str(runner)], input="".join(request.model_dump_json() + "\n" for request in requests),
            text=True, capture_output=True, check=True, timeout=30)
        lines = result.stdout.splitlines()
        assert len(lines) == len(requests)
        return tuple(ErrorReply.model_validate_json(line) if '"error"' in line else MoveReply.model_validate_json(line) for line in lines)


@pytest.fixture
def configuration_moves_runner() -> Path:
    """外部实际编译入口；缺少时明确skip，不把mock当作Core验证。"""
    value = os.getenv("PBI_CONFIGURATION_MOVES_RUNNER")
    if value is None:
        pytest.skip("PBI_CONFIGURATION_MOVES_RUNNER is required")
    runner = Path(value)
    assert runner.is_file()
    return runner


class TestCoreConfigurationMoves:
    """真实合法性与机制覆盖过滤、无序组合和原始成员计数差分。"""

    def test_complete_candidate_filtering(self, configuration_moves_runner: Path) -> None:
        """比较160组完整候选池，包括重复projection、同ID不同配置和无effect变化招式。"""
        rng = random.Random(28531)
        cases: list[_Case] = []
        for _ in range(160):
            candidates: list[MoveConfigurationCandidate] = []
            for index in range(rng.randint(1, 9)):
                identifier = rng.randint(1, 6)
                category = rng.choice(tuple(MoveCategory))
                effect = rng.choice((None, "ice-punch", "fake_out", "brick break", "unimplemented"))
                spec = MoveSpec(move_id=identifier,
                    move=BattleMove(f"candidate-{index}", rng.choice((Type.NORMAL, Type.ICE)), category, 0 if category is MoveCategory.STATUS else rng.choice((40, 80))),
                    max_pp=rng.choice((5, 10)), priority=rng.choice((-1, 0, 2)), accuracy=rng.choice((None, 75, 100)))
                candidates.append(MoveConfigurationCandidate(move_spec=spec, effect_identifier=effect,
                    support_status=rng.choice(tuple(MechanismSupportStatus)), candidate_identifier=f"projection-{index}"))
            if rng.choice((True, False)):
                candidates.append(replace(candidates[0], candidate_identifier="duplicate-projection"))
            command = MoveSpaceCommand(candidate_move_ids=rng.choice(((), (1, 2, 3))),
                slot_counts=rng.choice(((), (1,), (1, 2), (3,))), max_raw_combinations=10000)
            cases.append(_Case(tuple(candidates), command))
        actual = _Oracle.run(configuration_moves_runner, tuple(_Oracle.request(case) for case in cases))
        assert actual == tuple(_Oracle.reference(case) for case in cases)

    def test_combination_budget_counts_duplicate_members(self, configuration_moves_runner: Path) -> None:
        """三个相同projection归并为一类，预算仍必须拒绝其三个原始成员。"""
        candidate = MoveConfigurationCandidate(move_spec=MoveSpec(move_id=1,
            move=BattleMove("basic", Type.NORMAL, MoveCategory.PHYSICAL, 40), max_pp=10))
        case = _Case((candidate, candidate, candidate), MoveSpaceCommand(slot_counts=(1,), max_raw_combinations=2))
        with pytest.raises(ValueError, match="max_raw_combinations"):
            _Oracle.reference(case)
        result = _Oracle.run(configuration_moves_runner, (_Oracle.request(case),))[0]
        assert isinstance(result, ErrorReply)
        assert "max_raw_combinations" in result.error
