from __future__ import annotations

from pydantic import BaseModel, Field

from pokeop.application.use_cases.calculate_catalog_damage import (
    CalculateCatalogDamageResult,
    CalculatorMoveSearchResult,
    CalculatorPokemonProfile,
    CalculatorPokemonSearchResult,
)
from pokeop.domain.battle.modifiers import AppliedModifier
from pokeop.domain.battle.stats import StatValues


class PokemonSearchItem(BaseModel):
    """搜索接口返回的一只轻量宝可梦。"""

    pokemon_id: int = Field(description="PokeAPI pokemon_id。")
    identifier: str = Field(description="英文稳定标识。")
    display_name: str = Field(description="中文展示名；缺失时回退 identifier。")
    form_identifier: str | None = Field(default=None, description="默认形态标识。")
    types: list[str] = Field(description="英文属性标识列表。")
    type_names: list[str] = Field(description="中文属性名列表。")


class PokemonDetailResponse(PokemonSearchItem):
    """详情接口返回的宝可梦摘要和基础能力。"""

    base_stats: dict[str, int] = Field(description="六项种族值，供页面摘要展示。")


class MoveSearchItem(BaseModel):
    """招式选择器返回的一条可计算招式。"""

    move_id: int = Field(description="PokeAPI move_id。")
    identifier: str = Field(description="英文稳定标识。")
    display_name: str = Field(description="中文展示名；缺失时回退 identifier。")
    type: str = Field(description="英文属性标识。")
    type_name: str = Field(description="中文属性名。")
    category: str = Field(description="physical 或 special。")
    power: int = Field(description="固定正威力。")


class StatPresetResponse(BaseModel):
    """前端展示的配置模板说明。"""

    key: str = Field(description="提交计算请求时使用的稳定 key。")
    label: str = Field(description="面向用户的短标签。")
    assumption: str = Field(description="该模板展开后的等级、EV 与性格假设。")


class CalculatorPokemonInput(BaseModel):
    """计算请求中一侧宝可梦的用户选择。"""

    pokemon_id: int = Field(description="服务端可信查询用的 pokemon_id。")
    level: int = Field(default=50, ge=1, le=100, description="本次计算等级。")
    stat_preset: str = Field(description="application 层声明的配置模板 key。")


class CalculateDamageRequest(BaseModel):
    """执行基础伤害计算的 HTTP 请求。"""

    ruleset_id: str = Field(default="pokemon-champion", description="当前规则集标识。")
    attacker: CalculatorPokemonInput = Field(description="攻击方选择。")
    defender: CalculatorPokemonInput = Field(description="防守方选择。")
    move_id: int = Field(description="本次使用的招式 ID。")


class ResultPokemon(BaseModel):
    """伤害结果中一侧宝可梦的展示字段。"""

    pokemon_id: int
    identifier: str
    display_name: str
    level: int
    preset_label: str
    preset_assumption: str
    stats: dict[str, int]
    effective_attack: int | None = None
    effective_hp: int | None = None
    effective_defense: int | None = None


class ResultMove(BaseModel):
    """伤害结果中的招式展示字段。"""

    move_id: int
    identifier: str
    display_name: str
    type: str
    type_name: str
    category: str
    power: int


class DamageRange(BaseModel):
    """伤害结果中的伤害区间和 16 档明细。"""

    min: int
    max: int
    min_percent: float
    max_percent: float
    expected: float
    expected_percent: float
    rolls: list[int]


class KOResult(BaseModel):
    """伤害结果中的 KO 概率。"""

    ohko_probability: float
    two_hit_ko_probability: float
    guaranteed_ohko: bool
    guaranteed_2hko: bool


class ModifierTraceItem(BaseModel):
    """本次计算中生效的一个 modifier trace 条目。"""

    key: str
    multiplier: float | None = None
    min_multiplier: float | None = None
    max_multiplier: float | None = None
    stage: str | None = None
    source: str | None = None
    reason: str


class CalculationScopeResponse(BaseModel):
    """基础模式纳入与排除的机制说明。"""

    mode: str
    included: list[str]
    excluded: list[str]


class CalculateDamageResponse(BaseModel):
    """基础伤害计算 HTTP 响应。"""

    ruleset_id: str
    ruleset_name: str
    attacker: ResultPokemon
    defender: ResultPokemon
    move: ResultMove
    damage: DamageRange
    ko: KOResult
    modifiers: list[ModifierTraceItem]
    scope: CalculationScopeResponse
    warnings: list[str]


def _stats_to_dict(stats: StatValues) -> dict[str, int]:
    """把 domain StatValues 转成 JSON 友好的普通字典。"""
    return {
        "hp": stats.hp,
        "attack": stats.attack,
        "defense": stats.defense,
        "special_attack": stats.special_attack,
        "special_defense": stats.special_defense,
        "speed": stats.speed,
    }


