# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestEpisodeNames(Base):
    __tablename__ = 'conquest_episode_names'
    episode_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

__all__ = ['ConquestEpisodeNames']
