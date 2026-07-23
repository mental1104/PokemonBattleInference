from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.actions import (
    StandardLegalActionGenerator,
    StruggleAction,
    UseMoveAction,
)
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.effects import (
    ActionEffectContext,
    BattleEffectDispatcher,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
    PokemonChampionEffectFactory,
)
from pokeop.domain.battle.effects.adapters import ItemDamageEffectAdapter
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.item_effects import ChoiceBandEffect
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import BattleState, BattlerState
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.transitions import WeightedTransition
from pokeop.domain.battle.turn_resolver import TurnResolver
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import (
    BattleMoveFactory,
    BattlePokemonFactory,
    damage_context,
)


def _move_spec(
    move_id: int,
    *,
    name: str,
    category: MoveCategory = MoveCategory.PHYSICAL,
    max_pp: int = 5,
) -> MoveSpec:
    """构造讲究头带测试使用的稳定招式配置。

    Args:
        move_id: 当前测试规则集中的正整数招式 ID。
        name: 仅用于诊断展示的规范化招式名称。
        category: 招式的物理、特殊或变化分类。
        max_pp: 当前配置下的最大 PP，测试默认使用 5。

    Returns:
        可写入 ``PokemonSpec`` 的不可变 ``MoveSpec``。
    """
    return MoveSpec(
        move_id=move_id,
        move=BattleMove(
            name=name,
            type=Type.STEEL,
            category=category,
            power=0 if category is MoveCategory.STATUS else 60,
        ),
        max_pp=max_pp,
    )


def _battler(
    *,
    pokemon_id: int,
    name: str,
    item: DamageItem,
    moves: tuple[MoveSpec, ...],
    speed: int,
    consumed: bool = False,
) -> BattlerState:
    """构造满 HP、满 PP 的正式战斗方状态。

    Args:
        pokemon_id: 当前规则集中的稳定宝可梦 ID。
        name: 仅用于展示和诊断的规范化名称。
        item: 已类型化的携带道具。
        moves: 一到四个互不重复的招式配置。
        speed: 用于完整回合测试确定行动顺序的最终速度。
        consumed: 是否把道具标记为已经失效；True 时讲究头带不得新增锁招。

    Returns:
        满足 ``BattlerState`` 配置、槽位和道具状态不变量的新对象。
    """
    spec = PokemonSpec(
        pokemon_id=pokemon_id,
        name=name,
        level=50,
        types=(Type.STEEL,),
        stats=StatValues(
            hp=100,
            attack=100,
            defense=100,
            special_attack=100,
            special_defense=100,
            speed=speed,
        ),
        ability=DamageAbility.UNKNOWN,
        item=item,
        moves=moves,
    )
    return BattlerState(
        spec=spec,
        current_hp=spec.stats.hp,
        move_slots=tuple(
            MoveSlotState(
                move_id=move.move_id,
                current_pp=move.max_pp,
                max_pp=move.max_pp,
            )
            for move in moves
        ),
        item_consumed=consumed,
    )


def _battle_state(
    *,
    attacker_item: DamageItem = DamageItem.CHOICE_BAND,
    attacker_consumed: bool = False,
) -> BattleState:
    """构造包含两个攻击方招式和一个防守方招式的行动选择节点。

    Args:
        attacker_item: 攻击方携带道具，默认使用讲究头带。
        attacker_consumed: 是否把攻击方道具标记为已失效。

    Returns:
        攻击方速度更高、双方等级均为 50 的不可变 ``BattleState``。
    """
    attacker = _battler(
        pokemon_id=212,
        name="scizor",
        item=attacker_item,
        moves=(
            _move_spec(101, name="bullet-punch"),
            _move_spec(102, name="x-scissor"),
        ),
        speed=100,
        consumed=attacker_consumed,
    )
    defender = _battler(
        pokemon_id=700,
        name="sylveon",
        item=DamageItem.UNKNOWN,
        moves=(
            _move_spec(
                201,
                name="moonblast",
                category=MoveCategory.SPECIAL,
            ),
        ),
        speed=50,
    )
    return BattleState(
        attacker=attacker,
        defender=defender,
        rules=BattleInferenceRules(level=50),
    )


def _choice_band_dispatcher() -> BattleEffectDispatcher:
    """通过当前规则集具体工厂创建讲究头带 dispatcher。

    Returns:
        包含 no-op 招式/特性产品和讲究头带道具产品的类型化 dispatcher。
    """
    family = PokemonChampionEffectFactory().create_effect_family(
        move_identifier=None,
        ability_identifier=None,
        item_identifier=DamageItem.CHOICE_BAND,
    )
    return BattleEffectDispatcher.from_family(family)


