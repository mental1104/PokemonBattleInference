from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pokeop.domain.battle.actions import BattleAction, UseMoveAction
from pokeop.domain.battle.context import DamageContext, MoveCategory
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifier_keys import ModifierKey
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.transitions import WeightedTransition

if TYPE_CHECKING:
    from pokeop.domain.battle.effects.protocols import (
        ActionEffectContext,
        DamageEffectContext,
        DamageEffectResult,
        EffectCoverage,
        TransitionSet,
    )

_CHOICE_BAND_COVERAGE_REASON = (
    "Choice Band attack multiplier and move-selection lock are supported; "
    "item removal, suppression, swap, and consumption interactions are deferred."
)


@dataclass(frozen=True)
class ItemEffectResult:
    """One concrete item multiplier returned to the damage modifier chain."""

    key: ModifierKey
    multiplier: float
    reason: str


class ItemDamageEffect(Protocol):
    """Interface for held items that participate in damage calculation."""

    @property
    def key(self) -> ModifierKey:
        """Return the modifier trace key emitted by this item effect."""
        ...

    def attack_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        """Return an attack-stat-stage multiplier, or None when inactive."""
        ...

    def defense_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        """Return a defense-stat-stage multiplier, or None when inactive."""
        ...

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> ItemEffectResult | None:
        """Return a final-damage-stage multiplier, or None when inactive."""
        ...


@runtime_checkable
class ItemCoverageDetailEffect(Protocol):
    """允许具体道具效果补充当前实现边界的覆盖说明。"""

    @property
    def coverage_reason(self) -> str:
        """返回当前已支持能力和明确延期交互组成的稳定说明。"""
        ...


def _damage_policy(context: DamageContext) -> DamagePolicy:
    if context.ruleset is None:
        return DamagePolicy.modern()
    return context.ruleset.damage_policy


class BaseItemDamageEffect:
    """No-op base class for damage-relevant held item implementations."""

    item = DamageItem.UNKNOWN

    @property
    def key(self) -> ModifierKey:
        return self.item.trace_key

    def attack_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        return None

    def defense_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        return None

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> ItemEffectResult | None:
        return None


class LifeOrbEffect(BaseItemDamageEffect):
    """Life Orb boosts direct damage dealt by the holder."""

    item = DamageItem.LIFE_ORB

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> ItemEffectResult | None:
        _ = type_effectiveness
        return ItemEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).life_orb_damage_multiplier,
            reason="Life Orb boosts direct damage.",
        )


def _default_choice_band_coverage() -> EffectCoverage:
    """创建兼容旧入口使用的讲究头带机制覆盖记录。

    Returns:
        同时声明物攻倍率和首次选招锁定已支持的覆盖信息。道具被移除、无效化、
        交换或消耗后的联动仍明确保留为后续能力，不在本效果中伪装成完整支持。
    """
    from pokeop.domain.battle.effects.protocols import (
        EffectCoverage,
        EffectCoverageStatus,
        EffectSourceKind,
    )

    return EffectCoverage(
        ruleset_id="damage-context-compatibility",
        source_kind=EffectSourceKind.ITEM,
        identifier=DamageItem.CHOICE_BAND.value,
        status=EffectCoverageStatus.SUPPORTED,
        reason=_CHOICE_BAND_COVERAGE_REASON,
    )


