from pydantic import BaseModel
from typing import Optional
from enum import Enum
import sys
sys.path.append("../")
from schema.damage_calculator import Attacker, Defender, Move
from db import setup, open_session
from models.pokemon import Pokemon


class CommonProperty(BaseModel):
    hp: int = 0
    attack: int = 0
    defense: int = 0
    special_attack: int = 0
    special_defense: int = 0
    speed: int = 0


class IndividualValues(CommonProperty):
    pass

class SpeciesStrength(CommonProperty):
    pass

class BasePoints(CommonProperty):
    pass

class Statistic(CommonProperty):
    pass


class MoveType:
    physical_move = "physical_move"
    special_move = "special_move"
    status_move =  "status_move"


class Move:
    power: Optional[int] = None
    move_type: MoveType


class PokemonEntity:
    
    def __init__(self, 
        id, 
        level: int,
        basepoint: BasePoints,
        individual_values: IndividualValues,
        ability_index = 1,
        item_index = 1,
    ):
        self.id = id
        self.name = ""
        self.level = level
        species_strength = SpeciesStrength()
        print(111)
        with open_session() as session:
            print(123232)
            pokemon_record = Pokemon.get_by_id(session, id)
            print(555322)
            print(pokemon_record)
            if pokemon_record is not None:
                species_strength = SpeciesStrength(
                    hp=pokemon_record.hp,
                    attack=pokemon_record.attack,
                    defense=pokemon_record.defense,
                    special_attack=pokemon_record.special_attack,
                    special_defense=pokemon_record.special_defense,
                    speed=pokemon_record.speed
                )
                self.name = pokemon_record.name
                print(self.name)
        self.species_strength = species_strength
        self.basepoint = basepoint
        self.individual_values = individual_values

class PropertyCalculator:
    @staticmethod
    def calculate_hp(level: int, species_strength: int, basepoint: int = 252, individual_values: int = 31):
        print(level)
        print(species_strength)
        print(basepoint)
        print(individual_values)
        return ((species_strength * 2 + individual_values + basepoint / 4) * level) / 100.0 + 10 + level

    @staticmethod
    def calculate_ability(level: int, species_strength: int, basepoint: int = 252, individual_values: int = 31, nature: str = ""):
        return (((species_strength * 2 + individual_values + basepoint / 4) * level) / 100.0 + 5) * 1.0
        
    def __init__(self, pokemon_entity: PokemonEntity):
        stat = Statistic()
        species_strength = pokemon_entity.species_strength
        basepoint = pokemon_entity.basepoint
        individual_values = pokemon_entity.individual_values
        stat.hp = PropertyCalculator.calculate_hp(pokemon_entity.level, species_strength.hp, basepoint.hp, individual_values.hp)
        stat.attack = PropertyCalculator.calculate_ability(pokemon_entity.level, species_strength.attack, basepoint.attack, individual_values.attack)
        stat.defense = PropertyCalculator.calculate_ability(pokemon_entity.level, species_strength.defense, basepoint.defense, individual_values.defense)
        stat.special_attack = PropertyCalculator.calculate_ability(pokemon_entity.level, species_strength.special_attack, basepoint.special_attack, individual_values.special_attack)
        stat.special_defense = PropertyCalculator.calculate_ability(pokemon_entity.level, species_strength.special_defense, basepoint.special_defense, individual_values.special_defense)
        stat.speed = PropertyCalculator.calculate_ability(pokemon_entity.level, species_strength.speed, basepoint.speed, individual_values.speed)
        self.stat = stat
        

class DamageCalculator:
    
    @staticmethod
    def calculate(attacker: Attacker, defender: Defender, move: Move):
        pass
    

if __name__ == "__main__":
    setup()
    pokemon = PokemonEntity(6, 100, BasePoints(special_attack=252, speed=252, hp=4), IndividualValues(special_attack=31, speed=31))
    attacker = PropertyCalculator(pokemon)
    print(attacker.stat.special_attack)
    print(attacker.stat.speed)