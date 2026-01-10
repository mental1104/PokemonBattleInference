# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class MoveDamageClassProse(Base):
    __tablename__ = 'move_damage_class_prose'
    move_damage_class_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

__all__ = ['MoveDamageClassProse']
