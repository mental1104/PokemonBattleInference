from __future__ import annotations

from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.effects import PokemonChampionEffectFactory
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_execution import StandardMoveTurnResolver
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import BattleState, BattlerState
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


def test_fake_out_type_immunity_does_not_emit_flinch_attempt() -> None:
    """击掌奇袭命中幽灵属性目标时，普通属性免疫会让统一伤害链产出零伤害，具体 effect 不得仅因为进入 after-damage 阶段就错误施加畏缩。本测试要求攻击方仍按一次合法使用扣除 PP，但幽灵目标保持满 HP、正常执行自己的招式并扣除 PP，同时反击确实降低攻击方 HP，从外部结果证明目标没有被一个无效攻击阻止行动。"""
    attacker_stats = StatValues(170, 172, 85, 60, 105, 90)
    defender_stats = StatValues(200, 100, 100, 150, 120, 200)
    fake_out = MoveSpec(
        move_id=252,
        move=BattleMove(
            name="Fake Out",
            type=Type.NORMAL,
            category=MoveCategory.PHYSICAL,
            power=40,
        ),
        max_pp=10,
        priority=3,
        accuracy=100,
        effect_identifier="fake_out",
    )
    shadow_ball = MoveSpec(
        move_id=247,
        move=BattleMove(
            name="Shadow Ball",
            type=Type.GHOST,
            category=MoveCategory.SPECIAL,
            power=80,
        ),
        max_pp=15,
        accuracy=100,
    )
    state = BattleState(
        attacker=BattlerState(
            spec=PokemonSpec(
                pokemon_id=461,
                name="Weavile",
                level=50,
                types=(Type.DARK, Type.ICE),
                stats=attacker_stats,
                item=DamageItem.UNKNOWN,
                moves=(fake_out,),
            ),
            current_hp=attacker_stats.hp,
            move_slots=(MoveSlotState(move_id=252, current_pp=10, max_pp=10),),
        ),
        defender=BattlerState(
            spec=PokemonSpec(
                pokemon_id=94,
                name="Gengar",
                level=50,
                types=(Type.GHOST, Type.POISON),
                stats=defender_stats,
                item=DamageItem.UNKNOWN,
                moves=(shadow_ball,),
            ),
            current_hp=defender_stats.hp,
            move_slots=(MoveSlotState(move_id=247, current_pp=15, max_pp=15),),
        ),
        rules=BattleInferenceRules(level=50),
    )
    effect = PokemonChampionEffectFactory().create_move_effect("fake_out")
    resolver = StandardMoveTurnResolver(effects=(effect,))
    attacker_action = resolver.legal_actions(state, BattleSide.ATTACKER)[0]
    defender_action = resolver.legal_actions(state, BattleSide.DEFENDER)[0]

    transitions = resolver.resolve(
        state,
        attacker_action,
        defender_action,
    ).transitions

    assert all(
        transition.state.attacker.move_slot(252).current_pp == 9
        for transition in transitions
    )
    assert all(
        transition.state.defender.move_slot(247).current_pp == 14
        for transition in transitions
    )
    assert all(transition.state.defender.current_hp == 200 for transition in transitions)
    assert all(transition.state.attacker.current_hp < 170 for transition in transitions)
