from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pokeop.application.use_cases.calculate_catalog_damage import (
    CalculationScope,
    CalculateCatalogDamageResult,
    CalculateCatalogDamageUseCase,
    CalculatorCatalogRepository,
    CalculatorInputError,
    CalculatorMoveResult,
    CalculatorPokemonResult,
    CalculatorRulesetContext,
    stat_profile_from_preset,
)
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import BattleMove, BattlePokemon, DamageContextBuilder
from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.ko import estimate_ko_chance
from pokeop.domain.battle.modifiers import defensive_stat, offensive_stat
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_version_group
from pokeop.domain.battle.stat_stage_math import apply_stat_stages
from pokeop.domain.battle.state import StatStages
from pokeop.domain.battle.stats import calculate_actual_stats


@dataclass(frozen=True)
class CalculatorAbilityOption:
    """一只 Pokémon 在当前规则集下可选择的特性。"""

    ability_id: int
    identifier: str
    display_name: str
    slot: int
    is_hidden: bool
    implemented: bool
    effect_identifier: str | None


class CalculatorAbilityRepository(Protocol):
    """特性选择和合法性校验所需的持久化读取端口。"""

    def list_pokemon_ability_options(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
    ) -> tuple[CalculatorAbilityOption, ...]:
        """读取 Pokémon 在目标规则集下的 version-aware 特性列表。"""


@dataclass(frozen=True)
class CalculateCatalogPokemonWithAbilityCommand:
    """一次伤害计算中一侧 Pokémon 的显式用户选择。

    Attributes:
        pokemon_id: 服务端用于查询战斗资料的 PokeAPI Pokémon ID。
        level: 本次伤害计算等级，HTTP 层限制为 1 到 100。
        stat_preset: application 配置模板或不可变配置快照标识。
        ability_identifier: 必须属于当前 Pokémon 的特性 identifier。
        item_identifier: 可选持有道具 identifier；None 表示不携带道具。
        stat_stages: 当前战斗中的七项能力等级，默认全部为零。
    """

    pokemon_id: int
    level: int
    stat_preset: str
    ability_identifier: str
    item_identifier: str | None = None
    stat_stages: StatStages = StatStages()


@dataclass(frozen=True)
class CalculateCatalogDamageWithAbilitiesCommand:
    """包含双方必选特性、能力等级和招式选择的 catalog 伤害计算命令。"""

    ruleset_id: str
    attacker: CalculateCatalogPokemonWithAbilityCommand
    defender: CalculateCatalogPokemonWithAbilityCommand
    move_id: int


@dataclass(frozen=True)
class _ResolvedAbility:
    """保留用户选择与实际进入 domain 的特性实现。"""

    option: CalculatorAbilityOption
    domain_value: DamageAbility


