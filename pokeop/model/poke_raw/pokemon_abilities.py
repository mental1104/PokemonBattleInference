from __future__ import annotations

from sqlalchemy import Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonAbilities(Base):
    __tablename__ = 'pokemon_abilities'
    pokemon_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ability_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
