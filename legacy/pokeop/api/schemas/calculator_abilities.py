from __future__ import annotations

from pydantic import BaseModel, Field

from pokeop.api.schemas.calculator import CalculatorPokemonInput
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculatorAbilityOption,
)
from pokeop.domain.battle.state import StatStages


class BattleAbilityOptionResponse(BaseModel):
    """一只 Pokémon 在当前规则集下可选择的特性。"""

    ability_id: int = Field(description="PokeAPI ability ID。")
    identifier: str = Field(description="PokeAPI 稳定 identifier。")
    display_name: str = Field(description="当前语言展示名称。")
    slot: int = Field(description="PokeAPI 特性槽位。")
    is_hidden: bool = Field(description="是否为隐藏特性。")
    implemented: bool = Field(description="当前 domain 是否已实现对应 effect。")


class BattleStatStagesInput(BaseModel):
    """一侧 Pokémon 在本次计算开始时的七项战斗能力等级。"""

    attack: int = Field(default=0, ge=-6, le=6, strict=True, description="攻击能力等级。")
    defense: int = Field(default=0, ge=-6, le=6, strict=True, description="防御能力等级。")
    special_attack: int = Field(
        default=0,
        ge=-6,
        le=6,
        strict=True,
        description="特攻能力等级。",
    )
    special_defense: int = Field(
        default=0,
        ge=-6,
        le=6,
        strict=True,
        description="特防能力等级。",
    )
    speed: int = Field(default=0, ge=-6, le=6, strict=True, description="速度能力等级。")
    accuracy: int = Field(default=0, ge=-6, le=6, strict=True, description="命中能力等级。")
    evasion: int = Field(default=0, ge=-6, le=6, strict=True, description="回避能力等级。")

    def to_domain(self) -> StatStages:
        """转换为 application 与 domain 共享的不可变能力等级值对象。

        Returns:
            已由 Pydantic 校验全部字段位于 -6 到 +6 的 ``StatStages``。
        """
        return StatStages(
            attack=self.attack,
            defense=self.defense,
            special_attack=self.special_attack,
            special_defense=self.special_defense,
            speed=self.speed,
            accuracy=self.accuracy,
            evasion=self.evasion,
        )


class CalculatorPokemonWithAbilityInput(CalculatorPokemonInput):
    """计算请求中一侧 Pokémon 的必选特性、能力等级和其他用户选择。"""

    ability_identifier: str = Field(
        min_length=1,
        description="必须属于该 Pokémon 当前规则集特性列表的 identifier。",
    )
    stat_stages: BattleStatStagesInput = Field(
        default_factory=BattleStatStagesInput,
        description="当前战斗中的七项能力等级；省略时全部按 0 处理。",
    )


class CalculateDamageWithAbilitiesRequest(BaseModel):
    """执行支持双方特性和能力等级选择的基础伤害计算请求。"""

    ruleset_id: str = Field(default="pokemon-champion", description="当前规则集标识。")
    attacker: CalculatorPokemonWithAbilityInput = Field(description="攻击方选择。")
    defender: CalculatorPokemonWithAbilityInput = Field(description="防守方选择。")
    move_id: int = Field(description="本次使用的招式 ID。")


def ability_option_from_result(
    result: CalculatorAbilityOption,
) -> BattleAbilityOptionResponse:
    """把 application 特性选项转换成 HTTP schema。

    Args:
        result: application 层返回的特性候选及其实现状态。

    Returns:
        可由 FastAPI 序列化的特性响应模型。
    """
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
    "BattleStatStagesInput",
    "CalculateDamageWithAbilitiesRequest",
    "CalculatorPokemonWithAbilityInput",
    "ability_option_from_result",
]
