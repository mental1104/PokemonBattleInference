from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestMaxLinks(Base):
    __tablename__ = 'conquest_max_links'
    warrior_rank_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pokemon_species_id: Mapped[int] = mapped_column(Integer, nullable=False)
    max_link: Mapped[int] = mapped_column(Integer, nullable=False)
