from typing import Optional
from pydantic import BaseModel
from api.schema.property import BasePoints, IndividualValues
from api.schema.nature import Nature

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


class PokemonEntity(BaseModel):
    id: int
    level: int
    basepoint: BasePoints
    indiviudual_values: IndividualValues
    nature: Nature
    ability_index: int
    item_index: int

        