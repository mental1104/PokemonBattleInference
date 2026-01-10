from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class MoveMetaStatChanges(Base):
    __tablename__ = 'move_meta_stat_changes'
    move_id: Mapped[int] = mapped_column(Integer, nullable=False)
    stat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    change: Mapped[str] = mapped_column(Text, nullable=False)
