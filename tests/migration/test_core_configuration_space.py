"""标准四维真实候选生成、原类排序和两种精确权重假设的端到端差分。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.application.configuration_space.commands import (
    AbilitySpaceCommand, GenerateConfigurationSpaceCommand, ItemSpaceCommand,
    MoveSpaceCommand, PokemonSpaceCommand, StatSpaceCommand,
)
from pokeop.application.configuration_space.generator import (
    GenerateConfigurationSpaceUseCase, PokemonConfigurationGenerator, _PokemonConfigurationSpace,
)
from pokeop.application.configuration_space.model_base import ConfigurationWeightAssumption, MechanismSupportStatus, StatEnumerationMode
from pokeop.application.configuration_space.projections import AbilityConfigurationCandidate, PokemonConfigurationProfile
from pokeop.domain.battle.effects.factories import PokemonChampionEffectFactory
from pokeop.domain.battle.stats import NatureModifier
from pokeop.domain.models.pokemon_fields import StatField
from tests.application.configuration_space.helpers import _dragonite_profile, _move
from pokeop.domain.models.types import Type
from tests.migration.test_core_configuration_moves import Coverage, MoveInput, _Case as _MoveCase, _Oracle as _MoveOracle
from tests.migration.test_core_configuration_stats import Nature, StatInput, Stats, _Case as _StatCase, _Oracle as _StatOracle


class _Contract(BaseModel):
    """冻结完整测试进程边界，任一字段缺失都不能算差分成功。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Ability(_Contract):
    """原合法特性候选，无预先factory过滤。"""

    identifier: str
    support: MechanismSupportStatus
    reason: str


class SideInput(_Contract):
    """一侧原知识与原命令的完整投影，组合/过滤/归并不在适配层完成。"""

    ruleset_id: str
    version_group_id: int
    pokemon_id: int
    name: str
    types: tuple[int, ...]
    can_evolve: bool
    moves: MoveInput
    stats: StatInput
    abilities: tuple[Ability, ...]
    requested_abilities: tuple[str, ...]
    items: tuple[str | None, ...]
    max_raw_configurations: int


class SpaceInput(_Contract):
    """双方相同规则轴、显式权重假设与归并前配对保护。"""

    attacker: SideInput
    defender: SideInput
    weight_assumption: ConfigurationWeightAssumption
    max_raw_pairs: int


class ConfigurationClass(_Contract):
    """完整行为repr、首个原始投入代表及精确成员数。"""

    key: str
    member_count: str
    ivs: Stats
    evs: Stats
    nature: Nature
    stat_label: str
    move_names: tuple[str, ...]


class SideCoverage(Coverage):
    """原provider维度归属，不把双方覆盖记录混淆。"""

    dimension: Literal["moves", "ability", "item"]


class SideReply(_Contract):
    """全部已归并单侧配置与完整候选覆盖。"""

    classes: tuple[ConfigurationClass, ...]
    coverage: tuple[SideCoverage, ...]
    raw_configuration_count: str


class PairClass(_Contract):
    """原pair顺序和精确分数，没有浮点归一化。"""

    attacker_key: str
    defender_key: str
    member_count: str
    numerator: str
    denominator: str


class SpaceReply(_Contract):
    """完整双侧分区；任一方失败不能以更小分母替代。"""

    attacker: SideReply
    defender: SideReply
    pairs: tuple[PairClass, ...]
    raw_pair_count: str


class ErrorReply(_Contract):
    """整个空间失败，不能带部分结果。"""

    error: str


@dataclass(frozen=True)
class _Side:
    """完整原知识和命令事实源。"""

    profile: PokemonConfigurationProfile
    command: PokemonSpaceCommand


@dataclass(frozen=True)
class _Case:
    """双侧真实候选案例和权重约定。"""

    attacker: _Side
    defender: _Side
    assumption: ConfigurationWeightAssumption
    max_raw_pairs: int = 1000000


