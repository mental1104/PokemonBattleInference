from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.actions import BattleAction
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.effects import (
    BattleEffect,
    BattleEffectDispatcher,
    BrickBreakEffect,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
    FakeOutEffect,
    IcePunchEffect,
    PokemonChampionEffectFactory,
    StatusPreventionResult,
    VolatileStatusEffectContext,
)
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_execution import StandardMoveTurnResolver
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import BattlePhase, BattleState, BattlerState
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.battle.status.state import CombatantStatus, FlinchStatus
from pokeop.domain.battle.transitions import WeightedTransition
from pokeop.domain.models.types import Type


def _move_spec(
    *,
    move_id: int,
    name: str,
    move_type: Type,
    power: int,
    priority: int = 0,
    accuracy: int | None = 100,
    max_pp: int = 10,
    effect_identifier: str | None = None,
) -> MoveSpec:
    """构造具体招式效果测试使用的不可变招式配置。

    Args:
        move_id: 规则集中的稳定正整数招式 ID。
        name: 仅供伤害 trace 展示的规范化招式名称。
        move_type: 通用伤害链读取的招式属性。
        power: 物理招式使用的正整数基础威力。
        priority: 通用行动顺序策略读取的招式优先级。
        accuracy: 百分制命中率；None 表示跳过普通命中判定。
        max_pp: 招式槽的最大 PP 和初始 PP。
        effect_identifier: 绑定到具体 effect 的机制标识；None 表示仅走通用流程。

    Returns:
        可直接配置到 ``PokemonSpec`` 的 ``MoveSpec``。
    """
    return MoveSpec(
        move_id=move_id,
        move=BattleMove(
            name=name,
            type=move_type,
            category=MoveCategory.PHYSICAL,
            power=power,
        ),
        max_pp=max_pp,
        priority=priority,
        accuracy=accuracy,
        effect_identifier=effect_identifier,
    )


def _battler(
    *,
    pokemon_id: int,
    name: str,
    types: tuple[Type, ...],
    stats: StatValues,
    move: MoveSpec,
    ability: DamageAbility = DamageAbility.UNKNOWN,
    is_first_turn: bool = True,
    flinched: bool = False,
) -> BattlerState:
    """构造只携带一个招式槽的正式战斗方状态。

    Args:
        pokemon_id: 当前规则集中的稳定宝可梦 ID。
        name: 用于 trace 的规范化宝可梦名称。
        types: 一到两个真实战斗属性。
        stats: 已经计算完成的六项实际能力值。
        move: 当前测试唯一配置的招式。
        ability: 当前宝可梦配置的伤害特性枚举；fake 阻止 effect 由 resolver 额外注入。
        is_first_turn: 是否仍处于本次出场后的首次行动回合。
        flinched: 是否在回合开始前预置畏缩，用于隔离目标行动对伤害断言的干扰。

    Returns:
        HP、PP、状态和首次出场标记完整的不可变 ``BattlerState``。
    """
    status = (
        CombatantStatus(volatile=frozenset((FlinchStatus(),)))
        if flinched
        else CombatantStatus()
    )
    spec = PokemonSpec(
        pokemon_id=pokemon_id,
        name=name,
        level=50,
        types=types,
        stats=stats,
        ability=ability,
        item=DamageItem.UNKNOWN,
        moves=(move,),
    )
    return BattlerState(
        spec=spec,
        current_hp=stats.hp,
        move_slots=(
            MoveSlotState(
                move_id=move.move_id,
                current_pp=move.max_pp,
                max_pp=move.max_pp,
            ),
        ),
        status=status,
        is_first_turn=is_first_turn,
    )


