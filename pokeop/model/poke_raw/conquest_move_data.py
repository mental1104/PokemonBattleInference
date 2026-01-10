# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestMoveData(Base):
    __tablename__ = 'conquest_move_data'
    move_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    power: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    accuracy: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    effect_chance: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    effect_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    range_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    displacement_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['ConquestMoveData']
