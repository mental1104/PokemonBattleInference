from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokedexVersionGroups(Base):
    __tablename__ = 'pokedex_version_groups'
    pokedex_id: Mapped[int] = mapped_column(Integer, nullable=False)
    version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