def pokemon_search_item_from_result(result: CalculatorPokemonSearchResult) -> PokemonSearchItem:
    """把 application 宝可梦搜索结果转换成 HTTP schema。"""
    return PokemonSearchItem(
        pokemon_id=result.pokemon_id,
        identifier=result.identifier,
        display_name=result.display_name,
        form_identifier=result.form_identifier,
        types=list(result.types),
        type_names=list(result.type_names),
    )


def pokemon_detail_from_profile(profile: CalculatorPokemonProfile) -> PokemonDetailResponse:
    """把 application 宝可梦详情读取模型转换成 HTTP schema。"""
    return PokemonDetailResponse(
        pokemon_id=profile.pokemon_id,
        identifier=profile.identifier,
        display_name=profile.display_name,
        form_identifier=profile.form_identifier,
        types=[type_value.name.lower() for type_value in profile.types],
        type_names=list(profile.type_names),
        base_stats=_stats_to_dict(profile.base_stats),
    )


def move_search_item_from_result(result: CalculatorMoveSearchResult) -> MoveSearchItem:
    """把 application 招式搜索结果转换成 HTTP schema。"""
    return MoveSearchItem(
        move_id=result.move_id,
        identifier=result.identifier,
        display_name=result.display_name,
        type=result.type,
        type_name=result.type_name,
        category=result.category.value,
        power=result.power,
    )


def modifier_from_domain(modifier: AppliedModifier) -> ModifierTraceItem:
    """把 domain modifier trace 转成 HTTP schema。"""
    return ModifierTraceItem(
        key=str(getattr(modifier.key, "value", modifier.key)),
        multiplier=modifier.multiplier,
        min_multiplier=modifier.min_multiplier,
        max_multiplier=modifier.max_multiplier,
        stage=modifier.stage.value if modifier.stage is not None else None,
        source=str(getattr(modifier.source, "value", modifier.source)) if modifier.source else None,
        reason=modifier.reason,
    )


def damage_response_from_result(result: CalculateCatalogDamageResult) -> CalculateDamageResponse:
    """把 application 计算结果转换成 HTTP 响应。"""
    return CalculateDamageResponse(
        ruleset_id=result.ruleset.ruleset_id,
        ruleset_name=result.ruleset.ruleset_name,
        attacker=ResultPokemon(
            pokemon_id=result.attacker.pokemon_id,
            identifier=result.attacker.identifier,
            display_name=result.attacker.display_name,
            level=result.attacker.level,
            preset_label=result.attacker.preset.label,
            preset_assumption=result.attacker.preset.assumption,
            stats=_stats_to_dict(result.attacker.stats),
            effective_attack=result.attacker.effective_attack,
        ),
        defender=ResultPokemon(
            pokemon_id=result.defender.pokemon_id,
            identifier=result.defender.identifier,
            display_name=result.defender.display_name,
            level=result.defender.level,
            preset_label=result.defender.preset.label,
            preset_assumption=result.defender.preset.assumption,
            stats=_stats_to_dict(result.defender.stats),
            effective_hp=result.defender.effective_hp,
            effective_defense=result.defender.effective_defense,
        ),
        move=ResultMove(
            move_id=result.move.move_id,
            identifier=result.move.identifier,
            display_name=result.move.display_name,
            type=result.move.type,
            type_name=result.move.type_name,
            category=result.move.category.value,
            power=result.move.power,
        ),
        damage=DamageRange(
            min=result.damage.min_damage,
            max=result.damage.max_damage,
            min_percent=result.damage.min_percent,
            max_percent=result.damage.max_percent,
            expected=result.damage.expected_damage,
            expected_percent=result.damage.expected_percent,
            rolls=list(result.damage.rolls),
        ),
        ko=KOResult(
            ohko_probability=result.ko_chance.ohko_chance,
            two_hit_ko_probability=result.ko_chance.two_hit_ko_chance,
            guaranteed_ohko=result.ko_chance.guaranteed_ohko,
            guaranteed_2hko=result.ko_chance.guaranteed_2hko,
        ),
        modifiers=[modifier_from_domain(item) for item in result.damage.applied_modifiers],
        scope=CalculationScopeResponse(
            mode=result.scope.mode,
            included=list(result.scope.included),
            excluded=list(result.scope.excluded),
        ),
        warnings=list(result.warnings),
    )


__all__ = [
    "CalculateDamageRequest",
    "CalculateDamageResponse",
    "MoveSearchItem",
    "PokemonDetailResponse",
    "PokemonSearchItem",
    "StatPresetResponse",
    "damage_response_from_result",
    "move_search_item_from_result",
    "pokemon_detail_from_profile",
    "pokemon_search_item_from_result",
]
