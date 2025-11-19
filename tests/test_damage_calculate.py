import pytest
from unittest.mock import MagicMock
from pokemon_battle_inference.services.pokemon_builder import PokemonDirector
from pokemon_battle_inference.domain.calculations.damage.calculator import (
    DamageCalculator,
)
from pokemon_battle_inference.domain.models.nature import Nature
from pokemon_battle_inference.infrastructure.db.models.pokemon import Pokemon
from pokemon_battle_inference.domain.models.move import Move, MoveType
from pokemon_battle_inference.domain.models.types import Type

def create_pokemon_factory(id):
    pokemon_map = {
        6  : Pokemon(id=6,   name='charizard',  type_1=Type.FIRE, type_2=Type.FLYING, hp=78, attack=84, defense=78, special_attack=109, special_defense=85, speed=100),
        9  : Pokemon(id=9,   name='blastoise',  type_1=Type.WATER, type_2=None,             hp=79, attack=83, defense=100, special_attack=85, special_defense=105, speed=78),
        591: Pokemon(id=591, name='amoonguss', type_1=Type.GRASS, type_2=Type.POISON, hp=114,  attack=85, defense=70, special_attack=85, special_defense=80, speed=30),
        727: Pokemon(id=727, name='incineroar', type_1=Type.FIRE, type_2=Type.DARK, hp=95,  attack=115, defense=90, special_attack=80, special_defense=90, speed=60),
        812: Pokemon(id=812, name='rillaboom', type_1=Type.GRASS, type_2=None,            hp=100, attack=125, defense=90, special_attack=60, special_defense=70, speed=85)
    }
    return pokemon_map.get(id)

# ((727, 100, [4, 252, 0, 0, 0, 252], [31, 31, 31, 31, 31, 31], Nature.ADAMANT), 
#      (812, 100, [4, 252, 0, 0, 0, 252], [31, 31, 31, 31, 31, 31], Nature.JOLLY),
#      Move(power=120, type=Type.FIRE, move_type=MoveType.physical_move), 1)
@pytest.mark.parametrize('attacker_data, defenser_data, move, expect', [
    # 100级喷火龙 喷射火焰 100级水箭龟
    ((6, 100, [4, 0, 0, 252, 0, 252], [31, 31, 31, 31, 31, 31], Nature.TIMID),
     (9, 100, [4, 0, 0, 252, 0, 252], [31, 31, 31, 31, 31, 31], Nature.MODEST),
     Move(power=90, type=Type.FIRE, move_type=MoveType.special_move), ((63, 74), (21.0, 24.6))),
    # 50级炽焰咆哮虎 火推 50级败露球菇
    ((727, 50, [236, 4, 100, 0, 156, 12], [31, 31, 31, 31, 31, 31], Nature.CAREFUL),
     (591, 50, [244, 0, 236, 4, 20, 4], [31, 31, 31, 31, 31, 31], Nature.BOLD),
     Move(power=120, type=Type.FIRE, move_type=MoveType.physical_move), ((140, 168), (63.6, 76.3))),
    # 50级炽焰咆哮虎 火推 50级轰雷金刚猩
    ((727, 50, [236, 4, 100, 0, 156, 12], [31, 31, 31, 31, 31, 31], Nature.CAREFUL),
     (812, 50, [244, 116, 36, 0, 60, 52], [31, 31, 31, 31, 31, 31], Nature.ADAMANT),
     Move(power=120, type=Type.FIRE, move_type=MoveType.physical_move), ((162, 192), (78.6, 93.2)))
])
def test_normal_damage(attacker_data, defenser_data, move, expect):

    def mock_session_filter(id):
        # 创建一个模拟的 session 对象
        mock_session = MagicMock()

        # 模拟 query -> filter -> first 的链式调用，返回 expected_pokemon
        mock_query = mock_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = create_pokemon_factory(id)
        return mock_session

    result = []
    director = PokemonDirector()
    for entity in (attacker_data, defenser_data):
        entity_stat = Pokemon.get_by_id(entity[0], session=mock_session_filter(entity[0]))
        pokemon_entity = director.construct_custom(
            id=entity[0], 
            name=entity_stat.name,
            level=entity[1],
            type_1=entity_stat.type_1,
            type_2=entity_stat.type_2,
            species_strength=(
                entity_stat.hp, entity_stat.attack, entity_stat.defense,
                entity_stat.special_attack, entity_stat.special_defense, entity_stat.speed
            ),
            basepoint=entity[2],
            individual_values=entity[3],
            nature=entity[4]
        )
        result.append(pokemon_entity)
    result = tuple(result)
    attacker, defenser = result

    calculator = DamageCalculator()
    result = calculator.calculate(attacker, defenser, move)

    assert(result.min_damage == expect[0][0])
    assert(result.max_damage == expect[0][1])
    assert(result.min_damage_percent == expect[1][0])
    assert(result.max_damage_percent == expect[1][1])