class _Oracle:
    """边界仅投影事实，算法全部调用原生成器/用例。"""

    @staticmethod
    def side_request(side: _Side) -> SideInput:
        """将完整原profile/command映射为Core输入，保留全部候选。"""
        profile, command = side.profile, side.command
        return SideInput(
            ruleset_id=profile.ruleset_id, version_group_id=profile.version_group_id,
            pokemon_id=profile.pokemon_id, name=profile.name, types=tuple(value.value for value in profile.types),
            can_evolve=profile.can_evolve,
            moves=_MoveOracle.request(_MoveCase(profile.moves, command.moves)),
            stats=_StatOracle.request(_StatCase(_StatOracle.values(profile.base_stats), command.level, command.stats)),
            abilities=tuple(Ability(identifier=value.identifier, support=value.support_status.value, reason=value.support_reason) for value in profile.abilities),
            requested_abilities=command.abilities.candidate_identifiers, items=command.items.candidate_identifiers,
            max_raw_configurations=command.max_raw_configurations,
        )

    @classmethod
    def request(cls, case: _Case) -> SpaceInput:
        """生成完整输入；不把最终state或预构造pair送入Core。"""
        return SpaceInput(attacker=cls.side_request(case.attacker), defender=cls.side_request(case.defender),
            weight_assumption=case.assumption, max_raw_pairs=case.max_raw_pairs)

    @staticmethod
    def side_reply(space: _PokemonConfigurationSpace) -> SideReply:
        """投影原单侧行为、首代表与覆盖，不重写原去重算法。"""
        classes: list[ConfigurationClass] = []
        for value in space.equivalence_classes:
            config = value.representative
            profile = config.stat_profile
            classes.append(ConfigurationClass(key=repr(config.behavior_signature), member_count=str(value.member_count),
                ivs=_StatOracle.values(profile.ivs), evs=_StatOracle.values(profile.evs), nature=_StatOracle.nature(profile.nature_modifier),
                stat_label=next(label for dimension, label in config.dimension_labels if dimension == "stats"),
                move_names=tuple(move.move_spec.move.name for move in config.moves)))
        return SideReply(classes=tuple(classes), raw_configuration_count=str(space.raw_configuration_count),
            coverage=tuple(SideCoverage(dimension=record.dimension_key, identifier=record.identifier, support=record.support_status,
                included=record.included, reason=record.reason, factory_status=record.factory_status) for record in space.coverage_records))

    @classmethod
    def reference(cls, case: _Case) -> SpaceReply:
        """同时执行原单侧generator和完整pair用例，精确比较原权重和顺序。"""
        generator = PokemonConfigurationGenerator(PokemonChampionEffectFactory())
        first = generator.generate(case.attacker.profile, case.attacker.command, side="attacker")
        second = generator.generate(case.defender.profile, case.defender.command, side="defender")
        result = GenerateConfigurationSpaceUseCase(generator, generator).execute(
            GenerateConfigurationSpaceCommand(attacker=case.attacker.command, defender=case.defender.command,
                weight_assumption=case.assumption, max_raw_configuration_pairs=case.max_raw_pairs),
            attacker_profile=case.attacker.profile, defender_profile=case.defender.profile,
        )
        return SpaceReply(attacker=cls.side_reply(first), defender=cls.side_reply(second),
            raw_pair_count=str(result.statistics.raw_configuration_count), pairs=tuple(PairClass(
                attacker_key=repr(value.representative.attacker.behavior_signature), defender_key=repr(value.representative.defender.behavior_signature),
                member_count=str(value.member_count), numerator=str(value.weight.value.numerator), denominator=str(value.weight.value.denominator),
            ) for value in result.equivalence_classes))

    @staticmethod
    def run(runner: Path, requests: tuple[SpaceInput, ...]) -> tuple[SpaceReply | ErrorReply, ...]:
        """批量运行真实Core，逐条检查完整成功或整体失败。"""
        result = subprocess.run([str(runner)], input="".join(value.model_dump_json() + "\n" for value in requests),
            text=True, capture_output=True, check=True, timeout=30)
        lines = result.stdout.splitlines()
        assert len(lines) == len(requests)
        return tuple(ErrorReply.model_validate_json(line) if '"error"' in line else SpaceReply.model_validate_json(line) for line in lines)


