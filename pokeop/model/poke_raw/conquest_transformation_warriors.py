from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ConquestTransformationWarriors(Base):
    __tablename__ = 'conquest_transformation_warriors'
    transformation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    present_warrior_id: Mapped[int] = mapped_column(Integer, nullable=False)
