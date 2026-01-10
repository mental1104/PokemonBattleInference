from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class BerryFlavors(Base):
    __tablename__ = 'berry_flavors'
    berry_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contest_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    flavor: Mapped[int] = mapped_column(Integer, nullable=False)
