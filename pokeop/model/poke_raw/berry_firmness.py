from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class BerryFirmness(Base):
    __tablename__ = 'berry_firmness'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
