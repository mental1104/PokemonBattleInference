# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class NaturePokeathlonStats(Base):
    __tablename__ = 'nature_pokeathlon_stats'
    nature_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    pokeathlon_stat_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    max_change: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

__all__ = ['NaturePokeathlonStats']
