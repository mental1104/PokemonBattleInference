from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ContestTypeNames(Base):
    __tablename__ = 'contest_type_names'
    contest_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    flavor: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
