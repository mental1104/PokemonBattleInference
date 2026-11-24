"""逐字段比较真实 C++ EV/性格枚举与原 StatDimensionProvider，不复制枚举算法。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.application.configuration_space.commands import PokemonSpaceCommand, StatSpaceCommand
from pokeop.application.configuration_space.model_base import StatEnumerationMode
from pokeop.application.configuration_space.provider_core import ConfigurationGenerationContext, StatDimensionValue
from pokeop.application.configuration_space.stat_provider import StatDimensionProvider
from pokeop.domain.battle.effects.factories import PokemonChampionEffectFactory
from pokeop.domain.battle.stats import NatureModifier, StatValues
from pokeop.domain.models.pokemon_fields import StatField
from tests.application.configuration_space.helpers import _dragonite_profile


Stats = tuple[int, int, int, int, int, int]
Nature = tuple[float, float, float, float, float]


class _Contract(BaseModel):
    """完整进程边界，冻结字段并拒绝未知投影。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Preset(_Contract):
    """由旧应用层解析出的预设快照，未计算最终能力。"""

    ivs: Stats
    evs: Stats
    nature: Nature
    label: str


class StatInput(_Contract):
    """明确区分预设和受控模式的测试协议。"""

    base: Stats
    level: int
    max_raw_profiles: int
    mode: Literal["preset", "controlled"]
    presets: tuple[Preset, ...] = ()
    fields: tuple[int, ...] = ()
    ev_values: tuple[int, ...] = ()
    natures: tuple[Nature, ...] = ()


class StatClass(Preset):
    """最终能力类，包含原始成员计数与第一个完整投入代表。"""

    actual: Stats
    member_count: str


class StatReply(_Contract):
    """独立执行结果，所有原始成员必须被精确归入一个类。"""

    classes: tuple[StatClass, ...]
    raw_profile_count: str


class ErrorReply(_Contract):
    """完整失败，不能混入任何部分归一化的空间结果。"""

    error: str


@dataclass(frozen=True)
class _Case:
    """保存唯一原命令事实源，派生进程输入和原 Python oracle。"""

    base: Stats
    level: int
    command: StatSpaceCommand


class _Oracle:
    """仅负责两端 DTO 投影，枚举/过滤/能力/归并全部委托原业务实现。"""

    @staticmethod
    def values(stats: StatValues) -> Stats:
        """将旧能力值按固定顺序输出；参数为只读值，返回完整六项。"""
        return (stats.hp, stats.attack, stats.defense, stats.special_attack, stats.special_defense, stats.speed)

    @staticmethod
    def nature(nature: NatureModifier) -> Nature:
        """将旧完整性格投影为五轴；不会推导或改变倍率。"""
        return (nature.attack, nature.defense, nature.special_attack, nature.special_defense, nature.speed)

    @staticmethod
    def context(case: _Case) -> ConfigurationGenerationContext:
        """为 case 构造真实 provider context；使用公开类型而非动态假 context。"""
        return ConfigurationGenerationContext(
            profile=replace(_dragonite_profile(), base_stats=StatValues(*case.base)),
            command=PokemonSpaceCommand(stats=case.command, level=case.level),
            effect_factory=PokemonChampionEffectFactory(),
            side="attacker",
        )

    @classmethod
    def request(cls, case: _Case) -> StatInput:
        """只解析预设成未计算快照，受控模式完整命令直接送入 C++。"""
        command = case.command
        if command.mode is StatEnumerationMode.PRESET:
            return StatInput(
                base=case.base, level=case.level, max_raw_profiles=command.max_raw_profiles, mode="preset",
                presets=tuple(
                    Preset(ivs=cls.values(profile.ivs), evs=cls.values(profile.evs),
                           nature=cls.nature(profile.nature_modifier), label=label)
                    for profile, label in StatDimensionProvider()._raw_profiles(cls.context(case))
                ),
            )
        return StatInput(
            base=case.base, level=case.level, max_raw_profiles=command.max_raw_profiles, mode="controlled",
            fields=tuple(tuple(StatField).index(field) for field in command.relevant_fields),
            ev_values=command.ev_values, natures=tuple(cls.nature(nature) for nature in command.nature_modifiers),
        )

    @classmethod
    def reference(cls, case: _Case) -> StatReply:
        """执行原 provider 并投影全部类，保持代表和首次出现顺序。"""
        expansion = StatDimensionProvider().expand(cls.context(case))
        classes: list[StatClass] = []
        for value in expansion.values:
            assert isinstance(value, StatDimensionValue)
            profile = value.stat_profile
            classes.append(StatClass(
                ivs=cls.values(profile.ivs), evs=cls.values(profile.evs), nature=cls.nature(profile.nature_modifier),
                label=value.label, actual=cls.values(value.actual_stats), member_count=str(value.member_count),
            ))
        return StatReply(classes=tuple(classes), raw_profile_count=str(expansion.raw_member_count))

    @staticmethod
    def run(runner: Path, requests: tuple[StatInput, ...]) -> tuple[StatReply | ErrorReply, ...]:
        """以单进程批量运行真实 C++，严格读取每条成功或失败结果。"""
        result = subprocess.run(
            [str(runner)], input="".join(request.model_dump_json() + "\n" for request in requests),
            text=True, capture_output=True, check=True, timeout=30,
        )
        lines = result.stdout.splitlines()
        assert len(lines) == len(requests)
        return tuple(
            ErrorReply.model_validate_json(line) if '"error"' in line else StatReply.model_validate_json(line)
            for line in lines
        )