class CalculateCatalogDamageWithAbilitiesUseCase(CalculateCatalogDamageUseCase):
    """在现有 catalog 计算链路上增加双方必选特性、能力等级和合法性校验。"""

    def __init__(
        self,
        catalog_repository: CalculatorCatalogRepository,
        ability_repository: CalculatorAbilityRepository,
    ) -> None:
        """保存 catalog 与特性读取端口。

        Args:
            catalog_repository: 读取规则集、Pokémon、招式和道具的 repository。
            ability_repository: 读取 Pokémon 合法特性及实现状态的 repository。
        """
        super().__init__(catalog_repository)
        self._ability_repository = ability_repository

    def execute(
        self,
        command: CalculateCatalogDamageWithAbilitiesCommand,
    ) -> CalculateCatalogDamageResult:
        """校验双方特性归属，并把战斗能力等级应用到实际伤害能力。

        Args:
            command: 包含规则集、双方配置、能力等级和攻击方招式的完整命令。

        Returns:
            保留配置基础能力，并提供已经应用相关能力等级的有效攻防值、伤害档位和提示。

        Raises:
            CalculatorInputError: Pokémon、招式、特性或配置组合不合法时抛出。
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

        attacker_ability = self._require_ability(
            ruleset=ruleset,
            pokemon_id=attacker_profile.pokemon_id,
            identifier=command.attacker.ability_identifier,
            role="attacker",
        )
        defender_ability = self._require_ability(
            ruleset=ruleset,
            pokemon_id=defender_profile.pokemon_id,
            identifier=command.defender.ability_identifier,
            role="defender",
        )

        attacker_base_stats = calculate_actual_stats(
            stat_profile_from_preset(
                command.attacker.stat_preset,
                attacker_profile.base_stats,
            ),
            level=command.attacker.level,
        )
        defender_base_stats = calculate_actual_stats(
            stat_profile_from_preset(
                command.defender.stat_preset,
                defender_profile.base_stats,
            ),
            level=command.defender.level,
        )
        attacker_stats = apply_stat_stages(
            attacker_base_stats,
            command.attacker.stat_stages,
        )
        defender_stats = apply_stat_stages(
            defender_base_stats,
            command.defender.stat_stages,
        )

        attacker = BattlePokemon(
            name=attacker_profile.identifier,
            level=command.attacker.level,
            types=attacker_profile.types,
            stats=attacker_stats,
            ability=attacker_ability.domain_value,
            item=self._item_from_identifier(command.attacker.item_identifier),
        )
        defender = BattlePokemon(
            name=defender_profile.identifier,
            level=command.defender.level,
            types=defender_profile.types,
            stats=defender_stats,
            ability=defender_ability.domain_value,
            item=self._item_from_identifier(command.defender.item_identifier),
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
                stats=attacker_base_stats,
                effective_attack=offensive_stat(attacker, move),
            ),
            defender=CalculatorPokemonResult(
                pokemon_id=defender_profile.pokemon_id,
                identifier=defender_profile.identifier,
                display_name=defender_profile.display_name,
                level=command.defender.level,
                preset=self._preset_view(command.defender.stat_preset, attacker=False),
                stats=defender_base_stats,
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
                included=(
                    "等级",
                    "能力值模板",
                    "攻击/防御/特攻/特防能力等级",
                    "已实现持有道具",
                    "已实现特性",
                    "招式固定威力",
                    "STAB",
                    "属性克制",
                    "16 档随机伤害",
                ),
                excluded=(
                    "速度/命中/回避对单次伤害值的影响",
                    "未实现特性",
                    "未实现道具",
                    "天气",
                    "场地",
                    "状态",
                    "会心",
                    "双打范围修正",
                    "动态威力招式",
                ),
            ),
            warnings=(
                *self._ability_warnings(
                    attacker=attacker_ability,
                    defender=defender_ability,
                ),
                *self._stat_stage_warnings(command),
            ),
        )

    def _require_ability(
        self,
        *,
        ruleset: CalculatorRulesetContext,
        pokemon_id: int,
        identifier: str,
        role: str,
    ) -> _ResolvedAbility:
        """校验必选特性属于当前 Pokémon，并解析成已实现或 no-op domain 值。

        Args:
            ruleset: 已校验存在的 calculator 规则集上下文。
            pokemon_id: 当前侧 Pokémon ID。
            identifier: 用户显式选择的特性 identifier。
            role: 错误文本中使用的 attacker 或 defender 角色名。

        Returns:
            同时保留展示候选与 domain 特性枚举的解析结果。

        Raises:
            CalculatorInputError: identifier 为空或不属于当前 Pokémon 时抛出。
        """
        normalized = identifier.strip()
        if not normalized:
            raise CalculatorInputError(f"{role} ability_identifier is required")
        options = self._ability_repository.list_pokemon_ability_options(
            ruleset_id=ruleset.ruleset_id,
            pokemon_id=pokemon_id,
        )
        option = next(
            (candidate for candidate in options if candidate.identifier == normalized),
            None,
        )
        if option is None:
            raise CalculatorInputError(
                f"ability is not available for {role} in this ruleset: {normalized}"
            )
        return _ResolvedAbility(
            option=option,
            domain_value=DamageAbility.from_identifier(option.effect_identifier),
        )

    @staticmethod
    def _ability_warnings(
        *,
        attacker: _ResolvedAbility,
        defender: _ResolvedAbility,
    ) -> tuple[str, ...]:
        """为被选中的未实现特性生成可展示的降级说明。

        Args:
            attacker: 攻击方特性解析结果。
            defender: 防守方特性解析结果。

        Returns:
            每个未实现且合法的特性对应一条中文提示；全部实现时返回空元组。
        """
        warnings: list[str] = []
        for role, resolved in (("攻击方", attacker), ("防守方", defender)):
            if not resolved.option.implemented:
                warnings.append(
                    f"{role}特性“{resolved.option.display_name}”尚未实现，本次按无特性处理。"
                )
        return tuple(warnings)

    @staticmethod
    def _stat_stage_warnings(
        command: CalculateCatalogDamageWithAbilitiesCommand,
    ) -> tuple[str, ...]:
        """提示当前单次伤害模式尚不消费速度、命中和回避等级。

        Args:
            command: 已通过 HTTP 范围校验的完整计算命令。

        Returns:
            任一侧选择非零速度、命中或回避等级时返回一条统一提示，否则返回空元组。
        """
        for stages in (command.attacker.stat_stages, command.defender.stat_stages):
            if stages.speed != 0 or stages.accuracy != 0 or stages.evasion != 0:
                return (
                    "当前单次伤害按招式已命中计算；速度、命中和回避等级已保留，但不改变本次伤害值。",
                )
        return ()


__all__ = [
    "CalculateCatalogDamageWithAbilitiesCommand",
    "CalculateCatalogDamageWithAbilitiesUseCase",
    "CalculateCatalogPokemonWithAbilityCommand",
    "CalculatorAbilityOption",
    "CalculatorAbilityRepository",
]
