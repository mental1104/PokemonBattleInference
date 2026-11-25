from enum import Enum
from pydantic import BaseModel
from typing import Any, Dict, Union, List


class CommonProperty(BaseModel):
    hp: int = 0
    attack: int = 0
    defense: int = 0
    special_attack: int = 0
    special_defense: int = 0
    speed: int = 0

    @classmethod
    def create(cls, data: Union[Dict[str, Any], str, List[int], tuple]):
        if isinstance(data, dict):
            # 如果数据是字典，直接使用字典进行初始化
            return cls(**data)
        elif isinstance(data, str):
            # 如果数据是字符串，根据自定义逻辑进行处理
            return cls()
        elif isinstance(data, list) or isinstance(data, tuple):
            # 如果数据是整数，可以设定默认值进行初始化
            if len(data) < 6:
                raise ValueError("List must be greater than or equal to 6")
            return cls(
                hp=data[0],
                attack=data[1],
                defense=data[2],
                special_attack=data[3],
                special_defense=data[4],
                speed=data[5]
            )
        else:
            raise TypeError("Unsupported data type for initialization")


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


class PropertyEnum(str, Enum):
    HP = "hp"
    ATTACK = "attack"
    DEFENSE = "defense"
    SPECIAL_ATTACK = "special_attack"
    SPECIAL_DEFENSE = "special_defense"
    SPEED = "speed"
