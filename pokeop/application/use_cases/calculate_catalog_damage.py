from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pokeop.application.presets.stat_profiles import StatProfilePreset
from pokeop.domain.battle.context import (
    BattleMove,
    BattlePokemon,
    DamageContextBuilder,
    MoveCategory,
)
from pokeop.domain.battle.damage import DamageRollResult, calculate_damage_rolls
from pokeop.domain.battle.ko import KOChanceResult, estimate_ko_chance
from pokeop.domain.battle.modifiers import defensive_stat, offensive_stat
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_version_group
from pokeop.domain.battle.stats import StatProfile, StatValues, calculate_actual_stats
from pokeop.domain.models.types import Type


DEFAULT_RULESET_ID = "pokemon-champion"
DEFAULT_LEVEL = 50


@dataclass(frozen=True)
class CalculatorRulesetContext:
    """application 层读取到的计算器规则集上下文。

    ruleset_id 是 HTTP 和前端保留的稳定规则集标识；generation_id 与
    version_group_id 用于把数据库选择结果转换为 domain 的 BattleRuleset。
    """

    ruleset_id: str
    ruleset_name: str
    generation_id: int
    version_group_id: int
    version_group_identifier: str


@dataclass(frozen=True)
class CalculatorPokemonProfile:
    """application 层使用的宝可梦战斗读取模型。

    该对象只包含计算和页面摘要需要的字段，不向 application 泄漏 SQLAlchemy row、
    raw table model 或物化视图字段细节。
    """

    pokemon_id: int
    identifier: str
    display_name: str
    form_identifier: str | None
    types: tuple[Type, ...]
    type_names: tuple[str, ...]
    base_stats: StatValues


@dataclass(frozen=True)
class CalculatorMoveProfile:
    """application 层使用的招式战斗读取模型。

    第一版只允许固定正威力的物理或特殊招式进入计算；repository 可以提前过滤，
    use case 仍会在执行计算前做最终防线校验。
    """

    move_id: int
    identifier: str
    display_name: str
    type: Type
    type_name: str
    category: MoveCategory
    power: int


@dataclass(frozen=True)
class CalculatorPokemonSearchResult:
    """页面搜索选择器需要的轻量宝可梦结果。"""

    pokemon_id: int
    identifier: str
    display_name: str
    form_identifier: str | None
    types: tuple[str, ...]
    type_names: tuple[str, ...]


@dataclass(frozen=True)
class CalculatorMoveSearchResult:
    """页面招式选择器需要的轻量招式结果。"""

    move_id: int
    identifier: str
    display_name: str
    type: str
    type_name: str
    category: MoveCategory
    power: int


class CalculatorCatalogRepository(Protocol):
    """calculator use case 依赖的持久化读取端口。

    实现类负责读取物化视图和处理数据库细节；application 只依赖这些明确的业务
    读取模型，便于测试用 fake repository 替换真实 PostgreSQL。
    """

    def get_ruleset_context(self, ruleset_id: str) -> CalculatorRulesetContext | None:
        """按 ruleset_id 读取规则集上下文；不存在时返回 None。"""

    def search_pokemon(
        self,
        *,
        ruleset_id: str,
        query: str,
        limit: int,
    ) -> tuple[CalculatorPokemonSearchResult, ...]:
        """按中文名或 identifier 搜索宝可梦，返回最多 limit 条轻量结果。"""

    def get_pokemon_profile(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
    ) -> CalculatorPokemonProfile | None:
        """读取一只宝可梦的基础战斗资料；不存在时返回 None。"""

    def list_calculable_moves(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        query: str,
        limit: int,
    ) -> tuple[CalculatorMoveSearchResult, ...]:
        """列出某宝可梦在规则集下可学且当前 domain 可直接计算的招式。"""

    def get_move_profile(
        self,
        *,
        ruleset_id: str,
        move_id: int,
    ) -> CalculatorMoveProfile | None:
        """读取一个招式的 version-aware 战斗资料；不存在时返回 None。"""

    def pokemon_can_use_move(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        move_id: int,
    ) -> bool:
        """校验招式是否属于该宝可梦在当前规则集下的可用招式。"""


@dataclass(frozen=True)
class StatPresetView:
    """返回给前端展示的配置模板说明。"""

    key: str
    label: str
    assumption: str


