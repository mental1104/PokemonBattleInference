from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class ItemGameIndices(Base):
    __tablename__ = 'item_game_indices'
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    game_index: Mapped[int] = mapped_column(Integer, nullable=False)
