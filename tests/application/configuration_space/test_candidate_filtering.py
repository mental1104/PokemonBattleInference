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


def test_move_combinations_have_unique_slots_and_filter_unsupported_status_move() -> None:
    """
    招式 provider 应从 profile 的合法候选中先执行 repository/factory
    覆盖校验，再生成不重复槽位的组合。三个无额外机制的物理攻击招式选择两招时应产生三种组合；一个没有显式 effect 实现的变化招式即使 repository 声明
    supported，也不能被当作安全 no-op 混入配置。覆盖报告必须把它标记为 unsupported 并说明过滤，而每个代表配置中的 move_id
    必须唯一且保持稳定升序。
    """
    profile = PokemonConfigurationProfile(
        ruleset_id="pokemon-champion",
        version_group_id=31,
        pokemon_id=999,
        name="synthetic-move-tester",
        types=(Type.NORMAL,),
        base_stats=StatValues(100, 100, 100, 100, 100, 100),
        moves=(
            _move(1, "move-a", Type.NORMAL, 40),
            _move(2, "move-b", Type.NORMAL, 50),
            _move(3, "move-c", Type.NORMAL, 60),
            _move(4, "status-noop", Type.NORMAL, 0, category=MoveCategory.STATUS),
        ),
        abilities=(AbilityConfigurationCandidate("pressure"),),
    )
    defender = _weavile_profile()
    factory = _FakeEffectFactory(supported_abilities=frozenset({"pressure"}))
    generator = _generator(factory)
    result = GenerateConfigurationSpaceUseCase(generator, generator).execute(
        GenerateConfigurationSpaceCommand(
            attacker=PokemonSpaceCommand(
                moves=MoveSpaceCommand(slot_counts=(2,)),
                stats=StatSpaceCommand(preset_keys=("max_atk_plus",)),
                abilities=AbilitySpaceCommand(("pressure",)),
                items=ItemSpaceCommand((None,)),
            ),
            defender=_single_command(move_ids=(420,), ability="pressure"),
        ),
        attacker_profile=profile,
        defender_profile=defender,
    )

    assert result.statistics.attacker_raw_configuration_count == 3
    assert result.statistics.attacker_unique_configuration_count == 3
    for configuration in result.configurations:
        move_ids = tuple(move.move_spec.move_id for move in configuration.attacker.moves)
        assert move_ids == tuple(sorted(move_ids))
        assert len(move_ids) == len(set(move_ids)) == 2
        assert 4 not in move_ids
    assert any(
        record.identifier == "4"
        and record.support_status is MechanismSupportStatus.UNSUPPORTED
        and not record.included
        for record in result.coverage_records
    )
    assert result.statistics.unsupported_mechanism_count == 1


def test_unsupported_ability_and_item_candidates_are_never_silent_noops() -> None:
    """合法候选仍必须经过当前规则集 factory 的显式能力校验。玛纽拉 profile 同时提供
    pressure 与 pickpocket，测试 factory 只实现 pressure；command 还额外要求无道具和
    一个未知 mystery-item。结果应只保留 pressure 与 none，不得把未实现特性或道具映射
    成 no-op 后参与配置。两项被过滤机制必须分别出现在 coverage records 和 unsupported
    统计中，使后续胜率结果能够明确说明能力边界，而不是把缺失实现伪装成完整覆盖。
    """
    profile = _weavile_profile()
    factory = _FakeEffectFactory(supported_abilities=frozenset({"pressure"}))
    generator = _generator(factory)
    result = GenerateConfigurationSpaceUseCase(generator, generator).execute(
        GenerateConfigurationSpaceCommand(
            attacker=PokemonSpaceCommand(
                moves=MoveSpaceCommand((420,), (1,)),
                stats=StatSpaceCommand(preset_keys=("max_atk_plus",)),
                abilities=AbilitySpaceCommand(),
                items=ItemSpaceCommand((None, "mystery-item")),
            ),
            defender=_single_command(move_ids=(420,), ability="pressure"),
        ),
        attacker_profile=profile,
        defender_profile=profile,
    )

    assert {
        configuration.attacker.ability_identifier
        for configuration in result.configurations
    } == {"pressure"}
    assert {
        configuration.attacker.item_identifier
        for configuration in result.configurations
    } == {"none"}
    assert {
        (record.dimension_key, record.identifier)
        for record in result.coverage_records
        if record.side == "attacker"
        and record.support_status is MechanismSupportStatus.UNSUPPORTED
    } == {("ability", "pickpocket"), ("item", "mystery_item")}
    assert result.statistics.unsupported_mechanism_count == 2


