from typing import Optional, List
from pydantic import BaseModel
from pokemon_battle_inference.domain.models.property import (
    BasePoints,
    IndividualValues,
    SpeciesStrength,
    Statistic,
)
from pokemon_battle_inference.domain.models.nature import Nature
from pokemon_battle_inference.domain.models.types import Type
from pokemon_battle_inference.domain.models.level import DefaultLevel


class PokemonCreate(BaseModel):
    id: int
    name: str
    type_1: int
    type_2: Optional[int] = None
    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int
    move_ids: List[int]
    ability: List[int]


class AbstractCreate(BaseModel):
    id: int
    name: str


class PokemonEntity(BaseModel):
    id: int = 0
    name: str = ""
    level: int = DefaultLevel.DEFAULT_100_LEVEL.value
    type_1: Type = Type.NORMAL
    type_2: Optional[Type] = None
    basepoint: BasePoints = (0, 0, 0, 0, 0, 0)
    individual_values: IndividualValues = (31, 31, 31, 31, 31, 31)
    species_strength: SpeciesStrength = (0, 0, 0, 0, 0, 0)
    stat: Optional[Statistic] = None
    nature: Nature = Nature.JOLLY
    ability_index: int = 0
    item_index: int = 0
