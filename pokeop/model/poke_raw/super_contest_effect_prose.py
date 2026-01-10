from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class SuperContestEffectProse(Base):
    __tablename__ = 'super_contest_effect_prose'
    super_contest_effect_id: Mapped[int] = mapped_column(Integer, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    flavor_text: Mapped[str] = mapped_column(Text, nullable=False)