@dataclass(frozen=True)
class CalculateCatalogPokemonCommand:
    """一次 catalog 伤害计算中一侧宝可梦的输入。"""

    pokemon_id: int
    level: int
    stat_preset: str


@dataclass(frozen=True)
class CalculateCatalogDamageCommand:
    """数据库驱动 calculator damage use case 的输入命令。"""

    ruleset_id: str
    attacker: CalculateCatalogPokemonCommand
    defender: CalculateCatalogPokemonCommand
    move_id: int


@dataclass(frozen=True)
class CalculatorPokemonResult:
    """伤害结果中一侧宝可梦的展示字段。"""

    pokemon_id: int
    identifier: str
    display_name: str
    level: int
    preset: StatPresetView
    stats: StatValues
    effective_attack: int | None = None
    effective_defense: int | None = None
    effective_hp: int | None = None


@dataclass(frozen=True)
class CalculatorMoveResult:
    """伤害结果中的招式展示字段。"""

    move_id: int
    identifier: str
    display_name: str
    type: str
    type_name: str
    category: MoveCategory
    power: int


@dataclass(frozen=True)
class CalculationScope:
    """基础模式当前纳入和排除的机制范围。"""

    mode: str
    included: tuple[str, ...]
    excluded: tuple[str, ...]


@dataclass(frozen=True)
class CalculateCatalogDamageResult:
    """数据库驱动 calculator damage use case 的输出结果。"""

    ruleset: CalculatorRulesetContext
    attacker: CalculatorPokemonResult
    defender: CalculatorPokemonResult
    move: CalculatorMoveResult
    damage: DamageRollResult
    ko_chance: KOChanceResult
    scope: CalculationScope
    warnings: tuple[str, ...]


class CalculatorInputError(ValueError):
    """表示用户输入组合非法或当前基础模式不支持。"""


def _blank_stat_values() -> StatValues:
    """创建无投入 EV 模板，避免多个 preset 共享可变结构。"""
    return StatValues.zero()


NO_INVESTMENT = StatProfilePreset(
    key="no_investment",
    evs=_blank_stat_values(),
)


ATTACKER_PRESETS: dict[str, StatPresetView] = {
    "no_investment": StatPresetView("no_investment", "无投入", "50 级 · 0 EV · 中性性格"),
    "max_atk_neutral": StatPresetView("max_atk_neutral", "满攻", "50 级 · 252 Atk · 中性性格"),
    "max_atk_plus": StatPresetView("max_atk_plus", "极攻", "50 级 · 252 Atk · 攻击性格"),
    "max_spatk_neutral": StatPresetView("max_spatk_neutral", "满特攻", "50 级 · 252 SpA · 中性性格"),
    "max_spatk_plus": StatPresetView("max_spatk_plus", "极特攻", "50 级 · 252 SpA · 特攻性格"),
}

DEFENDER_PRESETS: dict[str, StatPresetView] = {
    "no_investment": StatPresetView("no_investment", "无投入", "50 级 · 0 EV · 中性性格"),
    "max_hp": StatPresetView("max_hp", "满 HP", "50 级 · 252 HP · 防御/特防无投入"),
    "max_hp_def": StatPresetView("max_hp_def", "物耐", "50 级 · 252 HP / 252 Def · 中性性格"),
    "max_hp_def_plus": StatPresetView("max_hp_def_plus", "极限物耐", "50 级 · 252 HP / 252 Def · 防御性格"),
    "max_hp_spdef": StatPresetView("max_hp_spdef", "特耐", "50 级 · 252 HP / 252 SpD · 中性性格"),
    "max_hp_spdef_plus": StatPresetView("max_hp_spdef_plus", "极限特耐", "50 级 · 252 HP / 252 SpD · 特防性格"),
}