def _battle_state(
    *,
    attacker_move: MoveSpec,
    defender_move: MoveSpec,
    attacker_name: str = "Dragonite",
    attacker_types: tuple[Type, ...] = (Type.DRAGON, Type.FLYING),
    attacker_stats: StatValues = StatValues(200, 186, 115, 120, 120, 110),
    defender_name: str = "Weavile",
    defender_types: tuple[Type, ...] = (Type.DARK, Type.ICE),
    defender_stats: StatValues = StatValues(170, 172, 85, 60, 105, 180),
    attacker_first_turn: bool = True,
    defender_first_turn: bool = True,
    defender_flinched: bool = False,
    turn_number: int = 1,
) -> BattleState:
    """构造 issue #28 三项招式共享的 1v1 行动选择节点。

    Args:
        attacker_move: 攻击方唯一配置的招式。
        defender_move: 防守方唯一配置的招式。
        attacker_name: 攻击方展示名称。
        attacker_types: 攻击方真实属性组合。
        attacker_stats: 攻击方最终能力值。
        defender_name: 防守方展示名称。
        defender_types: 防守方真实属性组合。
        defender_stats: 防守方最终能力值。
        attacker_first_turn: 攻击方是否满足击掌奇袭首次出场条件。
        defender_first_turn: 防守方是否仍处于首次出场回合。
        defender_flinched: 是否预置畏缩以隔离防守方行动。
        turn_number: 当前展示和事件标识使用的正整数回合号。

    Returns:
        可交给 ``StandardMoveTurnResolver`` 推进的正式 ``BattleState``。
    """
    return BattleState(
        attacker=_battler(
            pokemon_id=149,
            name=attacker_name,
            types=attacker_types,
            stats=attacker_stats,
            move=attacker_move,
            is_first_turn=attacker_first_turn,
        ),
        defender=_battler(
            pokemon_id=461,
            name=defender_name,
            types=defender_types,
            stats=defender_stats,
            move=defender_move,
            is_first_turn=defender_first_turn,
            flinched=defender_flinched,
        ),
        rules=BattleInferenceRules(level=50),
        turn_number=turn_number,
    )


def _resolve(
    state: BattleState,
    *effects: BattleEffect,
) -> tuple[WeightedTransition[BattleState], ...]:
    """使用双方唯一合法行动和指定 effect 推进一个完整回合。

    Args:
        state: 处于行动选择阶段的正式测试状态。
        effects: 具体招式 effect 以及可选的 fake 特性 effect。

    Returns:
        标准执行器产生并按状态键归并后的完整概率转移集合。
    """
    resolver = StandardMoveTurnResolver(effects=tuple(effects))
    attacker_action = resolver.legal_actions(state, BattleSide.ATTACKER)[0]
    defender_action = resolver.legal_actions(state, BattleSide.DEFENDER)[0]
    return resolver.resolve(
        state,
        attacker_action,
        defender_action,
    ).transitions


@dataclass(frozen=True, slots=True)
class PreventDefenderFlinchEffect:
    """测试用目标特性 effect，只阻止防守方接收类型化畏缩请求。"""

    coverage: EffectCoverage = EffectCoverage(
        ruleset_id="pokemon-champion",
        source_kind=EffectSourceKind.ABILITY,
        identifier="test_prevent_flinch",
        status=EffectCoverageStatus.SUPPORTED,
        reason="Test-only typed flinch prevention effect.",
    )

    def prevent_volatile_status(
        self,
        context: VolatileStatusEffectContext,
    ) -> StatusPreventionResult:
        """根据目标侧和状态标识裁决畏缩请求，不读取具体招式或特性名称。

        Args:
            context: dispatcher 提供的当前状态、请求来源、目标和临时状态标识。

        Returns:
            防守方接收 flinch 时返回阻止；其他请求返回不阻止，便于证明击掌奇袭只发出
            类型化事件，目标能力通过统一协议拦截，而不是由招式 effect 检查能力字符串。
        """
        prevented = (
            context.target is BattleSide.DEFENDER
            and context.status_identifier == VolatileStatusKind.FLINCH.value
        )
        return StatusPreventionResult(
            prevented=prevented,
            source_identifier=self.coverage.identifier,
            reason="The target prevents flinch." if prevented else "",
        )


