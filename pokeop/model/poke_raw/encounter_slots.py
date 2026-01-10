# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class EncounterSlots(Base):
    __tablename__ = 'encounter_slots'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    encounter_method_id: Mapped[int] = mapped_column(Integer, nullable=False)
    slot: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rarity: Mapped[int] = mapped_column(Integer, nullable=False)

__all__ = ['EncounterSlots']
