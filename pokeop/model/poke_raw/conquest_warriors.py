# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestWarriors(Base):
    __tablename__ = 'conquest_warriors'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    gender_id: Mapped[int] = mapped_column(Integer, nullable=False)
    archetype_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

__all__ = ['ConquestWarriors']
