# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonSpecies(Base):
    __tablename__ = 'pokemon_species'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    evolves_from_species_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    evolution_chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    color_id: Mapped[int] = mapped_column(Integer, nullable=False)
    shape_id: Mapped[int] = mapped_column(Integer, nullable=False)
    habitat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gender_rate: Mapped[str] = mapped_column(Text, nullable=False)
    capture_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    base_happiness: Mapped[int] = mapped_column(Integer, nullable=False)
    is_baby: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hatch_counter: Mapped[int] = mapped_column(Integer, nullable=False)
    has_gender_differences: Mapped[bool] = mapped_column(Boolean, nullable=False)
    growth_rate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    forms_switchable: Mapped[int] = mapped_column(Integer, nullable=False)
    is_legendary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_mythical: Mapped[bool] = mapped_column(Boolean, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    conquest_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

__all__ = ['PokemonSpecies']
