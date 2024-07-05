from api.factory.pokemon import PokemonEntityFactory
import logging

def calculate(attacker: PokemonEntityFactory, defenser: PokemonEntityFactory):
    damage = int((2 * attacker.level + 10)/250.0 * attacker.stat.special_attack / defenser.stat.special_defense * 90 + 2)*1.5/2.0
    return (float(int(damage * 0.85))/defenser.stat.hp, float(int(damage))/defenser.stat.hp)
