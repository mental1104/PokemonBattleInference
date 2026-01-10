# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class PokemonForms(Base):
    __tablename__ = 'pokemon_forms'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    form_identifier: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pokemon_id: Mapped[int] = mapped_column(Integer, nullable=False)
    introduced_in_version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_battle_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_mega: Mapped[bool] = mapped_column(Boolean, nullable=False)
    form_order: Mapped[int] = mapped_column(Integer, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)

__all__ = ['PokemonForms']
