# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestPokemonEvolution(Base):
    __tablename__ = 'conquest_pokemon_evolution'
    evolved_species_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    required_stat_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    minimum_stat: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    minimum_link: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    kingdom_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    warrior_gender_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    recruiting_ko_required: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['ConquestPokemonEvolution']
