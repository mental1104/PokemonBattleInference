import sys
import logging
sys.path.append("../")
from common.damage_calculator import PokemonEntity, BasePoints, IndividualValues, Nature
from db import setup, open_session

if __name__ == "__main__":
    setup()
    pokemon = PokemonEntity(
        6, 
        100, 
        BasePoints(special_attack=252, speed=252, hp=4), 
        IndividualValues(hp=31, attack=31, defense=31, special_attack=31, special_defense=31, speed=31), 
        Nature.TIMID
    )
    print(pokemon.stat)