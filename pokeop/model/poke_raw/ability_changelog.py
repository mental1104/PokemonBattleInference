from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class AbilityChangelog(Base):
    __tablename__ = 'ability_changelog'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ability_id: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_in_version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
