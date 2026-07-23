from __future__ import annotations

import pytest

from pokeop.application.composition.battle_effects import (
    UnsupportedBattleEffectRulesetError,
    create_battle_effect_factory,
)
from pokeop.domain.battle.effects import PokemonChampionEffectFactory


def test_composition_selects_pokemon_champion_factory() -> None:
    """application composition 应把规则集标识解析成对应具体抽象工厂。"""
    factory = create_battle_effect_factory("pokemon_champion")

    assert isinstance(factory, PokemonChampionEffectFactory)
    assert factory.ruleset_id == "pokemon-champion"


def test_composition_rejects_unregistered_ruleset() -> None:
    """未注册规则集应显式失败，不能偷偷退回默认工厂。"""
    with pytest.raises(
        UnsupportedBattleEffectRulesetError,
        match="unsupported battle effect ruleset",
    ):
        create_battle_effect_factory("future-ruleset")
