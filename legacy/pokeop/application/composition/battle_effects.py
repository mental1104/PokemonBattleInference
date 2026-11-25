from __future__ import annotations

from pokeop.domain.battle.effects import (
    BattleEffectAbstractFactory,
    PokemonChampionEffectFactory,
)


class UnsupportedBattleEffectRulesetError(ValueError):
    """表示 application composition 尚未注册指定规则集的 effect 工厂。"""


def create_battle_effect_factory(ruleset_id: str) -> BattleEffectAbstractFactory:
    """按 ruleset 选择并创建 domain battle effect 抽象工厂实现。

    Args:
        ruleset_id: application 已从请求或读取模型获得的规则集标识。

    Returns:
        负责创建该规则集 effect 产品族的抽象工厂实现。

    Raises:
        UnsupportedBattleEffectRulesetError: 当前 composition root 不认识该规则集。
    """
    normalized = ruleset_id.strip().lower().replace("_", "-")
    if normalized == PokemonChampionEffectFactory.RULESET_ID:
        return PokemonChampionEffectFactory()
    raise UnsupportedBattleEffectRulesetError(
        f"unsupported battle effect ruleset: {ruleset_id}"
    )


__all__ = [
    "UnsupportedBattleEffectRulesetError",
    "create_battle_effect_factory",
]
