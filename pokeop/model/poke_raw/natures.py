# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Natures(Base):
    __tablename__ = 'natures'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    decreased_stat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    increased_stat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    hates_flavor_id: Mapped[int] = mapped_column(Integer, nullable=False)
    likes_flavor_id: Mapped[int] = mapped_column(Integer, nullable=False)
    game_index: Mapped[int] = mapped_column(Integer, nullable=False)

__all__ = ['Natures']
