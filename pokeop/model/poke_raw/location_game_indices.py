# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class LocationGameIndices(Base):
    __tablename__ = 'location_game_indices'
    location_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    game_index: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['LocationGameIndices']
