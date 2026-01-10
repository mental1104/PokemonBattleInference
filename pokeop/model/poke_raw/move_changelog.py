# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class MoveChangelog(Base):
    __tablename__ = 'move_changelog'
    move_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    changed_in_version_group_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    type_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    power: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    pp: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    accuracy: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    priority: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    effect_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    effect_chance: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['MoveChangelog']
