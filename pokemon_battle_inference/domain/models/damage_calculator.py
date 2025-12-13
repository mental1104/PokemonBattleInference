import json
from pydantic import BaseModel
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


class DamageResult:
    formula: str = ""
    min_damage: int = 0
    max_damage = 0
    random_damage: int = 0
    min_damage_percent: float = 0.0
    max_damage_percent: float = 0.0
    random_damage_percent: float = 0.0

    def __init__(
        self,
        formula="",
        min_damage=0,
        max_damage=0,
        random_damage=0,
        min_damage_percent=0.0,
        max_damage_percent=0.0,
        random_damage_percent=0.0,
    ):
        self.formula = formula
        self.min_damage = min_damage
        self.max_damage = max_damage
        self.random_damage = random_damage
        self.min_damage_percent = min_damage_percent
        self.max_damage_percent = max_damage_percent
        self.random_damage_percent = random_damage_percent

    def __str__(self):
        # 将类实例转换为 JSON 字符串，格式化输出便于阅读
        return json.dumps(self.__dict__, indent=4, ensure_ascii=False)

    def __repr__(self):
        # 返回更简洁的 JSON 字符串
        return json.dumps(self.__dict__)

    def __mul__(self, other):
        return DamageResult(
            "",
            int(self.min_damage * other),
            int(self.max_damage * other),
            int(self.random_damage * other),
        )

    def __imul__(self, other):
        min_damage = int(self.min_damage * other)
        self.min_damage = min_damage

        max_damage = int(self.max_damage * other)
        self.max_damage = max_damage

        random_damage = int(self.random_damage * other)
        self.random_damage = random_damage

        return self
