# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonMoves(Base):
    __tablename__ = 'pokemon_moves'
    pokemon_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    version_group_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    move_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    pokemon_move_method_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    level: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    order: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    mastery: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

__all__ = ['PokemonMoves']
