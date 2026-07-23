from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import DamageContext
from pokeop.domain.battle.modifier_keys import ModifierKey
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.models.types import Type

if TYPE_CHECKING:
    from pokeop.domain.battle.effects.protocols import (
        DamageEffectContext,
        DamageEffectResult,
        StatusPreventionResult,
        VolatileStatusEffectContext,
    )


@dataclass(frozen=True)
class AbilityEffectResult:
    """One concrete ability multiplier returned to the damage modifier chain."""

    key: ModifierKey
    multiplier: float
    reason: str


class AbilityDamageEffect(Protocol):
    """Interface for ability effects that participate in damage calculation."""

    @property
    def key(self) -> ModifierKey:
        """Return the modifier trace key emitted by this ability effect."""
        ...

    def base_power_multiplier(
        self,
        context: DamageContext,
    ) -> AbilityEffectResult | None:
        """Return a base-power-stage multiplier, or None when inactive."""
        ...

    def stab_multiplier(self, context: DamageContext) -> AbilityEffectResult | None:
        """Return the final STAB multiplier, or None when this ability is inactive."""
        ...

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        """Return a final-damage-stage multiplier, or None when inactive."""
        ...

    def critical_hit_multiplier(
        self,
        context: DamageContext,
        base_multiplier: float,
    ) -> AbilityEffectResult | None:
        """Return the final critical-hit multiplier, or None when inactive."""
        ...


def _damage_policy(context: DamageContext) -> DamagePolicy:
    if context.ruleset is None:
        return DamagePolicy.modern()
    return context.ruleset.damage_policy


class BaseAbilityDamageEffect:
    """No-op base class for damage-relevant ability implementations."""

    ability = DamageAbility.UNKNOWN

    @property
    def key(self) -> ModifierKey:
        return self.ability.trace_key

    def base_power_multiplier(
        self,
        context: DamageContext,
    ) -> AbilityEffectResult | None:
        return None

    def stab_multiplier(self, context: DamageContext) -> AbilityEffectResult | None:
        return None

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        return None

    def critical_hit_multiplier(
        self,
        context: DamageContext,
        base_multiplier: float,
    ) -> AbilityEffectResult | None:
        return None


class TechnicianEffect(BaseAbilityDamageEffect):
    """Technician boosts moves with base power 60 or lower."""

    ability = DamageAbility.TECHNICIAN

    def base_power_multiplier(
        self,
        context: DamageContext,
    ) -> AbilityEffectResult | None:
        policy = _damage_policy(context)
        if context.move.power > policy.technician_base_power_threshold:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=policy.technician_base_power_multiplier,
            reason="Technician boosts moves with base power 60 or lower.",
        )


class AdaptabilityEffect(BaseAbilityDamageEffect):
    """Adaptability raises same-type attack bonus from 1.5 to 2.0."""

    ability = DamageAbility.ADAPTABILITY

    def stab_multiplier(self, context: DamageContext) -> AbilityEffectResult | None:
        if context.move.type not in context.attacker.types:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).adaptability_stab_multiplier,
            reason="Adaptability raises STAB to 2.0.",
        )


class ThickFatEffect(BaseAbilityDamageEffect):
    """Thick Fat halves incoming Fire- and Ice-type direct damage."""

    ability = DamageAbility.THICK_FAT

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        _ = type_effectiveness
        if context.move.type not in (Type.FIRE, Type.ICE):
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).thick_fat_damage_multiplier,
            reason="Thick Fat halves incoming Fire- and Ice-type damage.",
        )


class FilterEffect(BaseAbilityDamageEffect):
    """Filter reduces super-effective direct damage."""

    ability = DamageAbility.FILTER

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        if type_effectiveness <= 1.0:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).filter_damage_multiplier,
            reason="Filter reduces super-effective damage.",
        )


class SolidRockEffect(FilterEffect):
    """Solid Rock shares Filter's direct-damage behavior."""

    ability = DamageAbility.SOLID_ROCK

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        result = super().final_damage_multiplier(context, type_effectiveness)
        if result is None:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=result.multiplier,
            reason="Solid Rock reduces super-effective damage.",
        )