@dataclass(frozen=True, slots=True)
class ChoiceBandEffect(BaseItemDamageEffect):
    """实现讲究头带的物攻倍率与首次选招锁定语义。

    该效果同时兼容旧伤害责任链和新的类型化阶段 dispatcher。伤害阶段只处理物理
    招式的攻击能力倍率；选招阶段只为实际携带且尚未失效的讲究头带持有者写入
    ``choice_lock_move_id``，不遍历完整回合，也不处理道具移除、交换或无效化。

    Attributes:
        coverage: 当前规则集对讲究头带机制的覆盖说明，由具体工厂覆盖默认值。
    """

    coverage: EffectCoverage = field(default_factory=_default_choice_band_coverage)
    item = DamageItem.CHOICE_BAND

    @property
    def coverage_reason(self) -> str:
        """返回讲究头带当前已实现与明确延期的机制边界。"""
        return _CHOICE_BAND_COVERAGE_REASON

    def attack_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        """为物理招式返回规则集定义的攻击能力倍率。

        Args:
            context: 已由调用方选定讲究头带效果的单次伤害上下文。

        Returns:
            物理招式返回讲究头带倍率；特殊或变化招式返回 None，保持旧责任链兼容。
        """
        if context.move.category is not MoveCategory.PHYSICAL:
            return None
        return ItemEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).choice_item_attack_multiplier,
            reason="Choice Band boosts Attack for physical moves.",
        )

    def modify_damage(self, context: DamageEffectContext) -> DamageEffectResult:
        """把既有物攻倍率接入统一 ``ModifyDamageEffect`` 阶段协议。

        Args:
            context: 当前伤害上下文及显式伤害阶段。

        Returns:
            仅在 ``ATTACK_STAT`` 阶段且招式为物理分类时返回倍率应用；其他阶段返回
            显式 inactive，避免 dispatcher 传播可空结果。
        """
        from pokeop.domain.battle.effects.protocols import (
            DamageEffectApplication,
            DamageEffectResult,
            DamageEffectStage,
        )

        if context.stage is not DamageEffectStage.ATTACK_STAT:
            return DamageEffectResult.inactive()
        result = self.attack_stat_multiplier(context.damage_context)
        if result is None:
            return DamageEffectResult.inactive()
        return DamageEffectResult(
            DamageEffectApplication(
                key=result.key,
                multiplier=result.multiplier,
                reason=result.reason,
            )
        )

    def after_move_selected(
        self,
        context: ActionEffectContext[BattleAction],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """在持有者首次选择普通招式后写入稳定讲究锁招状态。

        Args:
            context: 当前战斗节点、选招方和已经通过合法行动生成器的类型化行动。
            transitions: 选招阶段当前已归一化的不可变状态分支。

        Returns:
            保留概率、事件摘要和来源键的新转移集合。普通招式首次选择时锁定该招式；
            挣扎、其他持有者、道具已失效或已经存在锁招时原样返回对应分支。
        """
        action = context.action
        if not isinstance(action, UseMoveAction) or action.side is not context.actor:
            # 挣扎不是普通招式槽选择，也不应成为之后可复用的锁招目标。
            return transitions

        updated: list[WeightedTransition] = []
        for transition in transitions:
            battler = transition.state.battler(context.actor)
            if (
                battler.spec.item is not DamageItem.CHOICE_BAND
                or battler.item_consumed
                or battler.choice_lock_move_id is not None
            ):
                # 已有锁招必须保持稳定；本轮也不猜测道具失效后的自动清理规则。
                updated.append(transition)
                continue

            locked_state = transition.state.with_battler(
                context.actor,
                battler.with_choice_lock(action.move_id),
            )
            updated.append(
                WeightedTransition(
                    probability=transition.probability,
                    state=locked_state,
                    event_summary=transition.event_summary,
                    source_key=transition.source_key,
                )
            )
        return tuple(updated)


class ChoiceSpecsEffect(BaseItemDamageEffect):
    """Choice Specs boosts the holder's Special Attack for special damage."""

    item = DamageItem.CHOICE_SPECS

    def attack_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        if context.move.category is not MoveCategory.SPECIAL:
            return None
        return ItemEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).choice_item_attack_multiplier,
            reason="Choice Specs boosts Special Attack for special moves.",
        )


class ExpertBeltEffect(BaseItemDamageEffect):
    """Expert Belt boosts super-effective direct damage."""

    item = DamageItem.EXPERT_BELT

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> ItemEffectResult | None:
        if type_effectiveness <= 1.0:
            return None
        return ItemEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).expert_belt_damage_multiplier,
            reason="Expert Belt boosts super-effective damage.",
        )


class EvioliteEffect(BaseItemDamageEffect):
    """Eviolite boosts Defense and Special Defense for Pokemon that can evolve."""

    item = DamageItem.EVIOLITE

    def defense_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        if not context.defender.can_evolve:
            return None
        return ItemEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).eviolite_defense_multiplier,
            reason="Eviolite boosts Defense and Special Defense when the holder can evolve.",
        )


def resolve_item_effect(item: DamageItem | str | None) -> ItemDamageEffect:
    """Resolve a held-item effect; unknown items map to a deliberate no-op effect."""
    return DamageItem.from_identifier(item).create_effect()


__all__ = [
    "BaseItemDamageEffect",
    "ChoiceBandEffect",
    "ChoiceSpecsEffect",
    "DamageItem",
    "EvioliteEffect",
    "ExpertBeltEffect",
    "ItemCoverageDetailEffect",
    "ItemDamageEffect",
    "ItemEffectResult",
    "LifeOrbEffect",
    "resolve_item_effect",
]
