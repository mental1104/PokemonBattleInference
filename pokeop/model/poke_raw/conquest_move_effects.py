from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestMoveEffects(Base):
    __tablename__ = 'conquest_move_effects'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
