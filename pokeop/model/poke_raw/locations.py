from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Locations(Base):
    __tablename__ = 'locations'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
