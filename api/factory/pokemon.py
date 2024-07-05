import logging
from typing import Any, Dict, Union

from api.schema.pokemon import PokemonEntity
from api.schema.damage_calculator import Move
from api.schema.nature import Nature
from api.schema.property import BasePoints, IndividualValues, SpeciesStrength, Statistic, PropertyEnum
from api.utils.property import PropertyCalculator
from api.db import open_session
from api.models.pokemon import Pokemon
from copy import deepcopy

# 性格增益
class PokemonEntityFactory(PokemonEntity):
    
    @staticmethod
    def create(id, level, basepoint, individual_values, nature, ability_index=0, item_index=0):
        
        name = ""
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
                logging.debug(species_strength)
    
        pokemon = PokemonEntity(
            id=id,
            name=name,
            level=level,
            basepoint=BasePoints.create(basepoint),
            individual_values=IndividualValues.create(individual_values),
            species_strength=species_strength,
            nature=nature,
            ability_index=ability_index,
            item_index=item_index
        )
        PokemonEntityFactory.refresh(pokemon)
        return pokemon

    @staticmethod
    def refresh(pokemon):
        pokemon.stat = Statistic()
        pokemon.stat.hp = PropertyCalculator.calculate_hp(pokemon.level, pokemon.species_strength.hp, pokemon.basepoint.hp, pokemon.individual_values.hp)
        pokemon.stat.attack = PropertyCalculator.calculate_ability(PropertyEnum.ATTACK, pokemon.level, pokemon.species_strength.attack, pokemon.basepoint.attack, pokemon.individual_values.attack, pokemon.nature)
        pokemon.stat.defense = PropertyCalculator.calculate_ability(PropertyEnum.DEFENSE, pokemon.level, pokemon.species_strength.defense, pokemon.basepoint.defense, pokemon.individual_values.defense, pokemon.nature)
        pokemon.stat.special_attack = PropertyCalculator.calculate_ability(PropertyEnum.SPECIAL_ATTACK, pokemon.level, pokemon.species_strength.special_attack, pokemon.basepoint.special_attack, pokemon.individual_values.special_attack, pokemon.nature)
        pokemon.stat.special_defense = PropertyCalculator.calculate_ability(PropertyEnum.SPECIAL_DEFENSE, pokemon.level, pokemon.species_strength.special_defense, pokemon.basepoint.special_defense, pokemon.individual_values.special_defense, pokemon.nature)
        pokemon.stat.speed = PropertyCalculator.calculate_ability(PropertyEnum.SPEED, pokemon.level, pokemon.species_strength.speed, pokemon.basepoint.speed, pokemon.individual_values.speed, pokemon.nature)
        logging.debug(pokemon.stat)