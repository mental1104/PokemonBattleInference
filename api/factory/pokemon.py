import logging
import copy
from api.schema.nature import Nature
from api.schema.pokemon import PokemonEntity
from api.schema.level import DefaultLevel
from api.schema.types import Type
from api.schema.property import BasePoints, IndividualValues, SpeciesStrength, Statistic, PropertyEnum
from api.common.ability_calculate import AbilityCalculatorFactory
from api.db import open_session
from api.models.pokemon import Pokemon

# 性格增益

class PokemonBuilder:
    def __init__(self):
        self._pokemon = PokemonEntity()

    def set_id(self, id):
        self._pokemon.id = id
        return self

    def set_name(self, name):
        self._pokemon.name = name
        return self

    def set_level(self, level):
        self._pokemon.level = level
        return self

    def set_types(self, type_1, type_2):
        self._pokemon.type_1 = type_1
        self._pokemon.type_2 = type_2
        return self

    def set_species_strength(self, species_strength):
        self._pokemon.species_strength = SpeciesStrength.create(species_strength)
        return self

    def set_basepoint(self, basepoint):
        self._pokemon.basepoint = BasePoints.create(basepoint)
        return self

    def set_individual_values(self, individual_values):
        self._pokemon.individual_values = IndividualValues.create(individual_values)
        return self

    def set_nature(self, nature):
        self._pokemon.nature = nature
        return self

    def set_ability_index(self, ability_index):
        self._pokemon.ability_index = ability_index
        return self

    def set_item_index(self, item_index):
        self._pokemon.item_index = item_index
        return self

    def build(self):
        self.refresh()
        result = copy.deepcopy(self._pokemon)
        self._pokemon = PokemonEntity()
        return result

    def refresh(self):
        self._pokemon.stat = Statistic()

        for _, property in PropertyEnum.__members__.items():
            species = getattr(self._pokemon.species_strength, property.value)
            base_point = getattr(self._pokemon.basepoint, property.value)
            individual = getattr(self._pokemon.individual_values, property.value)
            ability = AbilityCalculatorFactory.get(property).calculate(
                self._pokemon.level, species, base_point, individual, self._pokemon.nature
            )
            setattr(self._pokemon.stat, property.value, ability)


class PokemonDirector:
    def __init__(self, builder=PokemonBuilder()):
        self.builder = builder

    def construct_from_database(
        self,
        id,
        level=DefaultLevel.DEFAULT_100_LEVEL.value,
        basepoint=(0,0,0,0,0,0),
        individual_values=(31,31,31,31,31,31),
        nature=Nature.JOLLY,
        ability_index=0,
        item_index=0
    ):
        with open_session() as session:
            pokemon_record = Pokemon.get_by_id(session, id)
            if not pokemon_record:
                raise ValueError(f"Pokemon with id {id} not found.")

            self.builder.set_id(
                id
            ).set_level(
                level
            ).set_name(
                pokemon_record.name
            ).set_types(
                pokemon_record.type_1,
                pokemon_record.type_2
            ).set_species_strength([
                pokemon_record.hp,
                pokemon_record.attack,
                pokemon_record.defense,
                pokemon_record.special_attack,
                pokemon_record.special_defense,
                pokemon_record.speed,
            ]).set_basepoint(
                basepoint
            ).set_individual_values(
                individual_values
            ).set_nature(
                nature
            ).set_ability_index(
                ability_index
            ).set_item_index(item_index)

        return self.builder.build()

    def construct_custom(
        self,
        id=1,
        name="",
        level=DefaultLevel.DEFAULT_100_LEVEL.value,
        type_1=Type.NORMAL,
        type_2=None,
        species_strength=(0,0,0,0,0,0),
        basepoint=(0,0,0,0,0,0),
        individual_values=(0,0,0,0,0,0),
        nature=Nature.JOLLY
    ):
        self.builder.set_id(
            id
        ).set_name(
            name
        ).set_level(
            level
        ).set_types(
            type_1,
            type_2
        ).set_species_strength(
            species_strength
        ).set_basepoint(
            basepoint
        ).set_individual_values(
            individual_values
        ).set_nature(
            nature
        ).set_ability_index(
            0
        ).set_item_index(
            0
        )

        return self.builder.build()