class SniperEffect(BaseAbilityDamageEffect):
    """Sniper increases the critical-hit damage multiplier by 50%."""

    ability = DamageAbility.SNIPER

    def critical_hit_multiplier(
        self,
        context: DamageContext,
        base_multiplier: float,
    ) -> AbilityEffectResult | None:
        return AbilityEffectResult(
            key=self.key,
            multiplier=(
                base_multiplier * _damage_policy(context).sniper_critical_multiplier
            ),
            reason="Sniper increases critical-hit damage by 50%.",
        )


class MultiscaleEffect(BaseAbilityDamageEffect):
    """在持有者满 HP 时降低本次直接伤害。

    该 domain effect 只负责动态伤害判断，不修改防御或特防。旧 ``DamageContext``
    不包含当前 HP，因此它通过 adapter 识别的 ``modify_battle_damage`` 窄协议参与
    多回合执行，并从 ``DamagePolicy`` 读取倍率。
    """

    ability = DamageAbility.MULTISCALE

    def modify_battle_damage(
        self,
        context: "DamageEffectContext",
    ) -> "DamageEffectResult":
        """在最终直接伤害阶段为满 HP 的持有者返回规则集倍率。

        Args:
            context: 当前伤害阶段、旧伤害快照以及可选的实时战斗状态。只有完整提供
                ``battle_state``、``actor`` 和 ``target`` 时才可能生效。

        Returns:
            目标持有多重鳞片且当前 HP 等于最大 HP 时返回倍率应用；非最终伤害阶段、
            属性无效、非直接伤害、缺少动态状态或已掉血时返回 explicit inactive。
        """
        from pokeop.domain.battle.effects.protocols import (
            DamageEffectApplication,
            DamageEffectResult,
            DamageEffectStage,
        )

        if (
            context.stage is not DamageEffectStage.FINAL_DAMAGE
            or not context.is_direct_damage
            or context.type_effectiveness <= 0
            or context.battle_state is None
            or context.target is None
        ):
            # 缺少有效直接伤害或实时目标时不能猜测 HP，保持显式 no-op。
            return DamageEffectResult.inactive()

        target = context.battle_state.battler(context.target)
        if (
            target.spec.ability is not self.ability
            or target.current_hp != target.spec.stats.hp
        ):
            # 多重鳞片只检查本次命中前的满 HP 边界；掉血后不再参与后续伤害。
            return DamageEffectResult.inactive()

        return DamageEffectResult(
            DamageEffectApplication(
                key=self.key,
                multiplier=_damage_policy(
                    context.damage_context
                ).multiscale_damage_multiplier,
                reason=(
                    "Multiscale reduces direct damage while the target is at full HP."
                ),
            )
        )


class InnerFocusEffect(BaseAbilityDamageEffect):
    """阻止持有者获得畏缩临时状态。

    当前垂直切片只实现畏缩免疫。现代规则中的威吓免疫依赖尚未建立的能力等级
    下降来源协议，因此通过结构化 partial coverage 明确延期，而不是伪装为完整支持。
    """

    ability = DamageAbility.INNER_FOCUS
    unsupported_aspects = ("intimidate_immunity",)
    partial_support_reason = (
        "Flinch immunity is supported; modern Intimidate immunity is not implemented."
    )

    def prevent_volatile_status(
        self,
        context: "VolatileStatusEffectContext",
    ) -> "StatusPreventionResult":
        """仅阻止目标为精神力持有者时的 ``FLINCH`` 状态写入。

        Args:
            context: 当前不可变战斗状态、状态来源、目标方和规范化临时状态标识。

        Returns:
            目标持有精神力且待写入状态为 ``flinch`` 时返回阻止；其他临时状态和
            非精神力目标返回显式不阻止，伤害与其他行动阶段不受影响。
        """
        from pokeop.domain.battle.effects.protocols import StatusPreventionResult

        target = context.state.battler(context.target)
        prevented = (
            target.spec.ability is self.ability
            and context.status_identifier == VolatileStatusKind.FLINCH.value
        )
        return StatusPreventionResult(
            prevented=prevented,
            source_identifier=self.ability.value,
            reason="Inner Focus prevents flinch." if prevented else "",
        )


def resolve_ability_effect(
    ability: DamageAbility | str | None,
) -> AbilityDamageEffect:
    """Resolve a known ability effect; unknown abilities are deliberate no-ops."""
    return DamageAbility.from_identifier(ability).create_effect()


__all__ = [
    "AbilityDamageEffect",
    "AbilityEffectResult",
    "DamageAbility",
    "InnerFocusEffect",
    "MultiscaleEffect",
    "resolve_ability_effect",
]
