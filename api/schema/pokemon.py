from typing import Optional, List
from pydantic import BaseModel
from api.schema.property import BasePoints, IndividualValues, SpeciesStrength, Statistic
from api.schema.nature import Nature
from api.schema.types import Type

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
    id: int
    level: int
    type_1: Type
    type_2: Optional[Type] = None
    basepoint: BasePoints
    individual_values: IndividualValues
    species_strength: SpeciesStrength
    stat: Optional[Statistic] = None
    nature: Nature
    ability_index: int
    item_index: int
    

        