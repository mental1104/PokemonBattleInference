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


def test_fixed_dragonite_weavile_fixture_generates_one_explainable_pair() -> None:
    """
    固定 preset 模式应把快龙与玛纽拉的候选池收敛为一个可解释配置对：双方只使用 command 指定的两招、一个合法特性和一个受控道具，快龙的 partial
    羽栖仍保留在覆盖报告中但不得进入配置，结果需要保留 version-aware profile 的身份、最终能力、招式优先级、特性和道具标识，并以精确权重 1
    表示完整覆盖而非真实天梯使用率。
    """
    factory = _FakeEffectFactory(
        supported_move_effects=frozenset({"break_screens", "fake_out"}),
        supported_abilities=frozenset(
            {"inner_focus", "multiscale", "pressure", "pickpocket"}
        ),
    )
    generator = _generator(factory)
    use_case = GenerateConfigurationSpaceUseCase(generator, generator)
    result = use_case.execute(
        GenerateConfigurationSpaceCommand(
            attacker=_single_command(
                move_ids=(245, 280),
                ability="multiscale",
                item=None,
            ),
            defender=_single_command(
                move_ids=(252, 420),
                ability="pressure",
                item="choice-band",
            ),
        ),
        attacker_profile=_dragonite_profile(),
        defender_profile=_weavile_profile(),
    )

    assert result.statistics.raw_configuration_count == 1
    assert result.statistics.unique_configuration_count == 1
    assert result.total_weight == Fraction(1)
    representative = result.configurations[0]
    assert representative.attacker.ruleset_id == "pokemon-champion"
    assert representative.attacker.version_group_id == 31
    assert representative.attacker.name == "dragonite"
    assert representative.attacker.ability_identifier == "multiscale"
    assert representative.attacker.item_identifier == "none"
    assert tuple(move.move_spec.move_id for move in representative.attacker.moves) == (245, 280)
    assert representative.defender.name == "weavile"
    assert representative.defender.ability_identifier == "pressure"
    assert representative.defender.item_identifier == "choice_band"
    assert any(
        record.identifier == "355"
        and record.support_status is MechanismSupportStatus.PARTIAL
        and not record.included
        for record in result.coverage_records
    )
    assert result.statistics.partial_mechanism_count == 1
    assert hash(representative) == hash(representative)
    assert {representative} == {representative}