def test_factory_registers_three_moves_and_exposes_partial_capability_coverage() -> None:
    """Pokemon Champion 具体工厂应直接创建冰冻拳、击掌奇袭和劈瓦三种不同产品，三个顶层机制都标记为 supported，而冰冻拳的冰冻追加效果与劈瓦的屏障破坏必须通过结构化子能力标记为 unsupported。该测试同时保护 dispatcher 能展开这些缺口，避免整体 effect 已支持后把仍未实现的子机制静默伪装成完整覆盖。"""
    factory = PokemonChampionEffectFactory()
    effects = (
        factory.create_move_effect("ice-punch"),
        factory.create_move_effect("fake out"),
        factory.create_move_effect("brick_break"),
    )
    dispatcher = BattleEffectDispatcher[BattleAction].from_effects(effects)

    assert isinstance(effects[0], IcePunchEffect)
    assert isinstance(effects[1], FakeOutEffect)
    assert isinstance(effects[2], BrickBreakEffect)
    assert tuple(effect.coverage.status for effect in effects) == (
        EffectCoverageStatus.SUPPORTED,
        EffectCoverageStatus.SUPPORTED,
        EffectCoverageStatus.SUPPORTED,
    )
    assert tuple(
        capability.identifier for capability in dispatcher.unsupported_capabilities
    ) == ("freeze_secondary_effect", "screen_break")


def test_move_effect_identifier_is_normalized_and_part_of_state_semantics() -> None:
    """具体招式 effect 标识会决定同一个招式行动是否触发首次回合限制或伤害后状态请求，因此它不能像展示名称一样被状态键忽略。该测试要求连字符形式在 domain 边界规范化为下划线，并验证仅修改 effect_identifier 就会改变 MoveSpecKey，从而保证状态图不会把具有不同未来转移语义的节点错误归并。"""
    plain = _move_spec(
        move_id=8,
        name="Ice Punch",
        move_type=Type.ICE,
        power=75,
    )
    bound = replace(plain, effect_identifier=" Ice-Punch ")

    assert bound.effect_identifier == "ice_punch"
    assert bound.state_key != plain.state_key


def test_ice_punch_uses_common_damage_and_reports_freeze_as_unsupported() -> None:
    """冰冻拳独立 effect 不应复制 PP、命中、属性克制和伤害公式。本场景让快龙使用真实冰属性物理招式攻击龙与飞行双属性目标，并预置目标畏缩以排除其反击干扰；完整回合必须扣除一次 PP、按 75% 命中率产生精确的命中与未命中分支、通过通用伤害降低目标 HP，同时 coverage 仍明确保留尚未实现的冰冻追加效果。"""
    ice_punch = _move_spec(
        move_id=8,
        name="Ice Punch",
        move_type=Type.ICE,
        power=75,
        accuracy=75,
        max_pp=15,
        effect_identifier="ice-punch",
    )
    tackle = _move_spec(
        move_id=33,
        name="Tackle",
        move_type=Type.NORMAL,
        power=20,
        max_pp=35,
    )
    state = _battle_state(
        attacker_move=ice_punch,
        defender_move=tackle,
        defender_name="Dragonite Target",
        defender_types=(Type.DRAGON, Type.FLYING),
        defender_stats=StatValues(260, 150, 130, 120, 120, 80),
        defender_flinched=True,
    )
    effect = PokemonChampionEffectFactory().create_move_effect("ice_punch")

    transitions = _resolve(state, effect)

    assert all(
        transition.state.attacker.move_slot(8).current_pp == 14
        for transition in transitions
    )
    miss_probability = sum(
        (
            transition.probability
            for transition in transitions
            if transition.state.defender.current_hp == 260
        ),
        Fraction(0, 1),
    )
    hit_probability = sum(
        (
            transition.probability
            for transition in transitions
            if transition.state.defender.current_hp < 260
        ),
        Fraction(0, 1),
    )
    assert miss_probability == Fraction(1, 4)
    assert hit_probability == Fraction(3, 4)
    assert all(
        not transition.state.defender.status.has_volatile(VolatileStatusKind.FLINCH)
        for transition in transitions
    )
    assert tuple(
        capability.identifier for capability in effect.coverage.unsupported_capabilities
    ) == ("freeze_secondary_effect",)


