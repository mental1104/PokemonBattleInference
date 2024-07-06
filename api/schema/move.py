from typing import Optional
from enum import Enum, unique
from api.schema.types import Type
from pydantic import BaseModel

@unique
class MoveType(Enum):
    physical_move = "physical_move"
    special_move = "special_move"
    status_move = "status_move"


class Move(BaseModel):
    power: Optional[int] = None
    type: Type
    move_type: MoveType
