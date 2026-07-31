from __future__ import annotations

from pydantic import BaseModel, Field

from pokeop.api.schemas.calculator import CalculatorPokemonInput
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculatorAbilityOption,
)


class BattleAbilityOptionResponse(BaseModel):
    """一只 Pokémon 在当前规则集下可选择的特性。"""

    ability_id: int = Field(description="PokeAPI ability ID。")
    identifier: str = Field(description="PokeAPI 稳定 identifier。")
    display_name: str = Field(description="当前语言展示名称。")
    slot: int = Field(description="PokeAPI 特性槽位。")
    is_hidden: bool = Field(description="是否为隐藏特性。")
    implemented: bool = Field(description="当前 domain 是否已实现对应 effect。")


class CalculatorPokemonWithAbilityInput(CalculatorPokemonInput):
    """计算请求中一侧 Pokémon 的必选特性和其他用户选择。"""

    ability_identifier: str = Field(
        min_length=1,
        description="必须属于该 Pokémon 当前规则集特性列表的 identifier。",
    )


class CalculateDamageWithAbilitiesRequest(BaseModel):
    """执行支持双方特性选择的基础伤害计算请求。"""

    ruleset_id: str = Field(default="pokemon-champion", description="当前规则集标识。")
    attacker: CalculatorPokemonWithAbilityInput = Field(description="攻击方选择。")
    defender: CalculatorPokemonWithAbilityInput = Field(description="防守方选择。")
    move_id: int = Field(description="本次使用的招式 ID。")


def ability_option_from_result(
    result: CalculatorAbilityOption,
) -> BattleAbilityOptionResponse:
    """把 application 特性选项转换成 HTTP schema。"""
    return BattleAbilityOptionResponse(
        ability_id=result.ability_id,
        identifier=result.identifier,
        display_name=result.display_name,
        slot=result.slot,
        is_hidden=result.is_hidden,
        implemented=result.implemented,
    )


__all__ = [
    "BattleAbilityOptionResponse",
    "CalculateDamageWithAbilitiesRequest",
    "CalculatorPokemonWithAbilityInput",
    "ability_option_from_result",
]
