"""在 application composition 边界对账合法候选与当前 effect factory 覆盖状态。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from pokeop.application.repositories.battle_inference import (
    BattleInferenceAbilityProfile,
    BattleInferenceItemProfile,
    BattleInferenceMoveProfile,
    BattleInferencePokemonProfile,
    BattleInferenceRepository,
    BattleInferenceRulesetContext,
    MechanismCapability,
    MechanismSupportStatus,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.factories import BattleEffectAbstractFactory
from pokeop.domain.battle.effects.protocols import (
    EffectCoverage,
    EffectCoverageStatus,
)


@dataclass(frozen=True, slots=True)
class FactoryReconciledBattleInferenceRepository:
    """使用当前规则集 factory 校正 repository 的保守机制覆盖结论。

    persistence 只根据 PokeAPI 字段和已知基础枚举给出保守判断，因此带附加效果的合法招式
    可能先被标记为 partial，合法但未注册的特性可能被标记为 unsupported。该装饰器不会
    修改合法性、历史数据或候选集合；它只在具体 factory 已明确提供可执行产品时，把整体
    候选提升为 supported，并保留 factory 的结构化子能力缺口供最终结果解释。

    Args:
        repository: 提供 version-aware 合法候选的稳定读取端口。
        effect_factory: 当前 ruleset 的招式、特性与道具产品工厂。
    """

    repository: BattleInferenceRepository
    effect_factory: BattleEffectAbstractFactory

    def get_ruleset_context(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> BattleInferenceRulesetContext | None:
        """原样委托精确规则轴读取。

        Args:
            ruleset_id: 稳定规则集标识。
            version_group_id: PokeAPI version group 主轴。

        Returns:
            底层 repository 返回的规则上下文或 None。
        """
        return self.repository.get_ruleset_context(
            ruleset_id=ruleset_id,
            version_group_id=version_group_id,
        )

    def get_pokemon_profile(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
        pokemon_id: int,
    ) -> BattleInferencePokemonProfile | None:
        """读取合法 profile，并用当前 factory 对账机制执行覆盖。

        Args:
            ruleset_id: 稳定规则集标识。
            version_group_id: 历史数据与招式学习表查询主轴。
            pokemon_id: 当前规则轴下的 Pokémon ID。

        Returns:
            候选合法性不变、整体覆盖状态已与 factory 对账的 profile；不存在时返回 None。
        """
        profile = self.repository.get_pokemon_profile(
            ruleset_id=ruleset_id,
            version_group_id=version_group_id,
            pokemon_id=pokemon_id,
        )
        if profile is None:
            return None
        return replace(
            profile,
            moves=tuple(self._move(move) for move in profile.moves),
            abilities=tuple(self._ability(ability) for ability in profile.abilities),
        )

    def list_item_candidates(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> tuple[BattleInferenceItemProfile, ...]:
        """读取受控道具集合，并对账无道具和已实现道具产品。

        Args:
            ruleset_id: 稳定规则集标识。
            version_group_id: 当前受控道具边界适用的 version group。

        Returns:
            候选集合不变、整体执行覆盖已与 factory 对账的道具元组。
        """
        return tuple(
            self._item(candidate)
            for candidate in self.repository.list_item_candidates(
                ruleset_id=ruleset_id,
                version_group_id=version_group_id,
            )
        )

    def _move(self, move: BattleInferenceMoveProfile) -> BattleInferenceMoveProfile:
        """在具体招式产品与基础战斗字段均可执行时提升覆盖结论。

        factory 的 ``NO_EFFECT`` 只表示不需要附加 effect，不能证明变化威力攻击招式已经
        拥有可执行的基础伤害输入。此类招式必须继续保留 repository 的 unsupported 状态，
        直到 application/domain 提供明确的动态威力解析器。

        Args:
            move: 当前 version group 合法的招式 projection。

        Returns:
            合法字段完全不变、必要时只替换 capability 的招式 projection。
        """
        coverage = self.effect_factory.create_move_effect(
            move.effect_identifier
        ).coverage
        no_effect_is_complete = (
            move.effect_identifier is None
            and move.category is not MoveCategory.STATUS
            and move.power is not None
            and coverage.status is EffectCoverageStatus.NO_EFFECT
        )
        if coverage.status is EffectCoverageStatus.SUPPORTED or no_effect_is_complete:
            return replace(
                move,
                capability=_supported_capability(move.capability, coverage),
            )
        return move

    def _ability(
        self,
        ability: BattleInferenceAbilityProfile,
    ) -> BattleInferenceAbilityProfile:
        """在具体特性产品可执行时提升 repository 的保守覆盖结论。

        Args:
            ability: 当前 version group 合法的特性 projection。

        Returns:
            合法槽位与隐藏标记不变、必要时只替换 capability 的特性 projection。
        """
        coverage = self.effect_factory.create_ability_effect(
            ability.effect_identifier
        ).coverage
        if coverage.status is EffectCoverageStatus.SUPPORTED:
            return replace(
                ability,
                capability=_supported_capability(ability.capability, coverage),
            )
        return ability

    def _item(self, item: BattleInferenceItemProfile) -> BattleInferenceItemProfile:
        """在具体道具产品可执行时提升 repository 的保守覆盖结论。

        Args:
            item: 当前受控边界中的合法道具或显式无道具候选。

        Returns:
            候选身份不变、必要时只替换 capability 的道具 projection。
        """
        coverage = self.effect_factory.create_item_effect(item.effect_identifier).coverage
        if coverage.status is EffectCoverageStatus.SUPPORTED:
            status = MechanismSupportStatus.SUPPORTED
        elif coverage.status is EffectCoverageStatus.NO_EFFECT and item.effect_identifier is None:
            status = MechanismSupportStatus.NO_EFFECT
        else:
            return item
        return replace(
            item,
            capability=replace(
                item.capability,
                status=status,
                reason=_coverage_reason(item.capability.reason, coverage),
            ),
        )


def _supported_capability(
    capability: MechanismCapability,
    coverage: EffectCoverage,
) -> MechanismCapability:
    """把 factory 可执行结论合并进 repository capability。

    Args:
        capability: persistence/application repository 的保守覆盖记录。
        coverage: 当前具体 factory 产品的结构化覆盖记录。

    Returns:
        来源与稳定标识不变、状态提升为 supported 的 capability。
    """
    return replace(
        capability,
        status=MechanismSupportStatus.SUPPORTED,
        reason=_coverage_reason(capability.reason, coverage),
    )


def _coverage_reason(repository_reason: str, coverage: EffectCoverage) -> str:
    """生成同时保留读取判断和 factory 判断的规范化解释。

    Args:
        repository_reason: repository 对合法机制的原始保守原因。
        coverage: 具体规则集 factory 的执行覆盖结论。

    Returns:
        可直接进入配置覆盖报告的单行说明。
    """
    return f"{repository_reason} Factory reconciliation: {coverage.reason}"


__all__ = ["FactoryReconciledBattleInferenceRepository"]