@pytest.fixture
def configuration_stats_runner() -> Path:
    """返回外部已构建入口；未提供编译证据时显式 skip，不下载编译器。"""
    value = os.getenv("PBI_CONFIGURATION_STATS_RUNNER")
    if value is None:
        pytest.skip("PBI_CONFIGURATION_STATS_RUNNER is required")
    runner = Path(value)
    assert runner.is_file()
    return runner


class TestCoreConfigurationStats:
    """真实有效成员过滤、能力归并、代表保留与归并前预算的独立差分。"""

    def test_controlled_and_presets(self, configuration_stats_runner: Path) -> None:
        """比较 120 组随机命令、七内置预设和跨 510 总投入边界的完整结果。"""
        rng = random.Random(31149)
        cases = [_Case((91, 134, 95, 100, 100, 80), 50, StatSpaceCommand(
            preset_keys=("max_atk_plus", "max_atk_neutral", "max_hp", "max_hp_def", "max_hp_def_plus", "max_hp_spdef", "max_hp_spdef_plus"),
        ))]
        natures = (NatureModifier.neutral(), NatureModifier(1.1, 1.0, 0.9, 1.0, 1.0), NatureModifier.increase(StatField.DEFENSE))
        for _ in range(120):
            cases.append(_Case(
                tuple(rng.randint(1, 255) for _ in range(6)), rng.choice((1, 5, 50, 100)),
                StatSpaceCommand(
                    mode=StatEnumerationMode.CONTROLLED, preset_keys=(),
                    relevant_fields=tuple(rng.sample(tuple(StatField), rng.randint(1, 4))),
                    ev_values=rng.choice(((0, 1, 2, 3, 4), (0, 252), (4, 8, 12), (124, 252))),
                    nature_modifiers=natures[:rng.randint(1, len(natures))], max_raw_profiles=4096,
                ),
            ))
        case_values = tuple(cases)
        actual = _Oracle.run(configuration_stats_runner, tuple(_Oracle.request(case) for case in case_values))
        assert actual == tuple(_Oracle.reference(case) for case in case_values)

    def test_raw_budget_precedes_deduplication(self, configuration_stats_runner: Path) -> None:
        """低等级四个 EV 值虽归并一类，3 原始成员预算必须整体拒绝。"""
        case = _Case((80, 80, 80, 80, 80, 80), 1, StatSpaceCommand(
            mode=StatEnumerationMode.CONTROLLED, preset_keys=(), relevant_fields=(StatField.ATTACK,),
            ev_values=(0, 1, 2, 3), max_raw_profiles=3,
        ))
        with pytest.raises(ValueError, match="max_raw_profiles"):
            _Oracle.reference(case)
        result = _Oracle.run(configuration_stats_runner, (_Oracle.request(case),))[0]
        assert isinstance(result, ErrorReply)
        assert "max_raw_profiles" in result.error

    def test_preserves_custom_nature_binary64_and_labels(self, configuration_stats_runner: Path) -> None:
        """旧NatureModifier允许任意有限倍率；比较实际floor和代表label，不能缩成25性格。"""
        rng = random.Random(41149)
        multipliers = (0.0, -0.0, 0.125, 0.5, 2.5, 1.123456789, 1e-5, 1e-4, 5e-324, 1e-320)
        cases: list[_Case] = []
        for index in range(40):
            value = multipliers[index] if index < len(multipliers) else rng.uniform(-0.5, 2.0)
            cases.append(_Case((80, 80, 80, 80, 80, 80), 50, StatSpaceCommand(
                mode=StatEnumerationMode.CONTROLLED, preset_keys=(), relevant_fields=(StatField.HP,), ev_values=(0,),
                nature_modifiers=(NatureModifier(attack=value),),
            )))
        actual = _Oracle.run(configuration_stats_runner, tuple(_Oracle.request(case) for case in cases))
        assert actual == tuple(_Oracle.reference(case) for case in cases)
