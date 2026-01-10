from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class MoveMeta(Base):
    __tablename__ = 'move_meta'
    move_id: Mapped[int] = mapped_column(Integer, nullable=False)
    meta_category_id: Mapped[int] = mapped_column(Integer, nullable=False)
    meta_ailment_id: Mapped[int] = mapped_column(Integer, nullable=False)
    min_hits: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_hits: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_turns: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_turns: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    drain: Mapped[str] = mapped_column(Text, nullable=False)
    healing: Mapped[str] = mapped_column(Text, nullable=False)
    crit_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    ailment_chance: Mapped[int] = mapped_column(Integer, nullable=False)
    flinch_chance: Mapped[int] = mapped_column(Integer, nullable=False)
    stat_chance: Mapped[int] = mapped_column(Integer, nullable=False)
