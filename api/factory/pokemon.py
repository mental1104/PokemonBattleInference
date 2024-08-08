import logging

from api.schema.pokemon import PokemonEntity
from api.schema.property import BasePoints, IndividualValues, SpeciesStrength, Statistic, PropertyEnum
from api.common.ability_calculate import AbilityCalculatorFactory
from api.db import open_session
from api.models.pokemon import Pokemon

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
            type_1 = pokemon_record.type_1
            type_2 = pokemon_record.type_2

        pokemon = PokemonEntity(
            id=id,
            name=name,
            level=level,
            type_1=type_1,
            type_2=type_2,
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

        for _, property in PropertyEnum.__members__.items():
            speices = getattr(pokemon.species_strength, property.value)
            base_point = getattr(pokemon.basepoint, property.value)
            individual = getattr(pokemon.individual_values, property.value)
            ability = AbilityCalculatorFactory.get(property).calculate(
                pokemon.level, speices, base_point, individual, pokemon.nature
            )
            setattr(pokemon.stat, property.value, ability)
        logging.debug(pokemon.stat)