def _preset_profile(preset_key: str, base_stats: StatValues) -> StatProfile:
    """把 UI preset key 展开为 domain 能力配置。

    Args:
        preset_key: HTTP 请求传入的模板标识，只允许 application 层声明的固定值。
        base_stats: 从数据库读取的宝可梦六项种族值。

    Returns:
        可交给 domain 能力值公式计算的 StatProfile。
    """
    from pokeop.domain.battle.stats import NatureModifier
    from pokeop.domain.models.pokemon_fields import StatField

    if preset_key == "no_investment":
        return NO_INVESTMENT.apply(base_stats)
    if preset_key == "max_atk_neutral":
        return StatProfilePreset(preset_key, StatValues(attack=252)).apply(base_stats)
    if preset_key == "max_atk_plus":
        return StatProfilePreset(
            preset_key,
            StatValues(attack=252),
            NatureModifier.increase(StatField.ATTACK),
        ).apply(base_stats)
    if preset_key == "max_spatk_neutral":
        return StatProfilePreset(preset_key, StatValues(special_attack=252)).apply(base_stats)
    if preset_key == "max_spatk_plus":
        return StatProfilePreset(
            preset_key,
            StatValues(special_attack=252),
            NatureModifier.increase(StatField.SPECIAL_ATTACK),
        ).apply(base_stats)
    if preset_key == "max_hp":
        return StatProfilePreset(preset_key, StatValues(hp=252)).apply(base_stats)
    if preset_key == "max_hp_def":
        return StatProfilePreset(preset_key, StatValues(hp=252, defense=252)).apply(base_stats)
    if preset_key == "max_hp_def_plus":
        return StatProfilePreset(
            preset_key,
            StatValues(hp=252, defense=252),
            NatureModifier.increase(StatField.DEFENSE),
        ).apply(base_stats)
    if preset_key == "max_hp_spdef":
        return StatProfilePreset(
            preset_key,
            StatValues(hp=252, special_defense=252),
        ).apply(base_stats)
    if preset_key == "max_hp_spdef_plus":
        return StatProfilePreset(
            preset_key,
            StatValues(hp=252, special_defense=252),
            NatureModifier.increase(StatField.SPECIAL_DEFENSE),
        ).apply(base_stats)
    raise CalculatorInputError(f"unsupported stat preset: {preset_key}")


