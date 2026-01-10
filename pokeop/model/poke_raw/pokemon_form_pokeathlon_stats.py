from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonFormPokeathlonStats(Base):
    __tablename__ = 'pokemon_form_pokeathlon_stats'
    pokemon_form_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pokeathlon_stat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_stat: Mapped[int] = mapped_column(Integer, nullable=False)
    base_stat: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_stat: Mapped[int] = mapped_column(Integer, nullable=False)
