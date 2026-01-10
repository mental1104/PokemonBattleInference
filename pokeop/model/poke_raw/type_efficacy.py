from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class TypeEfficacy(Base):
    __tablename__ = 'type_efficacy'
    damage_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    damage_factor: Mapped[int] = mapped_column(Integer, nullable=False)
