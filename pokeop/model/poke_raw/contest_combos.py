from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ContestCombos(Base):
    __tablename__ = 'contest_combos'
    first_move_id: Mapped[int] = mapped_column(Integer, nullable=False)
    second_move_id: Mapped[int] = mapped_column(Integer, nullable=False)
