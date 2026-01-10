from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class Machines(Base):
    __tablename__ = 'machines'
    machine_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    move_id: Mapped[int] = mapped_column(Integer, nullable=False)
