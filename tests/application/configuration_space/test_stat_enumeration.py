"""验证配置空间受控枚举、归并、覆盖统计和运行保护。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

import pytest

from pokeop.application.configuration_space import (
    AbilityConfigurationCandidate,
    AbilitySpaceCommand,
    ConfigurationGenerationContext,
    ConfigurationSpaceError,
    ConfigurationWeightAssumption,
    DimensionExpansion,
    GenerateConfigurationSpaceCommand,
    GenerateConfigurationSpaceUseCase,
    ItemSpaceCommand,
    MechanismSupportStatus,
    MoveSpaceCommand,
    OpaqueDimensionValue,
    PokemonConfigurationProfile,
    PokemonSpaceCommand,
    StatEnumerationMode,
    StatSpaceCommand,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.stats import NatureModifier, StatValues
from pokeop.domain.models.pokemon_fields import StatField
from pokeop.domain.models.types import Type
from tests.application.configuration_space.helpers import (
    _FakeDimensionProvider,
    _FakeEffectFactory,
    _dragonite_profile,
    _generator,
    _move,
    _single_command,
    _weavile_profile,
)


def test_controlled_ev_values_merge_by_final_level_fifty_stats() -> None:
    """
    受控枚举在等级 50 下应以最终实际能力值而不是原始 EV 整数判等：HP EV 为 0、1、2、3 时都落入同一个 floor 桶，HP EV 为 4
    时进入下一个实际数值，因此攻击方原始五种方案只能形成两个行为等价类；成员数量必须分别保持为四和一，均匀原始配置权重也必须精确反映 4/5 与
    1/5，不能把归并后的代表类误当成同权真实使用率。
    """
    factory = _FakeEffectFactory(supported_abilities=frozenset({"multiscale", "pressure"}))
    generator = _generator(factory)
    result = GenerateConfigurationSpaceUseCase(generator, generator).execute(
        GenerateConfigurationSpaceCommand(
            attacker=_single_command(
                move_ids=(245,),
                ability="multiscale",
                stat_command=StatSpaceCommand(
                    mode=StatEnumerationMode.CONTROLLED,
                    preset_keys=(),
                    relevant_fields=(StatField.HP,),
                    ev_values=(0, 1, 2, 3, 4),
                    nature_modifiers=(NatureModifier.neutral(),),
                ),
            ),
            defender=_single_command(move_ids=(420,), ability="pressure"),
        ),
        attacker_profile=_dragonite_profile(),
        defender_profile=_weavile_profile(),
    )

    assert result.statistics.attacker_raw_configuration_count == 5
    assert result.statistics.attacker_unique_configuration_count == 2
    assert result.statistics.raw_configuration_count == 5
    assert result.statistics.unique_configuration_count == 2
    assert sorted(value.member_count for value in result.equivalence_classes) == [1, 4]
    assert sorted(value.weight.value for value in result.equivalence_classes) == [
        Fraction(1, 5),
        Fraction(4, 5),
    ]


def test_controlled_ev_enumeration_enforces_per_stat_and_total_limits() -> None:
    """
    受控完整枚举只允许 command 指定的离散值，并且必须同时遵守单项 EV 不超过 252、六项总和不超过 510 的游戏约束；当 HP、攻击、物防分别选择 0 或
    252 时，唯一非法组合是三项同时 252，总共八个笛卡尔积候选应只留下七个原始配置。每个 representative 保留的 StatProfile
    也必须再次满足相同约束，避免 preset 或后续 provider 绕过合法性校验。
    """
    factory = _FakeEffectFactory(supported_abilities=frozenset({"multiscale", "pressure"}))
    generator = _generator(factory)
    result = GenerateConfigurationSpaceUseCase(generator, generator).execute(
        GenerateConfigurationSpaceCommand(
            attacker=_single_command(
                move_ids=(245,),
                ability="multiscale",
                stat_command=StatSpaceCommand(
                    mode=StatEnumerationMode.CONTROLLED,
                    preset_keys=(),
                    relevant_fields=(StatField.HP, StatField.ATTACK, StatField.DEFENSE),
                    ev_values=(0, 252),
                    nature_modifiers=(NatureModifier.neutral(),),
                ),
            ),
            defender=_single_command(move_ids=(420,), ability="pressure"),
        ),
        attacker_profile=_dragonite_profile(),
        defender_profile=_weavile_profile(),
    )

    assert result.statistics.attacker_raw_configuration_count == 7
    for configuration in result.configurations:
        evs = configuration.attacker.stat_profile.evs
        values = (
            evs.hp,
            evs.attack,
            evs.defense,
            evs.special_attack,
            evs.special_defense,
            evs.speed,
        )
        assert all(0 <= value <= 252 for value in values)
        assert sum(values) <= 510


