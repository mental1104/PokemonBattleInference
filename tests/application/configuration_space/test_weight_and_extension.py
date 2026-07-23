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


def test_stat_profile_limit_stops_controlled_enumeration_before_materialization() -> None:
    """受控 EV 枚举必须在生成过程中逐项执行 max_raw_profiles，而不是先把完整笛卡尔积
    放进内存后再检查。HP EV 取 0、1、2、3、4 会产生五个合法原始 profile；上限设为四
    时应在第五项被消费时抛出稳定错误。该保护既验证 command 能控制规模，也防止未来把
    六项更多离散值误配置成指数级列表后才发现超限；失败不能返回截断结果或错误权重。
    """
    factory = _FakeEffectFactory(
        supported_abilities=frozenset({"multiscale", "pressure"})
    )
    generator = _generator(factory)
    limited_stats = StatSpaceCommand(
        mode=StatEnumerationMode.CONTROLLED,
        preset_keys=(),
        relevant_fields=(StatField.HP,),
        ev_values=(0, 1, 2, 3, 4),
        nature_modifiers=(NatureModifier.neutral(),),
        max_raw_profiles=4,
    )

    with pytest.raises(ConfigurationSpaceError, match="max_raw_profiles"):
        GenerateConfigurationSpaceUseCase(generator, generator).execute(
            GenerateConfigurationSpaceCommand(
                attacker=_single_command(
                    move_ids=(245,),
                    ability="multiscale",
                    stat_command=limited_stats,
                ),
                defender=_single_command(move_ids=(420,), ability="pressure"),
            ),
            attacker_profile=_dragonite_profile(),
            defender_profile=_weavile_profile(),
        )


def test_uniform_equivalence_class_weight_does_not_reuse_raw_member_ratio() -> None:
    """
    权重模式必须由 command 显式决定。沿用 HP EV 0～4 产生的两个最终能力等价类时，原始成员数量仍然是四和一，但选择
    uniform_equivalence_class 后两个代表类都应获得精确的 1/2 覆盖权重；该结果只表达分析者对唯一行为类的均匀覆盖，不得因为成员数量不同又偷偷退回
    4/5 与 1/5，也不得被命名为真实使用率或实战胜率。
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
            weight_assumption=ConfigurationWeightAssumption.UNIFORM_EQUIVALENCE_CLASS,
        ),
        attacker_profile=_dragonite_profile(),
        defender_profile=_weavile_profile(),
    )

    assert sorted(value.member_count for value in result.equivalence_classes) == [1, 4]
    assert {value.weight.value for value in result.equivalence_classes} == {Fraction(1, 2)}
    assert result.total_weight == Fraction(1)


@dataclass(frozen=True, slots=True)
class _FakeDimensionProvider:
    """模拟未来新增、主循环和标准四维均未知的规则维度。"""

    @property
    def dimension_key(self) -> str:
        """返回测试扩展维度稳定键。"""
        return "fake-rule"

    def expand(self, context: ConfigurationGenerationContext) -> DimensionExpansion:
        """为每一方返回两个行为不同的扩展值，证明无需修改组合主循环。"""
        return DimensionExpansion(
            values=(
                OpaqueDimensionValue("fake-rule", "alpha", "alpha"),
                OpaqueDimensionValue("fake-rule", "beta", "beta"),
            )
        )


def test_new_dimension_provider_extends_space_without_changing_standard_generators() -> None:
    """
    扩展性验收要求新增一个 fake 配置维度时不修改招式、能力、特性、道具 provider 和主组合循环。本测试只把自定义 provider 追加到 generator
    构造参数，双方其他维度都固定为单一值；每方应自然得到 alpha、beta 两个行为签名，最终形成四个配置对。代表配置必须保存 extra_dimensions
    和解释标签，证明未来天气预设、规则开关或策略维度可以沿相同协议扩展。
    """
    factory = _FakeEffectFactory(supported_abilities=frozenset({"multiscale", "pressure"}))
    generator = _generator(factory, extra_providers=(_FakeDimensionProvider(),))
    result = GenerateConfigurationSpaceUseCase(generator, generator).execute(
        GenerateConfigurationSpaceCommand(
            attacker=_single_command(move_ids=(245,), ability="multiscale"),
            defender=_single_command(move_ids=(420,), ability="pressure"),
        ),
        attacker_profile=_dragonite_profile(),
        defender_profile=_weavile_profile(),
    )

    assert result.statistics.attacker_unique_configuration_count == 2
    assert result.statistics.defender_unique_configuration_count == 2
    assert result.statistics.unique_configuration_count == 4
    assert {
        configuration.attacker.extra_dimensions[0][1]
        for configuration in result.configurations
    } == {"alpha", "beta"}
    assert all(
        ("fake-rule", "alpha") in configuration.attacker.dimension_labels
        or ("fake-rule", "beta") in configuration.attacker.dimension_labels
        for configuration in result.configurations
    )
