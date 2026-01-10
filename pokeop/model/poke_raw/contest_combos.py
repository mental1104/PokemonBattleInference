# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ContestCombos(Base):
    __tablename__ = 'contest_combos'
    first_move_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    second_move_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['ContestCombos']
