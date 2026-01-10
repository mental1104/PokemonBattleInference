# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class EvolutionChains(Base):
    __tablename__ = 'evolution_chains'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    baby_trigger_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

__all__ = ['EvolutionChains']
