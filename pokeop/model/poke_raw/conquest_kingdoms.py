# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestKingdoms(Base):
    __tablename__ = 'conquest_kingdoms'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    type_id: Mapped[int] = mapped_column(Integer, nullable=False)

__all__ = ['ConquestKingdoms']
