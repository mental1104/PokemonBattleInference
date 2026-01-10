from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestPokemonEvolution(Base):
    __tablename__ = 'conquest_pokemon_evolution'
    evolved_species_id: Mapped[int] = mapped_column(Integer, nullable=False)
    required_stat_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minimum_stat: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minimum_link: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kingdom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    warrior_gender_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recruiting_ko_required: Mapped[int] = mapped_column(Integer, nullable=False)
