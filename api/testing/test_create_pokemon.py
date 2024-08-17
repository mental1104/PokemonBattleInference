import logging

from api.schema.nature import Nature
from api.factory.pokemon import PokemonEntityFactory
from api.db import setup
from api.schema.property import PropertyEnum
from api.common.ability_calculate import AbilityCalculatorFactory


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
    pokemon = PokemonEntityFactory.create(6, 100,
        [4,0,0,252,0,252],
        [31,31,31,31,31,31], 
        Nature.TIMID
    )
    
    result = []
    for _, property in PropertyEnum.__members__.items():
        speices = getattr(pokemon.species_strength, property.value)
        individual = getattr(pokemon.individual_values, property.value)
        ability = getattr(pokemon.stat, property.value)
        result.append(AbilityCalculatorFactory.get(property).get_basepoint(pokemon.level, ability, speices, individual, pokemon.nature))
    print(result)
    print(pokemon.stat)