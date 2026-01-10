from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Languages(Base):
    __tablename__ = 'languages'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iso639: Mapped[str] = mapped_column(Text, nullable=False)
    iso3166: Mapped[str] = mapped_column(Text, nullable=False)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    official: Mapped[int] = mapped_column(Integer, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
