from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class MoveFlagMap(Base):
    __tablename__ = 'move_flag_map'
    move_id: Mapped[int] = mapped_column(Integer, nullable=False)
    move_flag_id: Mapped[int] = mapped_column(Integer, nullable=False)
