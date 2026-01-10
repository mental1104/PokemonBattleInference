# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestWarriorRankStatMap(Base):
    __tablename__ = 'conquest_warrior_rank_stat_map'
    warrior_rank_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    warrior_stat_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    base_stat: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['ConquestWarriorRankStatMap']
