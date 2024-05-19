from typing import Optional


class MoveType:
    physical_move = "physical_move"
    special_move = "special_move"
    status_move =  "status_move"


class Move:
    power: Optional[int] = None
    move_type: MoveType
