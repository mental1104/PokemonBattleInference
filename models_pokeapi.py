# Auto-generated. DO NOT EDIT BY HAND.
# Re-generate via: python gen_sa_models.py <csv_dir> <out_py>
from __future__ import annotations

from typing import Optional
from sqlalchemy import Boolean, Integer, Text, ForeignKey, PrimaryKeyConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Pokemon(Base):
    __tablename__ = 'pokemon'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(Text, nullable=False)
    species_id: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    base_experience: Mapped[int] = mapped_column(Integer, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False)

class PokemonStats(Base):
    __tablename__ = 'pokemon_stats'
    __table_args__ = (PrimaryKeyConstraint('pokemon_id', 'stat_id'),)
    pokemon_id: Mapped[int] = mapped_column(Integer, ForeignKey("pokemon.id"), nullable=False)
    stat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    base_stat: Mapped[int] = mapped_column(Integer, nullable=False)
    effort: Mapped[int] = mapped_column(Integer, nullable=False)
