from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class MoveChangelog(Base):
    __tablename__ = 'move_changelog'
    move_id: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_in_version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    power: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    accuracy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    effect_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    effect_chance: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
