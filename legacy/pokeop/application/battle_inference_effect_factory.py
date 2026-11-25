"""为完整推演提供可解释的合法但未实现特性中性建模边界。"""

from __future__ import annotations

from dataclasses import dataclass, field

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.effects.factories import (
    BattleEffectFamily,
    PokemonChampionEffectFactory,
)
from pokeop.domain.battle.effects.protocols import (
    AbilityEffect,
    EffectCapabilityCoverage,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
    ItemEffect,
    MoveEffect,
)
from pokeop.domain.battle.effects.registry import normalize_effect_identifier
from pokeop.domain.battle.items import DamageItem


@dataclass(frozen=True, slots=True)
class NeutralUnsupportedAbilityEffect:
    """表示合法但尚未实现、在当前推演中按中性行为处理的特性。

    该对象不实现任何战斗阶段协议，因此不会修改行动、伤害或状态。整体 coverage 使用
    SUPPORTED 只是声明“中性占位建模可执行”，真实特性行为仍通过 unsupported 子能力
    明确暴露，调用方不得把结果解释为已完整支持该特性。
    """

    coverage: EffectCoverage


@dataclass(frozen=True, slots=True)
class TransparentPokemonChampionEffectFactory:
    """在 Pokémon Champion 工厂外增加显式中性特性假设。

    Args:
        base: 提供已实现招式、特性和道具产品的真实 domain 工厂。
        neutral_ability_identifiers: 允许在推演中按中性行为继续计算的合法特性标识。
    """

    base: PokemonChampionEffectFactory = field(default_factory=PokemonChampionEffectFactory)
    neutral_ability_identifiers: frozenset[str] = frozenset({"pressure", "pickpocket"})

    @property
    def ruleset_id(self) -> str:
        """返回被包装工厂负责的稳定规则集标识。"""
        return self.base.ruleset_id

    def create_move_effect(self, identifier: str | None) -> MoveEffect:
        """委托真实工厂创建招式 effect。

        Args:
            identifier: 规范化前的可选招式机制标识。

        Returns:
            真实 Pokémon Champion 工厂创建的招式产品。
        """
        return self.base.create_move_effect(identifier)

    def create_ability_effect(
        self,
        identifier: DamageAbility | str | None,
    ) -> AbilityEffect:
        """创建真实特性 effect，或为白名单合法特性返回透明中性占位。

        Args:
            identifier: domain enum、repository identifier 或未配置值。

        Returns:
            已实现真实特性产品，或明确声明行为未覆盖的中性占位产品。
        """
        effect = self.base.create_ability_effect(identifier)
        if effect.coverage.status is not EffectCoverageStatus.UNSUPPORTED:
            return effect
        normalized = (
            identifier.value
            if isinstance(identifier, DamageAbility)
            else normalize_effect_identifier(identifier or "")
        )
        if normalized not in self.neutral_ability_identifiers:
            return effect
        return NeutralUnsupportedAbilityEffect(
            coverage=EffectCoverage(
                ruleset_id=self.ruleset_id,
                source_kind=EffectSourceKind.ABILITY,
                identifier=normalized,
                status=EffectCoverageStatus.SUPPORTED,
                reason=(
                    "该合法特性尚未实现；本次推演显式采用不修改战斗状态的中性假设。"
                ),
                capabilities=(
                    EffectCapabilityCoverage(
                        identifier="real_ability_behavior",
                        status=EffectCoverageStatus.UNSUPPORTED,
                        reason=(
                            "真实特性行为未纳入当前 domain，结果只覆盖中性占位假设。"
                        ),
                    ),
                ),
            )
        )

    def create_item_effect(
        self,
        identifier: DamageItem | str | None,
    ) -> ItemEffect:
        """委托真实工厂创建道具 effect。

        Args:
            identifier: domain enum、repository identifier 或未配置值。

        Returns:
            真实 Pokémon Champion 工厂创建的道具产品。
        """
        return self.base.create_item_effect(identifier)

    def create_effect_family(
        self,
        *,
        move_identifier: str | None,
        ability_identifier: DamageAbility | str | None,
        item_identifier: DamageItem | str | None,
    ) -> BattleEffectFamily:
        """一次创建同规则集下的招式、特性和道具产品族。

        Args:
            move_identifier: 可选招式机制标识。
            ability_identifier: 特性标识，可触发透明中性建模。
            item_identifier: 可选道具标识。

        Returns:
            可交给 dispatcher 的同规则集产品族。
        """
        return BattleEffectFamily(
            move=self.create_move_effect(move_identifier),
            ability=self.create_ability_effect(ability_identifier),
            item=self.create_item_effect(item_identifier),
        )


__all__ = [
    "NeutralUnsupportedAbilityEffect",
    "TransparentPokemonChampionEffectFactory",
]