def test_brick_break_uses_common_type_effectiveness_and_reports_screen_gap() -> None:
    """劈瓦独立 effect 只声明差异能力，直接伤害必须继续走通用物理计算。测试分别让格斗招式攻击恶与冰双属性目标以及幽灵属性目标：前者应受到伤害，后者因属性免疫保持满 HP；两个场景都必须扣除一次 PP。与此同时 coverage 只把屏障破坏标为 unsupported，不能把基础伤害误报为缺失。"""
    brick_break = _move_spec(
        move_id=280,
        name="Brick Break",
        move_type=Type.FIGHTING,
        power=75,
        max_pp=15,
        effect_identifier="brick-break",
    )
    tackle = _move_spec(
        move_id=33,
        name="Tackle",
        move_type=Type.NORMAL,
        power=20,
        max_pp=35,
    )
    factory = PokemonChampionEffectFactory()
    effect = factory.create_move_effect("brick break")
    weak_state = _battle_state(
        attacker_move=brick_break,
        defender_move=tackle,
        defender_flinched=True,
    )
    immune_state = _battle_state(
        attacker_move=brick_break,
        defender_move=tackle,
        defender_name="Gengar",
        defender_types=(Type.GHOST, Type.POISON),
        defender_stats=StatValues(200, 100, 100, 150, 120, 130),
        defender_flinched=True,
    )

    weak_transitions = _resolve(weak_state, effect)
    immune_transitions = _resolve(immune_state, effect)

    assert all(
        transition.state.attacker.move_slot(280).current_pp == 14
        for transition in (*weak_transitions, *immune_transitions)
    )
    assert all(
        transition.state.defender.current_hp < weak_state.defender.current_hp
        for transition in weak_transitions
    )
    assert all(
        transition.state.defender.current_hp == immune_state.defender.current_hp
        for transition in immune_transitions
    )
    assert tuple(
        capability.identifier for capability in effect.coverage.unsupported_capabilities
    ) == ("screen_break",)


def test_fake_out_first_turn_uses_common_priority_and_flinches_unacted_target() -> None:
    """首次出场的玛纽拉使用击掌奇袭时，+3 优先级必须由 MoveSpec 与通用行动顺序策略生效，而不是由具体 effect 重排完整行动。招式命中并完成普通伤害后应发出畏缩请求，使尚未行动的快龙本回合不扣 PP；回合结束后畏缩被通用清理，同时双方首次出场标记完成，证明具体 effect 只补充首次回合门禁与状态事件。"""
    fake_out = _move_spec(
        move_id=252,
        name="Fake Out",
        move_type=Type.NORMAL,
        power=40,
        priority=3,
        max_pp=10,
        effect_identifier="fake-out",
    )
    dragon_claw = _move_spec(
        move_id=337,
        name="Dragon Claw",
        move_type=Type.DRAGON,
        power=80,
        max_pp=15,
    )
    state = _battle_state(
        attacker_move=fake_out,
        defender_move=dragon_claw,
        attacker_name="Weavile",
        attacker_types=(Type.DARK, Type.ICE),
        attacker_stats=StatValues(170, 172, 85, 60, 105, 90),
        defender_name="Dragonite",
        defender_types=(Type.DRAGON, Type.FLYING),
        defender_stats=StatValues(240, 186, 115, 120, 120, 200),
    )
    effect = PokemonChampionEffectFactory().create_move_effect("fake_out")

    transitions = _resolve(state, effect)

    assert all(
        transition.state.attacker.move_slot(252).current_pp == 9
        for transition in transitions
    )
    assert all(
        transition.state.defender.move_slot(337).current_pp == 15
        for transition in transitions
    )
    assert all(transition.state.defender.current_hp < 240 for transition in transitions)
    assert all(
        not transition.state.defender.status.has_volatile(VolatileStatusKind.FLINCH)
        for transition in transitions
    )
    assert all(not transition.state.attacker.is_first_turn for transition in transitions)
    assert all(not transition.state.defender.is_first_turn for transition in transitions)


