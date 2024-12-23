from pydantic import BaseModel
from enum import Enum, unique

type_efficacy = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 100, 100, 100, 100, 100, 50, 100, 0, 50, 100, 100, 100, 100, 100, 100, 100, 100, 100],
    [0, 200, 100, 50, 50, 100, 200, 50, 0, 200, 100, 100, 100, 100, 50, 200, 100, 200, 50],
    [0, 100, 200, 100, 100, 100, 50, 200, 100, 50, 100, 100, 200, 50, 100, 100, 100, 100, 100],
    [0, 100, 100, 100, 50, 50, 50, 100, 50, 0, 100, 100, 200, 100, 100, 100, 100, 100, 200],
    [0, 100, 100, 0, 200, 100, 200, 50, 100, 200, 200, 100, 50, 200, 100, 100, 100, 100, 100],
    [0, 100, 50, 200, 100, 50, 100, 200, 100, 50, 200, 100, 100, 100, 100, 200, 100, 100, 100],
    [0, 100, 50, 50, 50, 100, 100, 100, 50, 50, 50, 100, 200, 100, 200, 100, 100, 200, 50],
    [0, 0, 100, 100, 100, 100, 100, 100, 200, 100, 100, 100, 100, 100, 200, 100, 100, 50, 100],
    [0, 100, 100, 100, 100, 100, 200, 100, 100, 50, 50, 50, 100, 50, 100, 200, 100, 100, 200],
    [0, 100, 100, 100, 100, 100, 50, 200, 100, 200, 50, 50, 200, 100, 100, 200, 50, 100, 100],
    [0, 100, 100, 100, 100, 200, 200, 100, 100, 100, 200, 50, 50, 100, 100, 100, 50, 100, 100],
    [0, 100, 100, 50, 50, 200, 200, 50, 100, 50, 50, 200, 50, 100, 100, 100, 50, 100, 100],
    [0, 100, 100, 200, 100, 0, 100, 100, 100, 100, 100, 200, 50, 50, 100, 100, 50, 100, 100],
    [0, 100, 200, 100, 200, 100, 100, 100, 100, 50, 100, 100, 100, 100, 50, 100, 100, 0, 100],
    [0, 100, 100, 200, 100, 200, 100, 100, 100, 50, 50, 50, 200, 100, 100, 50, 200, 100, 100],
    [0, 100, 100, 100, 100, 100, 100, 100, 100, 50, 100, 100, 100, 100, 100, 100, 200, 100, 0],
    [0, 100, 50, 100, 100, 100, 100, 100, 200, 100, 100, 100, 100, 100, 200, 100, 100, 50, 50],
    [0, 100, 200, 100, 50, 100, 100, 100, 100, 50, 50, 100, 100, 100, 100, 100, 200, 200, 100]
]


@unique
class Type(Enum):
    NORMAL = 1
    FIGHTING = 2
    FLYING = 3
    POISON = 4
    GROUND = 5
    ROCK = 6
    BUG = 7
    GHOST = 8
    STEEL = 9
    FIRE = 10
    WATER = 11
    GRASS = 12
    ELECTRIC = 13
    PSYCHIC = 14
    ICE = 15
    DRAGON = 16
    DARK = 17
    FAIRY = 18

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return self is other
        return self.value == other

    @classmethod
    def from_string(cls, name: str):
        try:
            return cls[name.upper()]
        except KeyError:
            raise ValueError(f"{name} is not a valid {cls.__name__}")

class TypesCreate(BaseModel):
    id: int
    name: str

class TypeHelper:

    @staticmethod
    def get_type_efficacy(attacker: Type, defenser: Type):
        attacker_value = 0
        defenser_value = 0
        if isinstance(attacker, Type):
            attacker_value = attacker.value
        elif isinstance(attacker, int):
            attacker_value = attacker
        
        if isinstance(defenser, Type):
            defenser_value = defenser.value
        elif isinstance(defenser, int):
            defenser_value = defenser

        return type_efficacy[attacker_value][defenser_value]