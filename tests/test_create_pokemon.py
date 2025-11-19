'''
Date: 2024-12-22 04:57:03
Author: error: error: git config user.name & please set dead value or install git && error: git config user.email & please set dead value or install git & please set dead value or install git
LastEditors: error: error: git config user.name & please set dead value or install git && error: git config user.email & please set dead value or install git & please set dead value or install git
LastEditTime: 2024-12-22 04:58:25
'''
import logging

from pokemon_battle_inference.domain.models.nature import Nature
from pokemon_battle_inference.services.pokemon_builder import PokemonDirector
from pokemon_battle_inference.infrastructure.db import setup
from pokemon_battle_inference.domain.models.property import PropertyEnum
from pokemon_battle_inference.domain.calculations.ability import (
    AbilityCalculatorFactory,
)


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
    director = PokemonDirector()
    pokemon = director.construct_from_database(
        id=6,
        basepoint=(4,0,0,252,0,252),
        nature=Nature.TIMID
    )
    print(pokemon)
    
    result = []
    for _, property in PropertyEnum.__members__.items():
        speices = getattr(pokemon.species_strength, property.value)
        individual = getattr(pokemon.individual_values, property.value)
        ability = getattr(pokemon.stat, property.value)
        result.append(AbilityCalculatorFactory.get(property).get_basepoint(pokemon.level, ability, speices, individual, pokemon.nature))
    print(result)
    print(pokemon.stat)
