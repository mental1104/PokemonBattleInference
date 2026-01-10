from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestWarriorTransformation(Base):
    __tablename__ = 'conquest_warrior_transformation'
    transformed_warrior_rank_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_automatic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_link: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_episode_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_episode_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    distant_warrior_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    female_warlord_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pokemon_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    collection_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    warrior_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
