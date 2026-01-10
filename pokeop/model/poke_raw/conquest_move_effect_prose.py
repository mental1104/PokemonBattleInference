# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestMoveEffectProse(Base):
    __tablename__ = 'conquest_move_effect_prose'
    conquest_move_effect_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    short_effect: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    effect: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

__all__ = ['ConquestMoveEffectProse']
