from __future__ import annotations

from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Abilities(Base):
    __tablename__ = 'abilities'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_main_series: Mapped[bool] = mapped_column(Boolean, nullable=False)
