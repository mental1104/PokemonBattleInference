# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestPokemonStats(Base):
    __tablename__ = 'conquest_pokemon_stats'
    pokemon_species_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    conquest_stat_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    base_stat: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['ConquestPokemonStats']
