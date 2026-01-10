from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class SuperContestEffects(Base):
    __tablename__ = 'super_contest_effects'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appeal: Mapped[int] = mapped_column(Integer, nullable=False)
