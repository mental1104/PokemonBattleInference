import sys
sys.path.append("../")
from schema.damage_calculator import Attacker, Defender, Move
from schema.nature import Nature
from schema.property import BasePoints, IndividualValues, SpeciesStrength, Statistic, PropertyCalculator, PropertyEnum
from db import open_session
from models.pokemon import Pokemon




# 性格增益



class PokemonEntity:
    def __init__(self, 
        id, 
        level: int,
        basepoint: BasePoints,
        individual_values: IndividualValues,
        nature: Nature,
        ability_index = 1,
        item_index = 1,
    ):
        self.id = id
        self.name = ""
        self.level = level
        species_strength = SpeciesStrength()

        with open_session() as session:
            pokemon_record = Pokemon.get_by_id(session, id)
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

        self.nature = nature
        self.species_strength = species_strength
        self.basepoint = basepoint
        self.individual_values = individual_values
        self.stat = Statistic()
        self.refresh()
    
    def refresh(self):
        self.stat.hp = PropertyCalculator.calculate_hp(self.level, self.species_strength.hp, self.basepoint.hp, self.individual_values.hp)
        self.stat.attack = PropertyCalculator.calculate_ability(PropertyEnum.ATTACK, self.level, self.species_strength.attack, self.basepoint.attack, self.individual_values.attack, self.nature)
        self.stat.defense = PropertyCalculator.calculate_ability(PropertyEnum.DEFENSE, self.level, self.species_strength.defense, self.basepoint.defense, self.individual_values.defense, self.nature)
        self.stat.special_attack = PropertyCalculator.calculate_ability(PropertyEnum.SPECIAL_ATTACK, self.level, self.species_strength.special_attack, self.basepoint.special_attack, self.individual_values.special_attack, self.nature)
        self.stat.special_defense = PropertyCalculator.calculate_ability(PropertyEnum.SPECIAL_DEFENSE, self.level, self.species_strength.special_defense, self.basepoint.special_defense, self.individual_values.special_defense, self.nature)
        self.stat.speed = PropertyCalculator.calculate_ability(PropertyEnum.SPEED, self.level, self.species_strength.speed, self.basepoint.speed, self.individual_values.speed, self.nature)


class DamageCalculator:
    
    @staticmethod
    def calculate(attacker: Attacker, defender: Defender, move: Move):
        pass
