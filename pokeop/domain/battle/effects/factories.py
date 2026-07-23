from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Protocol, TypeVar

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.effects.adapters import (
    AbilityDamageEffectAdapter,
    ItemDamageEffectAdapter,
)
from pokeop.domain.battle.effects.products import (
    NoOpAbilityEffect,
    NoOpItemEffect,
    NoOpMoveEffect,
    UnsupportedAbilityEffect,
    UnsupportedItemEffect,
    UnsupportedMoveEffect,
)
from pokeop.domain.battle.effects.protocols import (
    AbilityEffect,
    BattleEffect,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
    ItemEffect,
    MoveEffect,
)
from pokeop.domain.battle.effects.registry import (
    EffectRegistration,
    EffectRegistry,
    normalize_effect_identifier,
)
from pokeop.domain.battle.items import DamageItem

EffectT = TypeVar("EffectT", bound=BattleEffect)


@dataclass(frozen=True, slots=True)
class BattleEffectFamily:
    """保存同一规则集工厂创建的一组招式、特性和道具 effect。"""

    move: MoveEffect
    ability: AbilityEffect
    item: ItemEffect

    @property
    def coverage(self) -> tuple[EffectCoverage, ...]:
        """返回三个产品的覆盖记录，供 application 结果统一暴露。"""
        return (
            self.move.coverage,
            self.ability.coverage,
            self.item.coverage,
        )


class BattleEffectAbstractFactory(Protocol):
    """创建同一规则集下相互匹配的招式、特性和道具 effect 产品族。"""

    @property
    def ruleset_id(self) -> str:
        """返回该具体工厂负责的规则集标识。"""
        ...

    def create_move_effect(self, identifier: str | None) -> MoveEffect:
        """根据 domain identifier 创建招式 effect。"""
        ...

    def create_ability_effect(
        self,
        identifier: DamageAbility | str | None,
    ) -> AbilityEffect:
        """根据 domain identifier 创建特性 effect。"""
        ...

    def create_item_effect(
        self,
        identifier: DamageItem | str | None,
    ) -> ItemEffect:
        """根据 domain identifier 创建道具 effect。"""
        ...

    def create_effect_family(
        self,
        *,
        move_identifier: str | None,
        ability_identifier: DamageAbility | str | None,
        item_identifier: DamageItem | str | None,
    ) -> BattleEffectFamily:
        """一次创建同一规则集下相互匹配的 effect 产品族。"""
        ...


def _supported_ability_effect(
    ruleset_id: str,
    ability: DamageAbility,
) -> AbilityEffect:
    """创建一个包装现有 ability damage effect 的当前规则集产品。

    Args:
        ruleset_id: 具体工厂负责的规则集标识。
        ability: 已规范化且不为 UNKNOWN 的伤害相关特性。

    Returns:
        带 supported 覆盖记录的 ability damage adapter。
    """
    return AbilityDamageEffectAdapter(
        coverage=EffectCoverage(
            ruleset_id=ruleset_id,
            source_kind=EffectSourceKind.ABILITY,
            identifier=ability.value,
            status=EffectCoverageStatus.SUPPORTED,
            reason="Existing ability damage behavior is available through an adapter.",
        ),
        wrapped=ability.create_effect(),
    )


def _supported_item_effect(
    ruleset_id: str,
    item: DamageItem,
) -> ItemEffect:
    """创建一个包装现有 item damage effect 的当前规则集产品。

    Args:
        ruleset_id: 具体工厂负责的规则集标识。
        item: 已规范化且不为 UNKNOWN 的伤害相关道具。

    Returns:
        带 supported 覆盖记录的 item damage adapter。
    """
    return ItemDamageEffectAdapter(
        coverage=EffectCoverage(
            ruleset_id=ruleset_id,
            source_kind=EffectSourceKind.ITEM,
            identifier=item.value,
            status=EffectCoverageStatus.SUPPORTED,
            reason="Existing item damage behavior is available through an adapter.",
        ),
        wrapped=item.create_effect(),
    )


