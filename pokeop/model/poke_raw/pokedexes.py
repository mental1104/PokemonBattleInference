# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Pokedexes(Base):
    __tablename__ = 'pokedexes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    region_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    is_main_series: Mapped[bool] = mapped_column(Boolean, nullable=False)

__all__ = ['Pokedexes']
