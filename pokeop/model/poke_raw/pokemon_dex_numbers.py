# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonDexNumbers(Base):
    __tablename__ = 'pokemon_dex_numbers'
    _species_id: Mapped[int] = mapped_column("﻿species_id", Integer, primary_key=True, nullable=False)
    pokedex_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    pokedex_number: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['PokemonDexNumbers']
