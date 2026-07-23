from __future__ import annotations

from dataclasses import dataclass

from pokeop.domain.battle.actions import BattleAction, UseMoveAction
from pokeop.domain.battle.effects.protocols import (
    ActionEffectContext,
    ActionValidationResult,
    EffectCapabilityCoverage,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
    MoveEffectContext,
    VolatileStatusAttempt,
)
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.status.state import FlinchStatus


def _opponent_side(side: BattleSide) -> BattleSide:
    """返回 1v1 战斗中指定稳定侧的对手侧。

    Args:
        side: 当前行动所属的攻击方或防守方。

    Returns:
        与输入相反的另一稳定战斗侧。
    """
    return (
        BattleSide.DEFENDER
        if side is BattleSide.ATTACKER
        else BattleSide.ATTACKER
    )


def _matches_move_effect(
    context: ActionEffectContext[BattleAction] | MoveEffectContext[BattleAction],
    identifier: str,
) -> bool:
    """判断当前类型化行动是否绑定到指定具体招式 effect。

    Args:
        context: 当前战斗状态、行动方和类型化行动。
        identifier: 已规范化的具体招式 effect 标识。

    Returns:
        普通招式配置的 ``effect_identifier`` 与目标标识一致时返回 True；挣扎和
        Pass 等不引用普通招式配置的行动返回 False。
    """
    action = context.action
    if not isinstance(action, UseMoveAction):
        return False
    move_spec = context.state.battler(context.actor).spec.move_spec(action.move_id)
    return move_spec.effect_identifier == identifier


@dataclass(frozen=True, slots=True)
class IcePunchEffect:
    """声明冰冻拳复用通用物理伤害，并显式报告尚未支持的冰冻追加效果。"""

    coverage: EffectCoverage = EffectCoverage(
        ruleset_id="pokemon-champion",
        source_kind=EffectSourceKind.MOVE,
        identifier="ice_punch",
        status=EffectCoverageStatus.SUPPORTED,
        reason="Ice Punch uses the standard physical move execution pipeline.",
        capabilities=(
            EffectCapabilityCoverage(
                identifier="common_physical_damage",
                status=EffectCoverageStatus.SUPPORTED,
                reason=(
                    "Accuracy, PP, type effectiveness and damage use the common "
                    "pipeline."
                ),
            ),
            EffectCapabilityCoverage(
                identifier="freeze_secondary_effect",
                status=EffectCoverageStatus.UNSUPPORTED,
                reason="The non-volatile freeze status is outside issue #28.",
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class FakeOutEffect:
    """实现击掌奇袭的首次出场限制与伤害后畏缩请求。

    该 effect 只识别绑定到 ``fake_out`` 的招式配置，不检查宝可梦名称或目标特性。
    优先级、命中、PP 和直接伤害继续由通用执行器处理；目标特性通过
    ``PreventVolatileStatusEffect`` 对类型化畏缩请求作出裁决。
    """

    coverage: EffectCoverage = EffectCoverage(
        ruleset_id="pokemon-champion",
        source_kind=EffectSourceKind.MOVE,
        identifier="fake_out",
        status=EffectCoverageStatus.SUPPORTED,
        reason="Fake Out adds a first-turn gate and a typed flinch attempt.",
        capabilities=(
            EffectCapabilityCoverage(
                identifier="common_physical_damage",
                status=EffectCoverageStatus.SUPPORTED,
                reason="Accuracy, PP and direct damage use the common pipeline.",
            ),
            EffectCapabilityCoverage(
                identifier="first_turn_gate",
                status=EffectCoverageStatus.SUPPORTED,
                reason=(
                    "The move is allowed only while BattlerState.is_first_turn "
                    "is true."
                ),
            ),
            EffectCapabilityCoverage(
                identifier="priority_ordering",
                status=EffectCoverageStatus.SUPPORTED,
                reason=(
                    "MoveSpec priority is handled by the common action order "
                    "policy."
                ),
            ),
            EffectCapabilityCoverage(
                identifier="flinch_secondary_effect",
                status=EffectCoverageStatus.SUPPORTED,
                reason="A typed volatile-status attempt is emitted after damage.",
            ),
        ),
    )

    def validate_action(
        self,
        context: ActionEffectContext[BattleAction],
    ) -> ActionValidationResult:
        """只允许首次出场回合执行绑定到本 effect 的击掌奇袭。

        Args:
            context: 当前不可变战斗状态、行动方和待执行行动。

        Returns:
            其他招式返回允许；击掌奇袭在 ``is_first_turn`` 为 True 时允许，之后返回
            明确拒绝结果。首版通用 policy 将该拒绝视为执行前阻止，因此不会消耗 PP。
        """
        if not _matches_move_effect(context, self.coverage.identifier):
            return ActionValidationResult(
                allowed=True,
                source_identifier=self.coverage.identifier,
            )
        allowed = context.state.battler(context.actor).is_first_turn
        return ActionValidationResult(
            allowed=allowed,
            source_identifier=self.coverage.identifier,
            reason=(
                "Fake Out can only succeed on the user's first active turn."
                if not allowed
                else ""
            ),
        )

    def after_damage_volatile_status_attempts(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> tuple[VolatileStatusAttempt, ...]:
        """在击掌奇袭命中并完成伤害后发出一次畏缩施加请求。

        Args:
            context: 当前行动以及完成直接伤害后的不可变战斗状态。

        Returns:
            非击掌奇袭或目标已濒死时返回空元组；否则返回一条由 dispatcher 交给目标
            特性 effect 裁决的 ``FlinchStatus`` 请求，本方法不直接修改目标状态。
        """
        if not _matches_move_effect(context, self.coverage.identifier):
            return ()
        target = _opponent_side(context.actor)
        if context.state.battler(target).current_hp == 0:
            return ()
        return (
            VolatileStatusAttempt(
                source=context.actor,
                target=target,
                status=FlinchStatus(),
                source_identifier=self.coverage.identifier,
            ),
        )


@dataclass(frozen=True, slots=True)
class BrickBreakEffect:
    """声明劈瓦复用通用物理伤害，并显式报告尚未支持的屏障破坏。"""

    coverage: EffectCoverage = EffectCoverage(
        ruleset_id="pokemon-champion",
        source_kind=EffectSourceKind.MOVE,
        identifier="brick_break",
        status=EffectCoverageStatus.SUPPORTED,
        reason="Brick Break uses the standard physical move execution pipeline.",
        capabilities=(
            EffectCapabilityCoverage(
                identifier="common_physical_damage",
                status=EffectCoverageStatus.SUPPORTED,
                reason=(
                    "Accuracy, PP, type effectiveness and damage use the common "
                    "pipeline."
                ),
            ),
            EffectCapabilityCoverage(
                identifier="screen_break",
                status=EffectCoverageStatus.UNSUPPORTED,
                reason=(
                    "Reflect, Light Screen and Aurora Veil removal is outside "
                    "issue #28."
                ),
            ),
        ),
    )


__all__ = ["BrickBreakEffect", "FakeOutEffect", "IcePunchEffect"]
