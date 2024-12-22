from pydantic import BaseModel
from typing import Optional
from enum import Enum

class CommonProperty(BaseModel):
    id: int
    name: str
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int
    hp: int


class Attacker(CommonProperty):
    pass


class Defender(CommonProperty):
    pass

# 定义枚举
class DamageResponsibility(Enum):
    BASIC_DAMAGE = "basic_damage"
    RANDOM_MODIFIER = "random_modifier"
    TYPE_STAT = "type_stat"
    TYPE_EFFICIENCY = "type_efficiency"
    PERCENT = "percent"