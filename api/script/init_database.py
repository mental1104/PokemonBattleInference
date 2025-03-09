import sys
import os
import logging


from db import startup

from script.init_pokemon import InitPokemon
from script.init_types import InitTypes
from models import pokemon

def init_table():
    InitPokemon.init()
    InitTypes.init()

def main():
    logging.basicConfig(
        level=getattr(logging, "INFO"),
        format="[SERVER]%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s"
            " %(message)s"
    )
    startup(True)
    init_table()    


if __name__ == '__main__':
    main()