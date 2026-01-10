# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonSpeciesFlavorText(Base):
    __tablename__ = 'pokemon_species_flavor_text'
    species_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    language_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    flavor_text: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

__all__ = ['PokemonSpeciesFlavorText']
