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


def test_explicit_raw_pair_limit_stops_configuration_explosion() -> None:
    """
    配置空间必须由 command 的显式上限约束，而不是依赖隐藏全局变量或让笛卡尔积无限扩张。双方各追加两个 fake 维度值后会形成四个原始配置对；当
    max_raw_configuration_pairs 设置为三时，用例应在进入最终配置对物化前抛出
    ConfigurationSpaceError。该失败属于可预测的运行保护，不能静默截断、丢失配置后仍声称覆盖完整，也不能把上限写死在 provider 内。
    """
    factory = _FakeEffectFactory(supported_abilities=frozenset({"multiscale", "pressure"}))
    generator = _generator(factory, extra_providers=(_FakeDimensionProvider(),))

    with pytest.raises(ConfigurationSpaceError, match="max_raw_configuration_pairs"):
        GenerateConfigurationSpaceUseCase(generator, generator).execute(
            GenerateConfigurationSpaceCommand(
                attacker=_single_command(move_ids=(245,), ability="multiscale"),
                defender=_single_command(move_ids=(420,), ability="pressure"),
                max_raw_configuration_pairs=3,
            ),
            attacker_profile=_dragonite_profile(),
            defender_profile=_weavile_profile(),
        )


def test_mismatched_version_group_profiles_are_rejected_before_enumeration() -> None:
    """
    version-aware 配置空间不能把两个不同版本组的 projection 组合成同一场战斗，即使
    它们碰巧具有相同属性、能力和招式字段也不行。测试把玛纽拉 fixture 的
    version_group_id 从 31 改为 30，期望顶层 use case 在调用任何维度 provider 前抛出
    稳定错误。这样可以防止历史招式、属性或机制规则被跨版本拼接，也保证配置缓存键与
    repository 的规则主轴保持一致。
    """
    factory = _FakeEffectFactory(
        supported_abilities=frozenset({"multiscale", "pressure"})
    )
    generator = _generator(factory)

    with pytest.raises(ConfigurationSpaceError, match="version_group_id"):
        GenerateConfigurationSpaceUseCase(generator, generator).execute(
            GenerateConfigurationSpaceCommand(
                attacker=_single_command(move_ids=(245,), ability="multiscale"),
                defender=_single_command(move_ids=(420,), ability="pressure"),
            ),
            attacker_profile=_dragonite_profile(),
            defender_profile=replace(_weavile_profile(), version_group_id=30),
        )


def test_move_combination_limit_stops_large_slot_enumeration_early() -> None:
    """
    招式组合也必须拥有独立的显式运行保护，因为单边总配置上限只有在各维度展开完成后
    才能计算。三个可用招式选择两个会形成三个合法组合；当 MoveSpaceCommand 的
    max_raw_combinations 设为二时，provider 应在第三个组合产生时立即失败，而不是先
    物化完整列表再由总上限兜底。失败不得返回静默截断的两组招式或错误的覆盖权重。
    """
    profile = PokemonConfigurationProfile(
        ruleset_id="pokemon-champion",
        version_group_id=31,
        pokemon_id=999,
        name="move-limit-tester",
        types=(Type.NORMAL,),
        base_stats=StatValues(100, 100, 100, 100, 100, 100),
        moves=(
            _move(1, "move-a", Type.NORMAL, 40),
            _move(2, "move-b", Type.NORMAL, 50),
            _move(3, "move-c", Type.NORMAL, 60),
        ),
        abilities=(AbilityConfigurationCandidate("pressure"),),
    )
    factory = _FakeEffectFactory(supported_abilities=frozenset({"pressure"}))
    generator = _generator(factory)

    with pytest.raises(ConfigurationSpaceError, match="max_raw_combinations"):
        GenerateConfigurationSpaceUseCase(generator, generator).execute(
            GenerateConfigurationSpaceCommand(
                attacker=PokemonSpaceCommand(
                    moves=MoveSpaceCommand(
                        slot_counts=(2,),
                        max_raw_combinations=2,
                    ),
                    stats=StatSpaceCommand(preset_keys=("max_atk_plus",)),
                    abilities=AbilitySpaceCommand(("pressure",)),
                    items=ItemSpaceCommand((None,)),
                ),
                defender=_single_command(move_ids=(420,), ability="pressure"),
            ),
            attacker_profile=profile,
            defender_profile=_weavile_profile(),
        )
