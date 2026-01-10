from __future__ import annotations

from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestStats(Base):
    __tablename__ = 'conquest_stats'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    is_base: Mapped[bool] = mapped_column(Boolean, nullable=False)
