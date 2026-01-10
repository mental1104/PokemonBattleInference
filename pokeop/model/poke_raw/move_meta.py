# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class MoveMeta(Base):
    __tablename__ = 'move_meta'
    move_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    meta_category_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    meta_ailment_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    min_hits: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    max_hits: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    min_turns: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    drain: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    healing: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    crit_rate: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    ailment_chance: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    flinch_chance: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    stat_chance: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['MoveMeta']
