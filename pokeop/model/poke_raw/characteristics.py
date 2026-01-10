# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Characteristics(Base):
    __tablename__ = 'characteristics'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    stat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gene_mod_5: Mapped[int] = mapped_column(Integer, nullable=False)

__all__ = ['Characteristics']
