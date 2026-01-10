# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokeathlonStatNames(Base):
    __tablename__ = 'pokeathlon_stat_names'
    pokeathlon_stat_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

__all__ = ['PokeathlonStatNames']
