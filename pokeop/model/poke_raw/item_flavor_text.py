from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ItemFlavorText(Base):
    __tablename__ = 'item_flavor_text'
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    flavor_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