def _deterministic_transition(state: BattleState) -> tuple[WeightedTransition, ...]:
    """把一个战斗节点包装成概率为一的选招阶段转移。

    Args:
        state: 需要进入 effect dispatcher 的不可变战斗节点。

    Returns:
        只包含输入节点、概率严格为一的转移元组。
    """
    return (WeightedTransition(probability=Fraction(1, 1), state=state),)


@dataclass(frozen=True, slots=True)
class FakeLockItemEffect:
    """测试用锁招道具效果，只依赖通用 ``with_choice_lock`` 状态更新入口。"""

    coverage: EffectCoverage

    def after_move_selected(
        self,
        context: ActionEffectContext,
        transitions: tuple[WeightedTransition, ...],
    ) -> tuple[WeightedTransition, ...]:
        """把首次普通招式选择写入通用锁招状态。

        Args:
            context: 当前战斗节点、行动方和已经选择的类型化行动。
            transitions: 已归一化的不可变战斗状态转移。

        Returns:
            普通招式被锁定后的新转移集合；非普通招式行动原样返回。
        """
        if not isinstance(context.action, UseMoveAction):
            return transitions
        return tuple(
            WeightedTransition(
                probability=transition.probability,
                state=transition.state.with_battler(
                    context.actor,
                    transition.state.battler(context.actor).with_choice_lock(
                        context.action.move_id
                    ),
                ),
                event_summary=transition.event_summary,
                source_key=transition.source_key,
            )
            for transition in transitions
        )


def test_factory_product_preserves_choice_band_damage_and_coverage_boundary() -> None:
    """验证当前规则集具体工厂仍以一个讲究头带产品同时承载既有伤害倍率和新增锁招语义。工厂返回的
    兼容 adapter 内部必须包装 ``ChoiceBandEffect``，覆盖结果应明确写出物攻倍率与 move-selection lock
    已支持，同时说明移除、无效化、交换和消耗联动仍延期。物理招式在 ``ATTACK_STAT`` 阶段应得到
    1.5 倍，特殊招式不得产生任何攻击能力修正，从而保护旧伤害测试和新机制覆盖说明不会互相漂移。
    """
    factory = PokemonChampionEffectFactory()
    item_effect = factory.create_item_effect(DamageItem.CHOICE_BAND)
    dispatcher = BattleEffectDispatcher.from_effects((item_effect,))
    attacker = BattlePokemonFactory.with_item(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        DamageItem.CHOICE_BAND,
    )
    defender = BattlePokemonFactory.sylveon("max_hp")

    physical = damage_context(
        attacker=attacker,
        defender=defender,
        move=BattleMoveFactory.bullet_punch(),
    )
    special = damage_context(
        attacker=attacker,
        defender=defender,
        move=BattleMoveFactory.special(),
    )

    from pokeop.domain.battle.effects import DamageEffectContext, DamageEffectStage

    physical_results = dispatcher.modify_damage(
        DamageEffectContext(physical, DamageEffectStage.ATTACK_STAT)
    )
    special_results = dispatcher.modify_damage(
        DamageEffectContext(special, DamageEffectStage.ATTACK_STAT)
    )

    assert isinstance(item_effect, ItemDamageEffectAdapter)
    assert isinstance(item_effect.wrapped, ChoiceBandEffect)
    assert item_effect.coverage.ruleset_id == factory.ruleset_id
    assert "move-selection lock" in item_effect.coverage.reason
    assert "deferred" in item_effect.coverage.reason
    assert tuple(result.multiplier for result in physical_results) == (1.5,)
    assert special_results == ()


def test_turn_resolver_locks_the_first_selected_move_without_identifier_branches() -> None:
    """验证讲究头带通过 ``AfterMoveSelectedEffect`` 接入完整回合，而不是让 ``TurnResolver`` 判断道具名。
    巨钳螳螂首次选择 101 后，回合应正常消耗该槽一格 PP，并在下一回合状态中保留 101 的锁招标记；
    祖先节点保持未锁定，新的 ``StateKey`` 与祖先不同。随后即使直接再次分发 102 的选招事件，既有锁招
    也不得被覆盖，证明“首次选择”语义稳定且锁定发生在选招后、命中和伤害结算之前的统一阶段中。
    """
    state = _battle_state()
    dispatcher = _choice_band_dispatcher()
    resolver = TurnResolver(effects=dispatcher)

    resolution = resolver.resolve(
        state,
        UseMoveAction(BattleSide.ATTACKER, 101),
        UseMoveAction(BattleSide.DEFENDER, 201),
    )

    next_state = resolution.transitions[0].state
    assert state.attacker.choice_lock_move_id is None
    assert next_state.attacker.choice_lock_move_id == 101
    assert next_state.attacker.move_slot(101).is_locked is True
    assert next_state.attacker.move_slot(101).current_pp == 4
    assert next_state.state_key != state.state_key

    attempted_relock = dispatcher.after_move_selected(
        ActionEffectContext(
            state=next_state,
            actor=BattleSide.ATTACKER,
            action=UseMoveAction(BattleSide.ATTACKER, 102),
        ),
        _deterministic_transition(next_state),
    )
    assert attempted_relock[0].state.attacker.choice_lock_move_id == 101