class PokemonChampionEffectFactory:
    """创建 Pokemon Champion 规则集使用的显式 battle effect 产品族。

    默认 registry 只注册当前已经有真实 domain 实现的伤害相关特性和道具。
    招式 registry 初始为空，因此非空招式 identifier 会明确标记为 unsupported，
    而不是伪装成完整支持。后续新增机制只需提供实现并追加注册项。
    """

    RULESET_ID = "pokemon-champion"

    def __init__(
        self,
        *,
        move_registry: EffectRegistry[MoveEffect] | None = None,
        ability_registry: EffectRegistry[AbilityEffect] | None = None,
        item_registry: EffectRegistry[ItemEffect] | None = None,
    ) -> None:
        """初始化当前规则集使用的三个类型化 registry。

        Args:
            move_registry: 招式 effect registry；None 使用空 registry。
            ability_registry: 特性 effect registry；None 注册现有伤害特性 adapter。
            item_registry: 道具 effect registry；None 注册现有伤害道具 adapter。
        """
        self._move_registry = move_registry or EffectRegistry()
        self._ability_registry = ability_registry or self._default_ability_registry()
        self._item_registry = item_registry or self._default_item_registry()

    @property
    def ruleset_id(self) -> str:
        """返回当前具体工厂负责的 Pokemon Champion 规则集标识。"""
        return self.RULESET_ID

    def _default_ability_registry(self) -> EffectRegistry[AbilityEffect]:
        """构建包含现有伤害特性 adapter 的默认显式 registry。"""
        registrations = tuple(
            EffectRegistration[AbilityEffect](
                ability.value,
                partial(_supported_ability_effect, self.ruleset_id, ability),
            )
            for ability in DamageAbility
            if ability is not DamageAbility.UNKNOWN
        )
        return EffectRegistry(registrations)

    def _default_item_registry(self) -> EffectRegistry[ItemEffect]:
        """构建包含现有伤害道具 adapter 的默认显式 registry。"""
        registrations = tuple(
            EffectRegistration[ItemEffect](
                item.value,
                partial(_supported_item_effect, self.ruleset_id, item),
            )
            for item in DamageItem
            if item is not DamageItem.UNKNOWN
        )
        return EffectRegistry(registrations)

    def _validate_registered_effect(
        self,
        effect: EffectT,
        expected_kind: EffectSourceKind,
    ) -> EffectT:
        """校验自定义 registry 仍返回当前规则集和正确来源类型的产品。

        Args:
            effect: registry provider 创建的 effect 产品。
            expected_kind: 当前 registry 对应的来源类型。

        Returns:
            通过规则集和来源校验的原 effect。

        Raises:
            ValueError: provider 返回了其他规则集或其他来源类型的产品。
        """
        if effect.coverage.ruleset_id != self.ruleset_id:
            raise ValueError("registered effect belongs to a different ruleset")
        if effect.coverage.source_kind is not expected_kind:
            raise ValueError("registered effect has an unexpected source kind")
        return effect

    def create_move_effect(self, identifier: str | None) -> MoveEffect:
        """创建招式 effect，并区分未配置与当前尚未支持。

        Args:
            identifier: 已从 persistence/DTO 转换出的招式机制标识；None 或空白表示
                当前没有需要参与阶段分发的招式机制。

        Returns:
            已注册 effect、显式 no-op effect 或显式 unsupported effect。
        """
        if identifier is None or not normalize_effect_identifier(identifier):
            return NoOpMoveEffect(
                EffectCoverage(
                    self.ruleset_id,
                    EffectSourceKind.MOVE,
                    "none",
                    EffectCoverageStatus.NO_EFFECT,
                    "No move effect identifier was configured.",
                )
            )

        normalized = normalize_effect_identifier(identifier)
        effect = self._move_registry.create(normalized)
        if effect is not None:
            return self._validate_registered_effect(effect, EffectSourceKind.MOVE)
        return UnsupportedMoveEffect(
            EffectCoverage(
                self.ruleset_id,
                EffectSourceKind.MOVE,
                normalized,
                EffectCoverageStatus.UNSUPPORTED,
                "The move effect is not implemented for this ruleset.",
            )
        )

    def create_ability_effect(
        self,
        identifier: DamageAbility | str | None,
    ) -> AbilityEffect:
        """创建特性 effect，并保留未知原始标识的 unsupported 语义。

        Args:
            identifier: domain enum、边界字符串或未配置值。

        Returns:
            已注册 ability adapter、显式 no-op effect 或 unsupported effect。
        """
        if identifier is None or identifier is DamageAbility.UNKNOWN:
            return NoOpAbilityEffect(
                EffectCoverage(
                    self.ruleset_id,
                    EffectSourceKind.ABILITY,
                    "none",
                    EffectCoverageStatus.NO_EFFECT,
                    "No supported ability identifier was configured.",
                )
            )

        if isinstance(identifier, DamageAbility):
            ability = identifier
            unsupported_identifier = ability.value
        else:
            if not identifier.strip():
                return self.create_ability_effect(None)
            ability = DamageAbility.from_identifier(identifier)
            unsupported_identifier = normalize_effect_identifier(identifier)
            if ability is DamageAbility.UNKNOWN:
                return UnsupportedAbilityEffect(
                    EffectCoverage(
                        self.ruleset_id,
                        EffectSourceKind.ABILITY,
                        unsupported_identifier,
                        EffectCoverageStatus.UNSUPPORTED,
                        "The ability identifier is not implemented for this ruleset.",
                    )
                )

        effect = self._ability_registry.create(ability.value)
        if effect is not None:
            return self._validate_registered_effect(effect, EffectSourceKind.ABILITY)
        return UnsupportedAbilityEffect(
            EffectCoverage(
                self.ruleset_id,
                EffectSourceKind.ABILITY,
                unsupported_identifier,
                EffectCoverageStatus.UNSUPPORTED,
                "The ability is known but has no registered effect implementation.",
            )
        )

    def create_item_effect(
        self,
        identifier: DamageItem | str | None,
    ) -> ItemEffect:
        """创建道具 effect，并保留未知原始标识的 unsupported 语义。

        Args:
            identifier: domain enum、边界字符串或未配置值。

        Returns:
            已注册 item adapter、显式 no-op effect 或 unsupported effect。
        """
        if identifier is None or identifier is DamageItem.UNKNOWN:
            return NoOpItemEffect(
                EffectCoverage(
                    self.ruleset_id,
                    EffectSourceKind.ITEM,
                    "none",
                    EffectCoverageStatus.NO_EFFECT,
                    "No supported item identifier was configured.",
                )
            )

        if isinstance(identifier, DamageItem):
            item = identifier
            unsupported_identifier = item.value
        else:
            if not identifier.strip():
                return self.create_item_effect(None)
            item = DamageItem.from_identifier(identifier)
            unsupported_identifier = normalize_effect_identifier(identifier)
            if item is DamageItem.UNKNOWN:
                return UnsupportedItemEffect(
                    EffectCoverage(
                        self.ruleset_id,
                        EffectSourceKind.ITEM,
                        unsupported_identifier,
                        EffectCoverageStatus.UNSUPPORTED,
                        "The item identifier is not implemented for this ruleset.",
                    )
                )

        effect = self._item_registry.create(item.value)
        if effect is not None:
            return self._validate_registered_effect(effect, EffectSourceKind.ITEM)
        return UnsupportedItemEffect(
            EffectCoverage(
                self.ruleset_id,
                EffectSourceKind.ITEM,
                unsupported_identifier,
                EffectCoverageStatus.UNSUPPORTED,
                "The item is known but has no registered effect implementation.",
            )
        )

    def create_effect_family(
        self,
        *,
        move_identifier: str | None,
        ability_identifier: DamageAbility | str | None,
        item_identifier: DamageItem | str | None,
    ) -> BattleEffectFamily:
        """一次创建当前规则集下相互匹配的 effect 产品族。

        Args:
            move_identifier: 招式机制标识；未配置时传 None。
            ability_identifier: 特性 enum、字符串或未配置值。
            item_identifier: 道具 enum、字符串或未配置值。

        Returns:
            包含 move、ability 和 item 三个 effect 的不可变产品族。
        """
        return BattleEffectFamily(
            move=self.create_move_effect(move_identifier),
            ability=self.create_ability_effect(ability_identifier),
            item=self.create_item_effect(item_identifier),
        )


__all__ = [
    "BattleEffectAbstractFactory",
    "BattleEffectFamily",
    "PokemonChampionEffectFactory",
]
