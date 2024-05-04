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


class MoveType:
    physical_move = "physical_move"
    special_move = "special_move"
    status_move =  "status_move"

class Move:
    power: Optional[int] = None
    move_type: MoveType