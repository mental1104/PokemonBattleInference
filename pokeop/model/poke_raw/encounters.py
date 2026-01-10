# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Encounters(Base):
    __tablename__ = 'encounters'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    location_area_id: Mapped[int] = mapped_column(Integer, nullable=False)
    encounter_slot_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pokemon_id: Mapped[int] = mapped_column(Integer, nullable=False)
    min_level: Mapped[int] = mapped_column(Integer, nullable=False)
    max_level: Mapped[int] = mapped_column(Integer, nullable=False)

__all__ = ['Encounters']
