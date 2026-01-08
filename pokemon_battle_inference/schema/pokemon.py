from enum import Enum
from typing import Dict, Tuple


class StatField(str, Enum):
    HP = "hp"
    ATTACK = "attack"
    DEFENSE = "defense"
    SPECIAL_ATTACK = "special_attack"
    SPECIAL_DEFENSE = "special_defense"
    SPEED = "speed"


class TypeSlotField(str, Enum):
    TYPE_1 = "type_1"
    TYPE_2 = "type_2"


STAT_FIELDS: Tuple[str, ...] = tuple(field.value for field in StatField)
STAT_ID_TO_FIELD: Dict[str, str] = {
    str(index): field.value for index, field in enumerate(StatField, start=1)
}
TYPE_SLOT_TO_FIELD: Dict[str, str] = {
    "1": TypeSlotField.TYPE_1.value,
    "2": TypeSlotField.TYPE_2.value,
}
