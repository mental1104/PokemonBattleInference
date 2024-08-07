from api.schema.pokemon import PokemonEntity
from api.schema.move import Move, MoveType
from api.utils.type import TypeHelper
import logging

def calculate(attacker: PokemonEntity, defenser: PokemonEntity, move: Move):
    if move.move_type == MoveType.special_move or move.move_type == MoveType.physical_move:
        damage = int((2 * attacker.level + 10)/250.0 * attacker.stat.special_attack / defenser.stat.special_defense * 90 + 2)
        # 本系一致加成
        if move.type in [attacker.type_1, attacker.type_2]:
            damage *= 1.5
        # 属性克制计算
        type_multiplier = 1.0
        type_multiplier *= TypeHelper.get_type_efficacy(move.type, defenser.type_1) / 100.0
        logging.info(type_multiplier)
        if defenser.type_2:
            type_multiplier *= TypeHelper.get_type_efficacy(move.type, defenser.type_2) / 100.0
        damage *= type_multiplier
    else:
        damage = 0
    
    return int(damage * 0.85), int(damage)

def calculate_percentage(attacker: PokemonEntity, defenser: PokemonEntity, move: Move):
    min_damage, max_damage = calculate(attacker, defenser, move)
    return (float(min_damage)/defenser.stat.hp, float(max_damage)/defenser.stat.hp)


class DamageCalculator:
    pass