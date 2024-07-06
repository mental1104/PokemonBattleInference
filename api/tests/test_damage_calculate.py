import logging
from api.factory.pokemon import PokemonEntityFactory
from api.common.damage_calculate import calculate_percentage
from api.schema.nature import Nature
from api.db import setup
from api.schema.move import Move, MoveType
from api.schema.types import Type

def set_logging(process_name, log_level="INFO"):
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="[SERVER]%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s"
            " %(message)s"
    )

if __name__ == "__main__":
    setup()
    set_logging('TEST', 'DEBUG')
    attacker = PokemonEntityFactory.create(6, 100,
        [4,0,0,252,0,252],
        [31,31,31,31,31,31], 
        Nature.TIMID
    )
    defense = PokemonEntityFactory.create(9, 100,
        [4,0,0,252,0,252],
        [31,31,31,31,31,31],
        Nature.MODEST                                 
    )

    damage = calculate_percentage(attacker, defense, Move(
        power=90,
        type=Type.FIRE,
        move_type=MoveType.special_move
    ))
    logging.info(damage)