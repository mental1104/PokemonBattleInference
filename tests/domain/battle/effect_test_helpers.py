from __future__ import annotations

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import BattleState, BattlerState
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


def _battler_state(spec: PokemonSpec) -> BattlerState:
    """把不可变配置转换为满 HP、满 PP 的 effect 测试状态。

    Args:
        spec: 已经包含一到四个招式配置的宝可梦不变配置。

    Returns:
        当前 HP 等于最大 HP、全部招式 PP 已补满的 ``BattlerState``。
    """
    return BattlerState(
        spec=spec,
        current_hp=spec.stats.hp,
        move_slots=tuple(
            MoveSlotState(
                move_id=move.move_id,
                current_pp=move.max_pp,
                max_pp=move.max_pp,
            )
            for move in spec.moves
        ),
    )


def build_effect_test_battle_state() -> BattleState:
    """构造 effect 协议测试使用的真实 #21 ``BattleState``。

    Returns:
        等级 50 的巨钳螳螂对仙子伊布 1v1 初始节点。配置只保留一个合理
        招式槽，以便测试聚焦状态不可变更新和带权转移，而不是招式合法性大全。
    """
    attacker_spec = PokemonSpec(
        pokemon_id=212,
        name="scizor",
        level=50,
        types=(Type.BUG, Type.STEEL),
        stats=StatValues(
            hp=177,
            attack=200,
            defense=120,
            special_attack=67,
            special_defense=100,
            speed=85,
        ),
        ability=DamageAbility.TECHNICIAN,
        item=DamageItem.CHOICE_BAND,
        moves=(
            MoveSpec(
                move_id=418,
                move=BattleMove(
                    name="bullet-punch",
                    type=Type.STEEL,
                    category=MoveCategory.PHYSICAL,
                    power=40,
                ),
                max_pp=30,
            ),
        ),
    )
    defender_spec = PokemonSpec(
        pokemon_id=700,
        name="sylveon",
        level=50,
        types=(Type.FAIRY,),
        stats=StatValues(
            hp=202,
            attack=76,
            defense=117,
            special_attack=130,
            special_defense=150,
            speed=80,
        ),
        moves=(
            MoveSpec(
                move_id=585,
                move=BattleMove(
                    name="moonblast",
                    type=Type.FAIRY,
                    category=MoveCategory.SPECIAL,
                    power=95,
                ),
                max_pp=15,
            ),
        ),
    )
    return BattleState(
        attacker=_battler_state(attacker_spec),
        defender=_battler_state(defender_spec),
        rules=BattleInferenceRules(level=50),
    )


__all__ = ["build_effect_test_battle_state"]