def test_depleted_choice_locked_move_forces_struggle_while_other_move_has_pp() -> None:
    """验证首次选招写入的锁招状态会被通用合法行动生成器持续执行。测试先经讲究头带 effect 锁定 101，
    再把该槽 PP 降到零，同时保持 102 仍有完整 PP；下一次生成合法行动时必须只返回 ``StruggleAction``，
    不能因为其他招式可用而绕过锁定。该场景同时确认 effect、状态字段、槽位标记和行动生成器形成闭环，
    且锁招后的 PP 边界不需要在讲究头带实现或回合主流程中新增第二套 identifier 判断。
    """
    state = _battle_state()
    dispatcher = _choice_band_dispatcher()
    locked = dispatcher.after_move_selected(
        ActionEffectContext(
            state=state,
            actor=BattleSide.ATTACKER,
            action=UseMoveAction(BattleSide.ATTACKER, 101),
        ),
        _deterministic_transition(state),
    )[0].state
    depleted_battler = locked.attacker.with_move_slot(
        locked.attacker.move_slot(101).with_current_pp(0)
    )
    depleted = locked.with_battler(BattleSide.ATTACKER, depleted_battler)

    actions = StandardLegalActionGenerator().generate(
        depleted,
        BattleSide.ATTACKER,
    )

    assert depleted.attacker.move_slot(102).current_pp == 5
    assert actions == (StruggleAction(BattleSide.ATTACKER),)


def test_consumed_choice_band_does_not_create_a_new_choice_lock() -> None:
    """验证道具已经失效时，讲究头带 effect 不会在首次选招后凭空建立新锁招。测试使用仍保留
    ``PokemonSpec.item=CHOICE_BAND`` 但 ``item_consumed=True`` 的正式状态，通过同一个工厂产品分发 101；
    返回节点必须与输入保持相同的锁招字段和槽位标记。该断言只固定“失效道具不新增状态”的首版边界，
    不实现或暗示拍落、戏法、魔法空间等具体清理时机，为后续显式调用 ``with_choice_lock(None)`` 预留空间。
    """
    state = _battle_state(attacker_consumed=True)
    dispatcher = _choice_band_dispatcher()

    result = dispatcher.after_move_selected(
        ActionEffectContext(
            state=state,
            actor=BattleSide.ATTACKER,
            action=UseMoveAction(BattleSide.ATTACKER, 101),
        ),
        _deterministic_transition(state),
    )

    assert result[0].state.attacker.choice_lock_move_id is None
    assert all(not slot.is_locked for slot in result[0].state.attacker.move_slots)
    assert result[0].state.state_key == state.state_key


def test_fake_lock_item_reuses_generic_legal_action_restriction() -> None:
    """验证合法行动层只理解通用 choice lock，而不认识讲究头带 identifier。测试注入一个独立的
    ``FakeLockItemEffect``，让携带讲究眼镜的攻击方锁定 102；dispatcher 无需修改即可写入正式状态，
    ``StandardLegalActionGenerator`` 随后只能生成 102。该测试不实现讲究眼镜原作效果，只用另一个允许
    持有锁招状态的配置证明新增锁招道具时可以复用相同状态和行动限制，而不修改回合执行器或生成器源码。
    """
    state = _battle_state(attacker_item=DamageItem.CHOICE_SPECS)
    fake_effect = FakeLockItemEffect(
        EffectCoverage(
            ruleset_id="fake-ruleset",
            source_kind=EffectSourceKind.ITEM,
            identifier="fake-lock-item",
            status=EffectCoverageStatus.SUPPORTED,
            reason="Test-only generic choice lock effect.",
        )
    )
    dispatcher = BattleEffectDispatcher.from_effects((fake_effect,))

    locked = dispatcher.after_move_selected(
        ActionEffectContext(
            state=state,
            actor=BattleSide.ATTACKER,
            action=UseMoveAction(BattleSide.ATTACKER, 102),
        ),
        _deterministic_transition(state),
    )[0].state
    actions = StandardLegalActionGenerator().generate(
        locked,
        BattleSide.ATTACKER,
    )

    assert locked.attacker.choice_lock_move_id == 102
    assert actions == (UseMoveAction(BattleSide.ATTACKER, 102),)
