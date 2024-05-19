from enum import Enum
from pydantic import BaseModel, field_validator 
from schema.nature import NatureHelper

class CommonProperty(BaseModel):
    hp: int = 0
    attack: int = 0
    defense: int = 0
    special_attack: int = 0
    special_defense: int = 0
    speed: int = 0

# 个体值
class IndividualValues(CommonProperty):
    pass

# 种族值
class SpeciesStrength(CommonProperty):
    pass

# 努力值
class BasePoints(CommonProperty):
    pass

# 最终能力值
class Statistic(CommonProperty):
    pass


class PropertyCalculator:
    @staticmethod
    def calculate_hp(level: int, species_strength: int, basepoint: int = 252, individual_values: int = 31):
        result = ((species_strength * 2 + individual_values + basepoint / 4) * level) / 100.0 + 10 + level
        return int(result)

    @staticmethod
    def calculate_ability(property, level: int, species_strength: int, basepoint: int = 252, individual_values: int = 31, nature: str = ""):
        result = (((species_strength * 2 + individual_values + basepoint / 4) * level) / 100.0 + 5) * NatureHelper.get_effectiveness(property.value, nature)
        return int(result)

class PropertyEnum(str, Enum):
    HP = "hp"
    ATTACK = "attack"
    DEFENSE = "defense"
    SPECIAL_ATTACK = "special_attack"
    SPECIAL_DEFENSE = "special_defense"
    SPEED = "speed"