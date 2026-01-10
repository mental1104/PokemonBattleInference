from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class AbilityChangelogProse(Base):
    __tablename__ = 'ability_changelog_prose'
    ability_changelog_id: Mapped[int] = mapped_column(Integer, nullable=False)
    local_language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    effect: Mapped[str] = mapped_column(Text, nullable=False)