@pytest.fixture
def configuration_space_runner() -> Path:
    """外部实际构建入口；未提供时显式skip，不伪造Core结果。"""
    value = os.getenv("PBI_CONFIGURATION_SPACE_RUNNER")
    if value is None:
        pytest.skip("PBI_CONFIGURATION_SPACE_RUNNER is required")
    runner = Path(value)
    assert runner.is_file()
    return runner


class TestCoreConfigurationSpace:
    """真实完整四维分区与原始/等价类两种精确权重。"""

    def test_real_candidates_and_both_weights(self, configuration_space_runner: Path) -> None:
        """36组双侧原候选各比较两种权重，包含partial/unknown特性、归并和排序。"""
        rng = random.Random(32149)
        cases: list[_Case] = []
        for _ in range(36):
            sides: list[_Side] = []
            for index in range(2):
                profile = replace(_dragonite_profile(), pokemon_id=149 + index,
                    abilities=(AbilityConfigurationCandidate("multiscale"), AbilityConfigurationCandidate("Multiscale"),
                               AbilityConfigurationCandidate("technician"), AbilityConfigurationCandidate("inner-focus"), AbilityConfigurationCandidate("pressure")),
                    moves=(_move(245, "extreme-speed", Type.NORMAL, 80, pp=5, priority=2),
                           _move(8, "ice-punch", Type.ICE, 75, effect_identifier="ice_punch")))
                command = PokemonSpaceCommand(
                    moves=MoveSpaceCommand(slot_counts=rng.choice(((), (1,)))),
                    stats=StatSpaceCommand(mode=StatEnumerationMode.CONTROLLED, preset_keys=(),
                        relevant_fields=(rng.choice(tuple(StatField)),), ev_values=(0, 1, 4),
                        nature_modifiers=rng.choice(((NatureModifier.neutral(),), (NatureModifier.neutral(), NatureModifier.increase(StatField.ATTACK))))),
                    abilities=AbilitySpaceCommand(rng.choice(((), ("multiscale",), ("technician", "multiscale")))),
                    items=ItemSpaceCommand(rng.choice(((None, "life-orb"), (None,), ("choice-band", "unimplemented")))),
                    level=rng.choice((1, 50, 100)),
                )
                sides.append(_Side(profile, command))
            cases.extend(_Case(sides[0], sides[1], assumption) for assumption in ConfigurationWeightAssumption)
        actual = _Oracle.run(configuration_space_runner, tuple(_Oracle.request(case) for case in cases))
        assert actual == tuple(_Oracle.reference(case) for case in cases)

    def test_rejects_original_member_budget(self, configuration_space_runner: Path) -> None:
        """真实原成员预算拒绝，不因归并后的少数类绕过保护。"""
        side = _Side(replace(_dragonite_profile(), abilities=(AbilityConfigurationCandidate("multiscale"),)), PokemonSpaceCommand(
            moves=MoveSpaceCommand(candidate_move_ids=(245,)), abilities=AbilitySpaceCommand(("multiscale",)), items=ItemSpaceCommand((None,)),
            stats=StatSpaceCommand(mode=StatEnumerationMode.CONTROLLED, preset_keys=(), relevant_fields=(StatField.HP,), ev_values=(0, 1, 2, 3)), level=1,
        ))
        case = _Case(side, side, ConfigurationWeightAssumption.UNIFORM_RAW_CONFIGURATION, max_raw_pairs=15)
        with pytest.raises(ValueError, match="max_raw_configuration_pairs"):
            _Oracle.reference(case)
        result = _Oracle.run(configuration_space_runner, (_Oracle.request(case),))[0]
        assert isinstance(result, ErrorReply)
        assert "max_raw_configuration_pairs" in result.error
