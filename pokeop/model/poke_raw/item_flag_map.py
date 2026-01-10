# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ItemFlagMap(Base):
    __tablename__ = 'item_flag_map'
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    item_flag_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['ItemFlagMap']
