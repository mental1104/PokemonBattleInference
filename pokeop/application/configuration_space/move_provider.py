"""实现当前规则集支持招式的过滤、组合和行为归并。"""

from __future__ import annotations

from itertools import combinations
from math import prod

from pokeop.application.configuration_space.model_base import (
    ConfigurationSpaceError,
    MechanismSupportStatus,
)
from pokeop.application.configuration_space.configurations import ConfiguredMove
from pokeop.application.configuration_space.coverage import MechanismCoverageRecord
from pokeop.application.configuration_space.provider_core import (
    ConfigurationGenerationContext,
    DimensionExpansion,
    MoveSetDimensionValue,
    _MoveOption,
    _factory_support_status,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.protocols import EffectCoverageStatus
from pokeop.domain.battle.specs import MoveSpecKey


class MoveSetDimensionProvider:
    """从合法可学习招式中筛选当前 engine 支持项并生成 1～4 招式组合。"""

    @property
    def dimension_key(self) -> str:
        """返回招式维度稳定键。"""
        return "moves"

    def expand(self, context: ConfigurationGenerationContext) -> DimensionExpansion:
        """生成满足命令候选池、槽位数量和 effect 覆盖要求的招式组合。

        合法但当前不可执行的候选仍进入覆盖报告；只有 repository 与 factory 均确认支持，
        且携带完整 ``MoveSpec`` 的候选才会进入组合枚举。

        Args:
            context: 当前 Pokémon profile、单边 command、规则集 factory 和阵营。

        Returns:
            去除重复行为候选后的招式组合及所有合法招式的覆盖记录。

        Raises:
            ConfigurationSpaceError: repository 将缺少 ``MoveSpec`` 的候选错误标记为
                supported，或组合数量超过运行保护时抛出。
        """
        requested_ids = set(context.command.moves.candidate_move_ids)
        coverage_records: list[MechanismCoverageRecord] = []
        grouped_options: dict[tuple[MoveSpecKey, str], _MoveOption] = {}

        for candidate in context.profile.moves:
            move_id = candidate.move_id
            if requested_ids and move_id not in requested_ids:
                coverage_records.append(
                    MechanismCoverageRecord(
                        side=context.side,
                        dimension_key=self.dimension_key,
                        identifier=candidate.identifier,
                        support_status=candidate.support_status,
                        included=False,
                        reason="The move is legal but excluded by the command candidate pool.",
                    )
                )
                continue
            if candidate.support_status is not MechanismSupportStatus.SUPPORTED:
                coverage_records.append(
                    MechanismCoverageRecord(
                        side=context.side,
                        dimension_key=self.dimension_key,
                        identifier=candidate.identifier,
                        support_status=candidate.support_status,
                        included=False,
                        reason=candidate.support_reason,
                    )
                )
                continue

            move_spec = candidate.move_spec
            if move_spec is None:
                # supported 候选必须已经具有完整 domain 输入；否则继续执行会绕过威力等不变量。
                raise ConfigurationSpaceError(
                    "supported move candidate is missing an executable MoveSpec"
                )
            effect = context.effect_factory.create_move_effect(
                candidate.effect_identifier
            )
            factory_status = effect.coverage.status
            no_effect_is_complete = (
                candidate.effect_identifier is None
                and move_spec.move.category is not MoveCategory.STATUS
                and factory_status is EffectCoverageStatus.NO_EFFECT
            )
            included = (
                factory_status is EffectCoverageStatus.SUPPORTED
                or no_effect_is_complete
            )
            support_status = (
                MechanismSupportStatus.SUPPORTED
                if included
                else _factory_support_status(factory_status)
            )
            reason = (
                effect.coverage.reason
                if included
                else (
                    "A status move requires an explicit supported effect implementation."
                    if move_spec.move.category is MoveCategory.STATUS
                    and factory_status is EffectCoverageStatus.NO_EFFECT
                    else effect.coverage.reason
                )
            )
            coverage_records.append(
                MechanismCoverageRecord(
                    side=context.side,
                    dimension_key=self.dimension_key,
                    identifier=candidate.identifier,
                    support_status=support_status,
                    included=included,
                    reason=reason,
                    factory_status=factory_status,
                )
            )
            if not included:
                continue

            normalized_effect = (
                None
                if factory_status is EffectCoverageStatus.NO_EFFECT
                else effect.coverage.identifier
            )
            configured_move = ConfiguredMove(
                move_spec=move_spec,
                effect_identifier=normalized_effect,
            )
            signature = configured_move.behavior_signature
            current = grouped_options.get(signature)
            if current is None:
                grouped_options[signature] = _MoveOption(configured_move, 1)
            else:
                grouped_options[signature] = _MoveOption(
                    current.configured_move,
                    current.member_count + 1,
                )

        options = tuple(
            sorted(
                grouped_options.values(),
                key=lambda value: (
                    value.configured_move.move_spec.move_id,
                    repr(value.configured_move.behavior_signature),
                ),
            )
        )
        grouped_sets: dict[
            tuple[tuple[MoveSpecKey, str], ...],
            MoveSetDimensionValue,
        ] = {}
        raw_combination_count = 0
        for slot_count in context.command.moves.slot_counts:
            for selected in combinations(options, slot_count):
                move_ids = tuple(
                    option.configured_move.move_spec.move_id for option in selected
                )
                # 同一招式 ID 的不同 projection 不能占据多个招式槽。
                if len(move_ids) != len(set(move_ids)):
                    continue
                configured_moves = tuple(
                    sorted(
                        (option.configured_move for option in selected),
                        key=lambda move: move.move_spec.move_id,
                    )
                )
                signature = tuple(
                    move.behavior_signature for move in configured_moves
                )
                member_count = prod(option.member_count for option in selected)
                raw_combination_count += member_count
                if (
                    raw_combination_count
                    > context.command.moves.max_raw_combinations
                ):
                    raise ConfigurationSpaceError(
                        "move-set enumeration exceeds max_raw_combinations"
                    )
                current = grouped_sets.get(signature)
                if current is None:
                    grouped_sets[signature] = MoveSetDimensionValue(
                        configured_moves,
                        member_count,
                    )
                else:
                    grouped_sets[signature] = MoveSetDimensionValue(
                        current.moves,
                        current.member_count + member_count,
                    )

        return DimensionExpansion(
            values=tuple(grouped_sets.values()),
            coverage_records=tuple(coverage_records),
        )




__all__ = ["MoveSetDimensionProvider"]
