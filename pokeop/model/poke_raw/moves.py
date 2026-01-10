from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Moves(Base):
    __tablename__ = 'moves'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    power: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pp: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    priority: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    damage_class_id: Mapped[int] = mapped_column(Integer, nullable=False)
    effect_id: Mapped[int] = mapped_column(Integer, nullable=False)
    effect_chance: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    contest_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contest_effect_id: Mapped[int] = mapped_column(Integer, nullable=False)
    super_contest_effect_id: Mapped[int] = mapped_column(Integer, nullable=False)
