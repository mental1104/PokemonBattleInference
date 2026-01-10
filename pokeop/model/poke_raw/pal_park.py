from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PalPark(Base):
    __tablename__ = 'pal_park'
    species_id: Mapped[int] = mapped_column(Integer, nullable=False)
    area_id: Mapped[int] = mapped_column(Integer, nullable=False)
    base_score: Mapped[int] = mapped_column(Integer, nullable=False)
    rate: Mapped[int] = mapped_column(Integer, nullable=False)
