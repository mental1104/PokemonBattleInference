# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonStats(Base):
    __tablename__ = 'pokemon_stats'
    pokemon_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    stat_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    base_stat: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    effort: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['PokemonStats']
