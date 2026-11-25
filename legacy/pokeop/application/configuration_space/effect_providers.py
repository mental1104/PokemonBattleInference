"""实现特性与受控道具候选的 factory 覆盖过滤。"""

from __future__ import annotations

from pokeop.application.configuration_space.coverage import MechanismCoverageRecord
from pokeop.application.configuration_space.model_base import MechanismSupportStatus
from pokeop.application.configuration_space.provider_core import (
    AbilityDimensionValue,
    ConfigurationGenerationContext,
    DimensionExpansion,
    ItemDimensionValue,
    _factory_support_status,
)
from pokeop.domain.battle.effects.protocols import EffectCoverageStatus
from pokeop.domain.battle.effects.registry import normalize_effect_identifier


class AbilityDimensionProvider:
    """只保留 repository 合法且当前规则集 factory 可创建的特性候选。"""

    @property
    def dimension_key(self) -> str:
        """返回特性维度稳定键。"""
        return "ability"

    def expand(self, context: ConfigurationGenerationContext) -> DimensionExpansion:
        """筛选、规范化并归并当前 Pokémon 的合法特性。

        Args:
            context: 当前 profile、特性候选池和规则集 factory。

        Returns:
            以 factory coverage identifier 为签名的唯一特性值与覆盖记录。
        """
        requested = {
            normalize_effect_identifier(identifier)
            for identifier in context.command.abilities.candidate_identifiers
        }
        coverage_records: list[MechanismCoverageRecord] = []
        grouped: dict[str, AbilityDimensionValue] = {}

        for candidate in context.profile.abilities:
            normalized_input = normalize_effect_identifier(candidate.identifier)
            if requested and normalized_input not in requested:
                coverage_records.append(
                    MechanismCoverageRecord(
                        side=context.side,
                        dimension_key=self.dimension_key,
                        identifier=normalized_input,
                        support_status=candidate.support_status,
                        included=False,
                        reason="The ability is legal but excluded by the command candidate pool.",
                    )
                )
                continue
            if candidate.support_status is not MechanismSupportStatus.SUPPORTED:
                coverage_records.append(
                    MechanismCoverageRecord(
                        side=context.side,
                        dimension_key=self.dimension_key,
                        identifier=normalized_input,
                        support_status=candidate.support_status,
                        included=False,
                        reason=candidate.support_reason,
                    )
                )
                continue

            effect = context.effect_factory.create_ability_effect(candidate.identifier)
            factory_status = effect.coverage.status
            included = factory_status is EffectCoverageStatus.SUPPORTED
            support_status = _factory_support_status(factory_status)
            coverage_records.append(
                MechanismCoverageRecord(
                    side=context.side,
                    dimension_key=self.dimension_key,
                    identifier=normalized_input,
                    support_status=support_status,
                    included=included,
                    reason=effect.coverage.reason,
                    factory_status=factory_status,
                )
            )
            if not included:
                continue

            identifier = effect.coverage.identifier
            current = grouped.get(identifier)
            grouped[identifier] = AbilityDimensionValue(
                identifier=identifier,
                member_count=1 if current is None else current.member_count + 1,
            )

        return DimensionExpansion(
            values=tuple(grouped.values()),
            coverage_records=tuple(coverage_records),
        )


class ItemDimensionProvider:
    """枚举 command 明确指定的受控道具集合，不访问全游戏道具表。"""

    @property
    def dimension_key(self) -> str:
        """返回道具维度稳定键。"""
        return "item"

    def expand(self, context: ConfigurationGenerationContext) -> DimensionExpansion:
        """通过规则集 factory 校验无道具和显式候选道具。

        Args:
            context: 当前单边 command 与规则集 effect factory。

        Returns:
            规范化、去重后的道具值和每个受控候选的覆盖记录。
        """
        coverage_records: list[MechanismCoverageRecord] = []
        grouped: dict[str, ItemDimensionValue] = {}

        for candidate in context.command.items.candidate_identifiers:
            effect = context.effect_factory.create_item_effect(candidate)
            no_item = candidate is None
            included = (
                no_item and effect.coverage.status is EffectCoverageStatus.NO_EFFECT
            ) or effect.coverage.status is EffectCoverageStatus.SUPPORTED
            support_status = (
                MechanismSupportStatus.SUPPORTED
                if included
                else _factory_support_status(effect.coverage.status)
            )
            identifier = effect.coverage.identifier
            coverage_records.append(
                MechanismCoverageRecord(
                    side=context.side,
                    dimension_key=self.dimension_key,
                    identifier=identifier,
                    support_status=support_status,
                    included=included,
                    reason=effect.coverage.reason,
                    factory_status=effect.coverage.status,
                )
            )
            if not included:
                continue

            current = grouped.get(identifier)
            grouped[identifier] = ItemDimensionValue(
                identifier=identifier,
                member_count=1 if current is None else current.member_count + 1,
            )

        return DimensionExpansion(
            values=tuple(grouped.values()),
            coverage_records=tuple(coverage_records),
        )


__all__ = ["AbilityDimensionProvider", "ItemDimensionProvider"]
