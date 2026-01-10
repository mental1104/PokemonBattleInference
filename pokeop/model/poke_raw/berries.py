from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Berries(Base):
    __tablename__ = 'berries'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    firmness_id: Mapped[int] = mapped_column(Integer, nullable=False)
    natural_gift_power: Mapped[int] = mapped_column(Integer, nullable=False)
    natural_gift_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    max_harvest: Mapped[int] = mapped_column(Integer, nullable=False)
    growth_time: Mapped[int] = mapped_column(Integer, nullable=False)
    soil_dryness: Mapped[int] = mapped_column(Integer, nullable=False)
    smoothness: Mapped[int] = mapped_column(Integer, nullable=False)
