from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonAbilitiesPast(Base):
    __tablename__ = 'pokemon_abilities_past'
    pokemon_id: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ability_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
