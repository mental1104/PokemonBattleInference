import logging

from pokemon_battle_inference.infrastructure.db import startup
from pokemon_battle_inference.infrastructure.db.models import pokemon  # noqa: F401
from scripts.init_pokemon import InitPokemon
from scripts.init_types import InitTypes


def init_table():
    InitPokemon.init()
    InitTypes.init()


def main():
    logging.basicConfig(
        level=getattr(logging, "INFO"),
        format="[SERVER]%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s"
        " %(message)s",
    )
    startup(True)
    init_table()


if __name__ == "__main__":
    main()
