import logging
from typing import Any, Dict, Union

from api.schema.pokemon import PokemonEntity
from api.schema.damage_calculator import Move
from api.schema.nature import Nature
from api.schema.property import BasePoints, IndividualValues, SpeciesStrength, Statistic, PropertyEnum
from api.utils.property import PropertyCalculator
from api.db import open_session
from api.models.pokemon import Pokemon


# 性格增益
class PokemonEntityFactory(PokemonEntity):
    
    @classmethod
    def create(cls, id, level, basepoint, individual_values, nature, ability_index=0, item_index=0):
        cls.id = id
        cls.name = ""
        cls.level = level
        species_strength = SpeciesStrength()

        with open_session() as session:
            pokemon_record = Pokemon.get_by_id(session, id)
            logging.debug(pokemon_record)
            if pokemon_record is not None:
                species_strength = SpeciesStrength.create([
                    pokemon_record.hp,
                    pokemon_record.attack,
                    pokemon_record.defense,
                    pokemon_record.special_attack,
                    pokemon_record.special_defense,
                    pokemon_record.speed
                ])
                cls.name = pokemon_record.name
                logging.info(species_strength)
            

        cls.nature = nature
        cls.species_strength = species_strength
        cls.basepoint = BasePoints.create(basepoint)
        cls.individual_values = IndividualValues.create(individual_values)
        cls.stat = Statistic()
        cls.refresh()
        return cls

    @classmethod
    def refresh(cls):
        cls.stat.hp = PropertyCalculator.calculate_hp(cls.level, cls.species_strength.hp, cls.basepoint.hp, cls.individual_values.hp)
        cls.stat.attack = PropertyCalculator.calculate_ability(PropertyEnum.ATTACK, cls.level, cls.species_strength.attack, cls.basepoint.attack, cls.individual_values.attack, cls.nature)
        cls.stat.defense = PropertyCalculator.calculate_ability(PropertyEnum.DEFENSE, cls.level, cls.species_strength.defense, cls.basepoint.defense, cls.individual_values.defense, cls.nature)
        cls.stat.special_attack = PropertyCalculator.calculate_ability(PropertyEnum.SPECIAL_ATTACK, cls.level, cls.species_strength.special_attack, cls.basepoint.special_attack, cls.individual_values.special_attack, cls.nature)
        cls.stat.special_defense = PropertyCalculator.calculate_ability(PropertyEnum.SPECIAL_DEFENSE, cls.level, cls.species_strength.special_defense, cls.basepoint.special_defense, cls.individual_values.special_defense, cls.nature)
        cls.stat.speed = PropertyCalculator.calculate_ability(PropertyEnum.SPEED, cls.level, cls.species_strength.speed, cls.basepoint.speed, cls.individual_values.speed, cls.nature)