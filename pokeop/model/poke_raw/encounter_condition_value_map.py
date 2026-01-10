from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class EncounterConditionValueMap(Base):
    __tablename__ = 'encounter_condition_value_map'
    encounter_id: Mapped[int] = mapped_column(Integer, nullable=False)
    encounter_condition_value_id: Mapped[int] = mapped_column(Integer, nullable=False)
