# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class TranslationsCs(Base):
    __tablename__ = 'translations_cs'
    language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    table: Mapped[str] = mapped_column(Text, nullable=False)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    column: Mapped[str] = mapped_column(Text, nullable=False)
    source_crc: Mapped[str] = mapped_column(Text, nullable=False)
    string: Mapped[str] = mapped_column(Text, nullable=False)

__all__ = ['TranslationsCs']
