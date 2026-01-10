# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonEggGroups(Base):
    __tablename__ = 'pokemon_egg_groups'
    species_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    egg_group_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['PokemonEggGroups']