def test_fake_out_after_first_turn_fails_before_pp_and_allows_target_action() -> None:
    """非首次出场回合再次选择击掌奇袭时，FakeOutEffect 必须给出确定的执行前拒绝，而不是继续命中、伤害或施加畏缩。按照当前 MoveExecutionPolicy，被 ValidateActionEffect 阻止的行动不消耗 PP；目标仍应正常完成自己的招式并扣除 PP。该测试把当前首版失败语义固定下来，后续若要调整真实游戏中的 PP 行为必须显式修改 policy 与测试合同。"""
    fake_out = _move_spec(
        move_id=252,
        name="Fake Out",
        move_type=Type.NORMAL,
        power=40,
        priority=3,
        max_pp=10,
        effect_identifier="fake_out",
    )
    dragon_claw = _move_spec(
        move_id=337,
        name="Dragon Claw",
        move_type=Type.DRAGON,
        power=80,
        max_pp=15,
    )
    state = _battle_state(
        attacker_move=fake_out,
        defender_move=dragon_claw,
        attacker_name="Weavile",
        attacker_types=(Type.DARK, Type.ICE),
        attacker_stats=StatValues(170, 172, 85, 60, 105, 180),
        defender_name="Dragonite",
        defender_types=(Type.DRAGON, Type.FLYING),
        defender_stats=StatValues(240, 186, 115, 120, 120, 110),
        attacker_first_turn=False,
        defender_first_turn=False,
        turn_number=2,
    )
    effect = PokemonChampionEffectFactory().create_move_effect("fake_out")

    transitions = _resolve(state, effect)

    assert all(
        transition.state.attacker.move_slot(252).current_pp == 10
        for transition in transitions
    )
    assert all(
        transition.state.defender.move_slot(337).current_pp == 14
        for transition in transitions
    )
    assert all(transition.state.defender.current_hp == 240 for transition in transitions)
    assert all(transition.state.attacker.current_hp < 170 for transition in transitions)
    assert all(
        transition.state.phase is BattlePhase.ACTION_SELECTION
        for transition in transitions
    )


def test_fake_ability_prevents_typed_flinch_without_move_inspecting_ability() -> None:
    """击掌奇袭应只发出携带 source、target 与 flinch 标识的类型化状态请求，不能检查目标配置的 ability identifier。测试额外注入一个只实现 PreventVolatileStatusEffect 的 fake ability：它阻止防守方畏缩后，速度更慢但仍未行动的目标应继续执行招式并扣除 PP。该结果证明拦截发生在 dispatcher 的统一状态事件边界，而不是 FakeOutEffect 中硬编码精神力等特性。"""
    fake_out = _move_spec(
        move_id=252,
        name="Fake Out",
        move_type=Type.NORMAL,
        power=40,
        priority=3,
        max_pp=10,
        effect_identifier="fake_out",
    )
    dragon_claw = _move_spec(
        move_id=337,
        name="Dragon Claw",
        move_type=Type.DRAGON,
        power=80,
        max_pp=15,
    )
    state = _battle_state(
        attacker_move=fake_out,
        defender_move=dragon_claw,
        attacker_name="Weavile",
        attacker_types=(Type.DARK, Type.ICE),
        attacker_stats=StatValues(170, 172, 85, 60, 105, 180),
        defender_name="Dragonite",
        defender_types=(Type.DRAGON, Type.FLYING),
        defender_stats=StatValues(240, 186, 115, 120, 120, 110),
    )
    effect = PokemonChampionEffectFactory().create_move_effect("fake_out")

    transitions = _resolve(state, effect, PreventDefenderFlinchEffect())

    assert all(
        transition.state.attacker.move_slot(252).current_pp == 9
        for transition in transitions
    )
    assert all(
        transition.state.defender.move_slot(337).current_pp == 14
        for transition in transitions
    )
    assert all(transition.state.attacker.current_hp < 170 for transition in transitions)
    assert all(
        not transition.state.defender.status.has_volatile(VolatileStatusKind.FLINCH)
        for transition in transitions
    )
