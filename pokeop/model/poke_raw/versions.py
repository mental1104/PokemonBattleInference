from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Versions(Base):
    __tablename__ = 'versions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
