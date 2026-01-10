from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class MoveFlavorText(Base):
    __tablename__ = 'move_flavor_text'
    move_id: Mapped[int] = mapped_column(Integer, nullable=False)
    version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    flavor_text: Mapped[str] = mapped_column(Text, nullable=False)
