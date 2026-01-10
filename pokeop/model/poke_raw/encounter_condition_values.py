from __future__ import annotations

from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class EncounterConditionValues(Base):
    __tablename__ = 'encounter_condition_values'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    encounter_condition_id: Mapped[int] = mapped_column(Integer, nullable=False)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False)
