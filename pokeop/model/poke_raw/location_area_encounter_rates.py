# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class LocationAreaEncounterRates(Base):
    __tablename__ = 'location_area_encounter_rates'
    location_area_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    encounter_method_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    rate: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['LocationAreaEncounterRates']
