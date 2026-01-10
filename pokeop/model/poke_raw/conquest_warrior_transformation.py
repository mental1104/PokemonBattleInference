# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestWarriorTransformation(Base):
    __tablename__ = 'conquest_warrior_transformation'
    transformed_warrior_rank_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    is_automatic: Mapped[bool] = mapped_column(Boolean, primary_key=True, nullable=False)
    required_link: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    completed_episode_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    current_episode_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    distant_warrior_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    female_warlord_count: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    pokemon_count: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    collection_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    warrior_count: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['ConquestWarriorTransformation']
