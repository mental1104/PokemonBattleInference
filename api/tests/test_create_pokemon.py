import logging

from api.schema.nature import Nature
from api.schema.property import BasePoints, IndividualValues
from api.factory.pokemon import PokemonEntityFactory
from api.db import setup


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
    print(pokemon.stat)