from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonFormNames(Base):
    __tablename__ = 'pokemon_form_names'
    pokemon_form_id: Mapped[int] = mapped_column(Integer, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    form_name: Mapped[str] = mapped_column(Text, nullable=False)
    pokemon_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
