from typing import Optional
from enum import Enum, unique
from pokemon_battle_inference.domain.models.types import Type
from pydantic import BaseModel


@unique
class MoveType(Enum):
    physical_move = "physical_move"
    special_move = "special_move"
    status_move = "status_move"

    @staticmethod
    def get_attack_move():
        return [MoveType.special_move, MoveType.physical_move]


# TODO: 技能Move类需要加上校验，若为物理或特殊技能，则power必定不可空
class Move(BaseModel):
    power: Optional[int] = None
    type: Type
    move_type: MoveType
