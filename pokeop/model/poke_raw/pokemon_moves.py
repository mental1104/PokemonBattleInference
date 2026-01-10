from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonMoves(Base):
    __tablename__ = 'pokemon_moves'
    pokemon_id: Mapped[int] = mapped_column(Integer, nullable=False)
    version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    move_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pokemon_move_method_id: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mastery: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
