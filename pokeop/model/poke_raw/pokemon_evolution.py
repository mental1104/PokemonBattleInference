# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonEvolution(Base):
    __tablename__ = 'pokemon_evolution'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    evolved_species_id: Mapped[int] = mapped_column(Integer, nullable=False)
    evolution_trigger_id: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minimum_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gender_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    location_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    held_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    time_of_day: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    known_move_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    known_move_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minimum_happiness: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minimum_beauty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minimum_affection: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    relative_physical_stats: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    party_species_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    party_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trade_species_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    needs_overworld_rain: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_upside_down: Mapped[int] = mapped_column(Integer, nullable=False)
    region_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    base_form_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

__all__ = ['PokemonEvolution']
