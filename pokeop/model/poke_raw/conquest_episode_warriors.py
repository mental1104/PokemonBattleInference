# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestEpisodeWarriors(Base):
    __tablename__ = 'conquest_episode_warriors'
    episode_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    warrior_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['ConquestEpisodeWarriors']
