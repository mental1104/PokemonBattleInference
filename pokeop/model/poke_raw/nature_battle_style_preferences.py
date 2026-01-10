from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class NatureBattleStylePreferences(Base):
    __tablename__ = 'nature_battle_style_preferences'
    nature_id: Mapped[int] = mapped_column(Integer, nullable=False)
    move_battle_style_id: Mapped[int] = mapped_column(Integer, nullable=False)
    low_hp_preference: Mapped[int] = mapped_column(Integer, nullable=False)
    high_hp_preference: Mapped[int] = mapped_column(Integer, nullable=False)
