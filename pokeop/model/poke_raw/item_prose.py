from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ItemProse(Base):
    __tablename__ = 'item_prose'
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    short_effect: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effect: Mapped[str] = mapped_column(Text, nullable=False)
