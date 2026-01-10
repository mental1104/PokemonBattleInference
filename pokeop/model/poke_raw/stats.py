# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Stats(Base):
    __tablename__ = 'stats'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    damage_class_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    is_battle_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    game_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

__all__ = ['Stats']
