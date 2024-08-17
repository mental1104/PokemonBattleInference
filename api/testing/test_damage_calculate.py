import pytest
from unittest.mock import MagicMock
from api.factory.pokemon import PokemonEntityFactory
from api.common.damage_calculate.calculator import DamageCalculator
from api.schema.nature import Nature
from api.models.pokemon import Pokemon
from api.db import setup
from api.schema.move import Move, MoveType
from api.schema.types import Type

def create_pokemon_factory(id):
    pokemon_map = {
        727: Pokemon(id=727, name='incineroar', type_1=Type.FIRE.value, type_2=Type.DARK.value, hp=95,  attack=115, defense=90, special_attack=80, special_defense=90, speed=60),
        812: Pokemon(id=812, name='rillaboom', type_1=Type.GRASS.value, type_2=None,            hp=100, attack=125, defense=90, special_attack=60, special_defense=70, speed=85)
    }
    return pokemon_map.get(id)

# ((727, 100, [4, 252, 0, 0, 0, 252], [31, 31, 31, 31, 31, 31], Nature.ADAMANT), 
#      (812, 100, [4, 252, 0, 0, 0, 252], [31, 31, 31, 31, 31, 31], Nature.JOLLY),
#      Move(power=120, type=Type.FIRE, move_type=MoveType.physical_move), 1)
@pytest.mark.parametrize('attacker_data, defenser_data, move, expect', [
    
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
    for entity in (attacker_data, defenser_data):
        entity_stat = Pokemon.get_by_id(mock_session_filter(entity[0]), entity[0])
        pokemon_entity = PokemonEntityFactory.create_by_diy(
            entity[0], 
            entity_stat.name,
            entity[1],
            entity_stat.type_1,
            entity_stat.type_2,
            [
                entity_stat.hp, entity_stat.attack, entity_stat.defense,
                entity_stat.special_attack, entity_stat.special_defense, entity_stat.speed
            ],
            entity[2],
            entity[3],
            entity[4]
        )
        result.append(pokemon_entity)
    result = tuple(result)
    attacker, defenser = result

    calculator = DamageCalculator()
    result = calculator.calculate(attacker, defenser, move)
    print(result.min_damage)








# def set_logging(process_name, log_level="INFO"):
#     for handler in logging.root.handlers[:]:
#         logging.root.removeHandler(handler)
#     logging.basicConfig(
#         level=getattr(logging, log_level),
#         format="[SERVER]%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s"
#             " %(message)s"
#     )

# if __name__ == "__main__":
#     setup()
#     set_logging('TEST', 'DEBUG')
#     attacker = PokemonEntityFactory.create(6, 100,
#         [4,0,0,252,0,252],
#         [31,31,31,31,31,31], 
#         Nature.TIMID
#     )
#     defense = PokemonEntityFactory.create(9, 100,
#         [4,0,0,252,0,252],
#         [31,31,31,31,31,31],
#         Nature.MODEST                                 
#     )

#     calculator = DamageCalculator()
    
#     result = calculator.calculate(attacker, defense, Move(
#             power=90,
#             type=Type.FIRE,
#             move_type=MoveType.special_move
#         )
#     )
#     logging.info(result.min_damage)
#     logging.info(result.max_damage)
#     logging.info(result.min_damage_percent)
#     logging.info(result.max_damage_percent)


    # damage = calculate_percentage(attacker, defense, Move(
    #     power=90,
    #     type=Type.FIRE,
    #     move_type=MoveType.special_move
    # ))
    # logging.info(damage)
    