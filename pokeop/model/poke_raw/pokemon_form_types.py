# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonFormTypes(Base):
    __tablename__ = 'pokemon_form_types'
    pokemon_form_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    type_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    slot: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['PokemonFormTypes']
