# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class BerryFlavors(Base):
    __tablename__ = 'berry_flavors'
    berry_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    contest_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    flavor: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['BerryFlavors']
