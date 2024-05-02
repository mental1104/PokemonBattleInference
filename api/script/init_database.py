import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from models import *
from db import startup

from script.init_pokemon import InitPokemon
from script.init_types import InitTypes

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