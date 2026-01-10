# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class TypeEfficacyPast(Base):
    __tablename__ = 'type_efficacy_past'
    damage_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    target_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    damage_factor: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['TypeEfficacyPast']
