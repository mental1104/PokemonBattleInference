from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class TypeNames(Base):
    __tablename__ = 'type_names'
    type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
