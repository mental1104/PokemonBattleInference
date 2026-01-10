# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonAbilities(Base):
    __tablename__ = 'pokemon_abilities'
    pokemon_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    ability_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, primary_key=True, nullable=False)
    slot: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['PokemonAbilities']
