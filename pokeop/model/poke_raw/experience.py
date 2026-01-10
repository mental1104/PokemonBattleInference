# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Experience(Base):
    __tablename__ = 'experience'
    growth_rate_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    level: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    experience: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['Experience']
