"""验证候选技能池按无序集合生成规范化技能组。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from pokeop.application.configuration_space import (
    AbilitySpaceCommand,
    GenerateConfigurationSpaceCommand,
    GenerateConfigurationSpaceUseCase,
    ItemSpaceCommand,
    MoveSpaceCommand,
    PokemonSpaceCommand,
    StatSpaceCommand,
)
from pokeop.domain.models.types import Type
from tests.application.configuration_space.helpers import (
    _FakeEffectFactory,
    _dragonite_profile,
    _generator,
    _move,
    _single_command,
    _weavile_profile,
)


def _candidate_profile(candidate_count: int):
    """创建包含指定数量可执行普通招式的配置读取模型。

    Args:
        candidate_count: 需要放入 profile 的候选招式数量。

    Returns:
        保留快龙固定能力和属性、只替换招式候选的 application projection。
    """
    return replace(
        _dragonite_profile(),
        moves=tuple(
            _move(
                1_000 + index,
                f"move-{index}",
                Type.NORMAL,
                40 + index,
            )
            for index in range(1, candidate_count + 1)
        ),
    )


def _canonical_space_command(move_ids: tuple[int, ...]) -> PokemonSpaceCommand:
    """创建使用产品规范技能组模式的单边配置空间命令。

    Args:
        move_ids: 允许参与规范组合的候选 move_id 集合。

    Returns:
        能力、能力值和道具均固定，技能组采用默认规范模式的命令。
    """
    return PokemonSpaceCommand(
        moves=MoveSpaceCommand(candidate_move_ids=move_ids),
        stats=StatSpaceCommand(preset_keys=("max_atk_plus",)),
        abilities=AbilitySpaceCommand(("inner-focus",)),
        items=ItemSpaceCommand((None,)),
    )


@pytest.mark.parametrize(
    ("candidate_count", "expected_group_count"),
    ((1, 1), (3, 1), (4, 1), (10, 210)),
)
def test_default_candidate_pool_generates_only_canonical_unordered_groups(
    candidate_count: int,
    expected_group_count: int,
) -> None:
    """验证少于四招取全量、达到四招后只生成 C(n, 4) 个无序技能组。"""
    profile = _candidate_profile(candidate_count)
    move_ids = tuple(move.move_id for move in profile.moves)
    factory = _FakeEffectFactory(
        supported_abilities=frozenset({"inner_focus", "pressure"})
    )
    generator = _generator(factory)

    result = GenerateConfigurationSpaceUseCase(generator, generator).execute(
        GenerateConfigurationSpaceCommand(
            attacker=_canonical_space_command(tuple(reversed(move_ids))),
            defender=_single_command(
                move_ids=(420,),
                ability="pressure",
            ),
        ),
        attacker_profile=profile,
        defender_profile=_weavile_profile(),
    )

    expected_slot_count = min(candidate_count, 4)
    assert result.statistics.attacker_raw_configuration_count == expected_group_count
    assert result.statistics.attacker_unique_configuration_count == expected_group_count
    assert len(result.configurations) == expected_group_count
    assert all(
        len(configuration.attacker.moves) == expected_slot_count
        for configuration in result.configurations
    )
    assert all(
        tuple(
            move.move_spec.move_id
            for move in configuration.attacker.moves
        )
        == tuple(
            sorted(
                move.move_spec.move_id
                for move in configuration.attacker.moves
            )
        )
        for configuration in result.configurations
    )


def test_direct_configuration_normalizes_move_permutations() -> None:
    """验证直接构造配置时，不同招式排列也共享同一行为签名与哈希。"""
    profile = _candidate_profile(4)
    factory = _FakeEffectFactory(
        supported_abilities=frozenset({"inner_focus", "pressure"})
    )
    generator = _generator(factory)

    result = GenerateConfigurationSpaceUseCase(generator, generator).execute(
        GenerateConfigurationSpaceCommand(
            attacker=_canonical_space_command(
                tuple(move.move_id for move in profile.moves)
            ),
            defender=_single_command(move_ids=(420,), ability="pressure"),
        ),
        attacker_profile=profile,
        defender_profile=_weavile_profile(),
    )
    original = result.configurations[0].attacker
    permuted = replace(original, moves=tuple(reversed(original.moves)))

    assert permuted.moves == original.moves
    assert permuted.behavior_signature == original.behavior_signature
    assert hash(permuted) == hash(original)