class CalculateCatalogDamageUseCase:
    """编排数据库驱动的基础伤害计算器链路。

    该 use case 从 repository 读取规则集、宝可梦和招式资料，解释 UI 配置模板，
    构建纯 domain 输入并返回适合 HTTP/前端展示的结果 DTO。
    """

    def __init__(self, repository: CalculatorCatalogRepository) -> None:
        """保存 calculator repository 端口实现。

        Args:
            repository: 只暴露 calculator 所需读取模型的持久化端口。
        """
        self._repository = repository

    def execute(self, command: CalculateCatalogDamageCommand) -> CalculateCatalogDamageResult:
        """执行一次从 catalog ID 到 domain 伤害结果的完整计算。

        Args:
            command: 包含 ruleset、双方 pokemon_id、move_id 和 stat preset 的输入命令。

        Returns:
            包含双方实际能力值、伤害 16 档、KO 概率和基础模式范围说明的结果。

        Raises:
            CalculatorInputError: 输入组合不存在、招式不可计算或宝可梦不能使用该招式。
        """
        ruleset = self._require_ruleset(command.ruleset_id)
        attacker_profile = self._require_pokemon(
            ruleset_id=ruleset.ruleset_id,
            pokemon_id=command.attacker.pokemon_id,
            role="attacker",
        )
        defender_profile = self._require_pokemon(
            ruleset_id=ruleset.ruleset_id,
            pokemon_id=command.defender.pokemon_id,
            role="defender",
        )
        move_profile = self._require_move(
            ruleset_id=ruleset.ruleset_id,
            move_id=command.move_id,
        )

        if not self._repository.pokemon_can_use_move(
            ruleset_id=ruleset.ruleset_id,
            pokemon_id=attacker_profile.pokemon_id,
            move_id=move_profile.move_id,
        ):
            raise CalculatorInputError("move is not available for attacker in this ruleset")

        attacker_stats = calculate_actual_stats(
            _preset_profile(command.attacker.stat_preset, attacker_profile.base_stats),
            level=command.attacker.level,
        )
        defender_stats = calculate_actual_stats(
            _preset_profile(command.defender.stat_preset, defender_profile.base_stats),
            level=command.defender.level,
        )

        attacker = BattlePokemon(
            name=attacker_profile.identifier,
            level=command.attacker.level,
            types=attacker_profile.types,
            stats=attacker_stats,
        )
        defender = BattlePokemon(
            name=defender_profile.identifier,
            level=command.defender.level,
            types=defender_profile.types,
            stats=defender_stats,
        )
        move = BattleMove(
            name=move_profile.identifier,
            type=move_profile.type,
            category=move_profile.category,
            power=move_profile.power,
        )
        domain_ruleset = resolve_ruleset_by_version_group(ruleset.version_group_id)

        damage = calculate_damage_rolls(
            DamageContextBuilder.for_move(
                attacker=attacker,
                defender=defender,
                move=move,
            )
            .with_ruleset(domain_ruleset)
            .build()
        )
        ko_chance = estimate_ko_chance(
            rolls=damage.rolls,
            defender_hp=defender.stats.hp,
        )

        return CalculateCatalogDamageResult(
            ruleset=ruleset,
            attacker=CalculatorPokemonResult(
                pokemon_id=attacker_profile.pokemon_id,
                identifier=attacker_profile.identifier,
                display_name=attacker_profile.display_name,
                level=command.attacker.level,
                preset=self._preset_view(command.attacker.stat_preset, attacker=True),
                stats=attacker_stats,
                effective_attack=offensive_stat(attacker, move),
            ),
            defender=CalculatorPokemonResult(
                pokemon_id=defender_profile.pokemon_id,
                identifier=defender_profile.identifier,
                display_name=defender_profile.display_name,
                level=command.defender.level,
                preset=self._preset_view(command.defender.stat_preset, attacker=False),
                stats=defender_stats,
                effective_hp=defender_stats.hp,
                effective_defense=defensive_stat(defender, move),
            ),
            move=CalculatorMoveResult(
                move_id=move_profile.move_id,
                identifier=move_profile.identifier,
                display_name=move_profile.display_name,
                type=move_profile.type.name.lower(),
                type_name=move_profile.type_name,
                category=move_profile.category,
                power=move_profile.power,
            ),
            damage=damage,
            ko_chance=ko_chance,
            scope=CalculationScope(
                mode="basic",
                included=("等级", "能力值模板", "招式固定威力", "STAB", "属性克制", "16 档随机伤害"),
                excluded=("特性", "道具", "天气", "场地", "状态", "会心", "双打范围修正", "动态威力招式"),
            ),
            warnings=(),
        )

    def _require_ruleset(self, ruleset_id: str) -> CalculatorRulesetContext:
        """读取规则集，不存在时转成稳定的用户输入错误。"""
        ruleset = self._repository.get_ruleset_context(ruleset_id)
        if ruleset is None:
            raise CalculatorInputError(f"unknown ruleset_id: {ruleset_id}")
        return ruleset

    def _require_pokemon(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        role: str,
    ) -> CalculatorPokemonProfile:
        """读取宝可梦战斗资料，不存在时标明是攻击方或防守方缺失。"""
        profile = self._repository.get_pokemon_profile(
            ruleset_id=ruleset_id,
            pokemon_id=pokemon_id,
        )
        if profile is None:
            raise CalculatorInputError(f"unknown {role} pokemon_id: {pokemon_id}")
        return profile

    def _require_move(self, *, ruleset_id: str, move_id: int) -> CalculatorMoveProfile:
        """读取并校验招式资料，只允许固定威力物理/特殊招式进入计算。"""
        move = self._repository.get_move_profile(ruleset_id=ruleset_id, move_id=move_id)
        if move is None:
            raise CalculatorInputError(f"unknown move_id: {move_id}")
        if move.category not in (MoveCategory.PHYSICAL, MoveCategory.SPECIAL):
            raise CalculatorInputError("status moves are not supported in basic calculator")
        if move.power <= 0:
            raise CalculatorInputError("moves without fixed positive power are not supported")
        return move

    def _preset_view(self, preset_key: str, *, attacker: bool) -> StatPresetView:
        """按攻防侧选择可展示的模板文案。"""
        presets = ATTACKER_PRESETS if attacker else DEFENDER_PRESETS
        try:
            return presets[preset_key]
        except KeyError as exc:
            raise CalculatorInputError(f"unsupported stat preset: {preset_key}") from exc


__all__ = [
    "ATTACKER_PRESETS",
    "DEFAULT_LEVEL",
    "DEFAULT_RULESET_ID",
    "DEFENDER_PRESETS",
    "CalculateCatalogDamageCommand",
    "CalculateCatalogDamageResult",
    "CalculateCatalogDamageUseCase",
    "CalculateCatalogPokemonCommand",
    "CalculatorCatalogRepository",
    "CalculatorInputError",
    "CalculatorMoveProfile",
    "CalculatorMoveSearchResult",
    "CalculatorPokemonProfile",
    "CalculatorPokemonSearchResult",
    "CalculatorRulesetContext",
]
