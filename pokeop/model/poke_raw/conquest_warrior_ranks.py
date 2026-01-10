from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestWarriorRanks(Base):
    __tablename__ = 'conquest_warrior_ranks'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warrior_id: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_id: Mapped[int] = mapped_column(Integer, nullable=False)
