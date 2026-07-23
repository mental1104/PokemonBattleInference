from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.actions import BattleAction
from pokeop.domain.battle.ability_effects import (
    InnerFocusEffect,
    MultiscaleEffect,
)
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.effects import (
    AbilityDamageEffectAdapter,
    BattleEffect,
    BattleEffectDispatcher,
    BattleSide,
    DamageEffectContext,
    DamageEffectStage,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
    MoveEffectContext,
    PokemonChampionEffectFactory,
    TransitionSet,
    VolatileStatusEffectContext,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifier_keys import ModifierKey
from pokeop.domain.battle.move_execution import (
    StandardMoveDamagePolicy,
    StandardMoveTurnResolver,
)
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import BattleState, BattlerState
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.battle.status.state import FlinchStatus
from pokeop.domain.battle.transitions import WeightedTransition
from pokeop.domain.models.types import Type


def _move(move_id: int, *, power: int = 40) -> MoveSpec:
    """构造确定命中的普通物理招式。

    Args:
        move_id: 测试内唯一的招式 ID。
        power: 参与现有伤害公式的基础威力，默认 40。

    Returns:
        具有 10 PP、100% 命中率和一般属性的 ``MoveSpec``。
    """
    return MoveSpec(
        move_id=move_id,
        move=BattleMove(
            name=f"move-{move_id}",
            type=Type.NORMAL,
            category=MoveCategory.PHYSICAL,
            power=power,
        ),
        max_pp=10,
        accuracy=100,
    )


def _battler(
    *,
    pokemon_id: int,
    move_id: int,
    speed: int,
    ability: DamageAbility,
    current_hp: int = 100,
    power: int = 40,
) -> BattlerState:
    """构造满 PP、可指定当前 HP 与特性的正式战斗方状态。

    Args:
        pokemon_id: 测试宝可梦的稳定 ID。
        move_id: 唯一配置招式的 ID。
        speed: 用于确定先后手的最终速度值。
        ability: 当前战斗方持有的 domain 特性枚举。
        current_hp: 当前 HP，最大 HP 固定为 100。
        power: 唯一配置招式的基础威力。

    Returns:
        能直接放入 ``BattleState`` 的不可变 ``BattlerState``。
    """
    move = _move(move_id, power=power)
    return BattlerState(
        spec=PokemonSpec(
            pokemon_id=pokemon_id,
            name=f"pokemon-{pokemon_id}",
            level=50,
            types=(Type.NORMAL,),
            stats=StatValues(
                hp=100,
                attack=100,
                defense=100,
                special_attack=100,
                special_defense=100,
                speed=speed,
            ),
            ability=ability,
            item=DamageItem.UNKNOWN,
            moves=(move,),
        ),
        current_hp=current_hp,
        move_slots=(
            MoveSlotState(
                move_id=move_id,
                current_pp=move.max_pp,
                max_pp=move.max_pp,
            ),
        ),
    )


def _state(
    *,
    defender_ability: DamageAbility,
    defender_hp: int = 100,
    damage_policy: DamagePolicy | None = None,
) -> BattleState:
    """构造攻击方确定先手的 1v1 测试状态。

    Args:
        defender_ability: 防守方持有的待测特性。
        defender_hp: 防守方当前 HP，最大 HP 固定为 100。
        damage_policy: 可选规则 policy；省略时使用唯一随机倍率 1.0 消除随机分支。

    Returns:
        双方各有一个普通物理招式、攻击方速度更高的 ``BattleState``。
    """
    return BattleState(
        attacker=_battler(
            pokemon_id=1,
            move_id=101,
            speed=120,
            ability=DamageAbility.UNKNOWN,
        ),
        defender=_battler(
            pokemon_id=2,
            move_id=202,
            speed=80,
            ability=defender_ability,
            current_hp=defender_hp,
        ),
        rules=BattleInferenceRules(
            level=50,
            damage_policy=damage_policy
            or DamagePolicy(random_damage_multipliers=(1.0,)),
        ),
    )


def _ability_effect(ability: DamageAbility) -> AbilityDamageEffectAdapter:
    """通过当前规则集具体工厂创建可分发的特性 adapter。

    Args:
        ability: 需要创建真实 effect 的已识别特性枚举。

    Returns:
        ``PokemonChampionEffectFactory`` 创建的 ``AbilityDamageEffectAdapter``。
    """
    effect = PokemonChampionEffectFactory().create_ability_effect(ability)
    assert isinstance(effect, AbilityDamageEffectAdapter)
    return effect


def _resolve_one_turn(
    state: BattleState,
    *,
    effects: tuple[BattleEffect, ...],
) -> BattleState:
    """选择双方首个合法行动并推进一个确定性完整回合。

    Args:
        state: 处于行动选择阶段的测试状态。
        effects: 需要接入完整回合 dispatcher 的特性或测试 effect。

    Returns:
        唯一概率为 1 的完整回合后继状态。
    """
    resolver = StandardMoveTurnResolver(effects=effects)
    attacker_action = resolver.legal_actions(state, BattleSide.ATTACKER)[0]
    defender_action = resolver.legal_actions(state, BattleSide.DEFENDER)[0]
    resolution = resolver.resolve(state, attacker_action, defender_action)

    assert len(resolution.transitions) == 1
    assert resolution.transitions[0].probability == Fraction(1, 1)
    return resolution.transitions[0].state


@dataclass(frozen=True, slots=True)
class PreventableFlinchAfterDamage:
    """通过通用阻止协议尝试写入畏缩的测试 effect。

    Attributes:
        source_side: 只有该侧行动完成伤害后才尝试施加畏缩。
        status_dispatcher: 负责判断目标特性是否阻止 ``FLINCH`` 的独立 dispatcher。
        coverage: 供完整回合 dispatcher 识别的测试机制覆盖记录。
    """

    source_side: BattleSide
    status_dispatcher: BattleEffectDispatcher[BattleAction]
    coverage: EffectCoverage = EffectCoverage(
        ruleset_id="pokemon-champion",
        source_kind=EffectSourceKind.MOVE,
        identifier="test-preventable-flinch",
        status=EffectCoverageStatus.SUPPORTED,
        reason="Test-only flinch source using the generic prevention protocol.",
    )

    def after_damage(
        self,
        context: MoveEffectContext[BattleAction],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """为指定来源行动尝试施加畏缩，并保持原概率与事件摘要。

        Args:
            context: 当前伤害结算后的行动方和行动信息。
            transitions: 伤害阶段已经产生并归一化的状态转移集合。

        Returns:
            状态被阻止时原样保留分支；否则为目标写入 ``FlinchStatus`` 的新集合。
        """
        if context.actor is not self.source_side:
            # 非指定来源不参与本测试机制，避免后手反向施加畏缩。
            return transitions

        target_side = (
            BattleSide.DEFENDER
            if context.actor is BattleSide.ATTACKER
            else BattleSide.ATTACKER
        )
        results: list[WeightedTransition[BattleState]] = []
        for transition in transitions:
            prevention = self.status_dispatcher.prevent_volatile_status(
                VolatileStatusEffectContext(
                    state=transition.state,
                    source=context.actor,
                    target=target_side,
                    status_identifier=VolatileStatusKind.FLINCH.value,
                )
            )
            if prevention.prevented:
                # 阻止结果只跳过状态写入，不回滚已结算的伤害或 PP。
                results.append(transition)
                continue

            target = transition.state.battler(target_side)
            results.append(
                WeightedTransition(
                    probability=transition.probability,
                    state=transition.state.with_battler(
                        target_side,
                        target.with_status(
                            target.status.add_volatile(FlinchStatus())
                        ),
                    ),
                    event_summary=transition.event_summary,
                    source_key=transition.source_key,
                )
            )
        return tuple(results)


def test_factory_creates_multiscale_and_partial_inner_focus_effects() -> None:
    """具体工厂应创建两项真实特性 effect，并结构化暴露精神力缺口。"""
    multiscale = _ability_effect(DamageAbility.MULTISCALE)
    inner_focus = _ability_effect(DamageAbility.INNER_FOCUS)

    assert isinstance(multiscale.wrapped, MultiscaleEffect)
    assert multiscale.coverage.status is EffectCoverageStatus.SUPPORTED
    assert isinstance(inner_focus.wrapped, InnerFocusEffect)
    assert inner_focus.coverage.status is EffectCoverageStatus.PARTIAL
    assert inner_focus.coverage.unsupported_aspects == (
        "intimidate_immunity",
    )


def test_multiscale_uses_policy_multiplier_only_at_full_hp() -> None:
    """多重鳞片只在满 HP 的最终直接伤害阶段返回 policy 倍率。"""
    policy = DamagePolicy(
        multiscale_damage_multiplier=0.4,
        random_damage_multipliers=(1.0,),
    )
    full_hp_state = _state(
        defender_ability=DamageAbility.MULTISCALE,
        damage_policy=policy,
    )
    effect = _ability_effect(DamageAbility.MULTISCALE)
    dispatcher = BattleEffectDispatcher[BattleAction].from_effects((effect,))
    damage_context = StandardMoveDamagePolicy._damage_context(
        state=full_hp_state,
        actor=BattleSide.ATTACKER,
        move_id=101,
    )

    full_hp_applications = dispatcher.modify_damage(
        DamageEffectContext(
            damage_context=damage_context,
            stage=DamageEffectStage.FINAL_DAMAGE,
            type_effectiveness=1.0,
            battle_state=full_hp_state,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
        )
    )
    damaged_state = _state(
        defender_ability=DamageAbility.MULTISCALE,
        defender_hp=99,
        damage_policy=policy,
    )
    damaged_applications = dispatcher.modify_damage(
        DamageEffectContext(
            damage_context=damage_context,
            stage=DamageEffectStage.FINAL_DAMAGE,
            type_effectiveness=1.0,
            battle_state=damaged_state,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
        )
    )
    defense_stage = dispatcher.modify_damage(
        DamageEffectContext(
            damage_context=damage_context,
            stage=DamageEffectStage.DEFENSE_STAT,
            battle_state=full_hp_state,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
        )
    )

    assert tuple(item.key for item in full_hp_applications) == (
        ModifierKey.ABILITY_MULTISCALE,
    )
    assert tuple(item.multiplier for item in full_hp_applications) == (0.4,)
    assert damaged_applications == ()
    assert defense_stage == ()


def test_dynamic_damage_dispatch_ignores_legacy_snapshot_effects() -> None:
    """实时伤害阶段不应把无归属的旧 Filter adapter 错套到当前目标。"""
    state = _state(defender_ability=DamageAbility.UNKNOWN)
    filter_effect = _ability_effect(DamageAbility.FILTER)
    dispatcher = BattleEffectDispatcher[BattleAction].from_effects((filter_effect,))
    damage_context = StandardMoveDamagePolicy._damage_context(
        state=state,
        actor=BattleSide.ATTACKER,
        move_id=101,
    )

    dynamic = dispatcher.modify_damage(
        DamageEffectContext(
            damage_context=damage_context,
            stage=DamageEffectStage.FINAL_DAMAGE,
            type_effectiveness=2.0,
            battle_state=state,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
        )
    )
    legacy = dispatcher.modify_damage(
        DamageEffectContext(
            damage_context=damage_context,
            stage=DamageEffectStage.FINAL_DAMAGE,
            type_effectiveness=2.0,
        )
    )

    assert dynamic == ()
    assert tuple(item.key for item in legacy) == (ModifierKey.ABILITY_FILTER,)


def test_multiscale_reduces_first_hit_but_not_later_hits() -> None:
    """完整回合中首个满 HP 命中减伤，掉血后的下一击恢复普通伤害。"""
    policy = DamagePolicy(random_damage_multipliers=(1.0,))
    baseline_state = _state(
        defender_ability=DamageAbility.UNKNOWN,
        damage_policy=policy,
    )
    baseline_after = _resolve_one_turn(baseline_state, effects=())
    normal_damage = (
        baseline_state.defender.current_hp
        - baseline_after.defender.current_hp
    )

    multiscale_effect = _ability_effect(DamageAbility.MULTISCALE)
    multiscale_state = _state(
        defender_ability=DamageAbility.MULTISCALE,
        damage_policy=policy,
    )
    first_after = _resolve_one_turn(
        multiscale_state,
        effects=(multiscale_effect,),
    )
    first_damage = (
        multiscale_state.defender.current_hp
        - first_after.defender.current_hp
    )
    second_after = _resolve_one_turn(
        first_after,
        effects=(multiscale_effect,),
    )
    second_damage = first_after.defender.current_hp - second_after.defender.current_hp

    assert first_damage == max(
        1,
        int(normal_damage * policy.multiscale_damage_multiplier),
    )
    assert second_damage == normal_damage


def test_inner_focus_blocks_only_flinch_and_reports_partial_support() -> None:
    """精神力应阻止 FLINCH，但不伪装为已支持威吓免疫。"""
    state = _state(defender_ability=DamageAbility.INNER_FOCUS)
    effect = _ability_effect(DamageAbility.INNER_FOCUS)
    dispatcher = BattleEffectDispatcher[BattleAction].from_effects((effect,))

    flinch = dispatcher.prevent_volatile_status(
        VolatileStatusEffectContext(
            state=state,
            source=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
            status_identifier=VolatileStatusKind.FLINCH.value,
        )
    )
    confusion = dispatcher.prevent_volatile_status(
        VolatileStatusEffectContext(
            state=state,
            source=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
            status_identifier=VolatileStatusKind.CONFUSION.value,
        )
    )

    assert flinch.prevented
    assert not confusion.prevented
    assert effect.coverage.status is EffectCoverageStatus.PARTIAL
    assert effect.coverage.unsupported_aspects == ("intimidate_immunity",)


def test_inner_focus_allows_damage_pp_and_other_move_execution() -> None:
    """fake 畏缩来源无需识别精神力，完整回合仍应让目标受伤并正常行动。"""
    state = _state(defender_ability=DamageAbility.INNER_FOCUS)
    inner_focus = _ability_effect(DamageAbility.INNER_FOCUS)
    status_dispatcher = BattleEffectDispatcher[BattleAction].from_effects(
        (inner_focus,)
    )
    flinch_source = PreventableFlinchAfterDamage(
        source_side=BattleSide.ATTACKER,
        status_dispatcher=status_dispatcher,
    )

    after = _resolve_one_turn(
        state,
        effects=(inner_focus, flinch_source),
    )

    assert after.defender.current_hp < state.defender.current_hp
    assert after.attacker.current_hp < state.attacker.current_hp
    assert after.attacker.move_slot(101).current_pp == 9
    assert after.defender.move_slot(202).current_pp == 9
    assert not after.defender.status.has_volatile(VolatileStatusKind.FLINCH)


def test_same_fake_flinch_source_blocks_target_without_inner_focus() -> None:
    """同一个 fake 来源在无精神力时应成功畏缩并阻止后手消耗 PP。"""
    state = _state(defender_ability=DamageAbility.UNKNOWN)
    empty_dispatcher = BattleEffectDispatcher[BattleAction].from_effects(())
    flinch_source = PreventableFlinchAfterDamage(
        source_side=BattleSide.ATTACKER,
        status_dispatcher=empty_dispatcher,
    )

    after = _resolve_one_turn(state, effects=(flinch_source,))

    assert after.attacker.move_slot(101).current_pp == 9
    assert after.defender.move_slot(202).current_pp == 10
