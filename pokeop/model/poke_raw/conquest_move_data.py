from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestMoveData(Base):
    __tablename__ = 'conquest_move_data'
    move_id: Mapped[int] = mapped_column(Integer, nullable=False)
    power: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    accuracy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    effect_chance: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    effect_id: Mapped[int] = mapped_column(Integer, nullable=False)
    range_id: Mapped[int] = mapped_column(Integer, nullable=False)
    displacement_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
