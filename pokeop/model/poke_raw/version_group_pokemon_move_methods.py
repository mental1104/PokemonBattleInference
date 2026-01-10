from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class VersionGroupPokemonMoveMethods(Base):
    __tablename__ = 'version_group_pokemon_move_methods'
    version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pokemon_move_method_id: Mapped[int] = mapped_column(Integer, nullable=False)
