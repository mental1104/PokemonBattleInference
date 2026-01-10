# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class LocationAreas(Base):
    __tablename__ = 'location_areas'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    location_id: Mapped[int] = mapped_column(Integer, nullable=False)
    game_index: Mapped[int] = mapped_column(Integer, nullable=False)
    identifier: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

__all__ = ['LocationAreas']
