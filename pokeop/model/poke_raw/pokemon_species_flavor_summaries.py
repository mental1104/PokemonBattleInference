from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonSpeciesFlavorSummaries(Base):
    __tablename__ = 'pokemon_species_flavor_summaries'
    pokemon_species_id: Mapped[int] = mapped_column(Integer, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    flavor_summary: Mapped[str] = mapped_column(Text, nullable=False)
