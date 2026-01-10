# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.model.poke_raw.base import Base


class VersionGroupRegions(Base):
    __tablename__ = 'version_group_regions'
    version_group_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    region_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)

__all__ = ['VersionGroupRegions']
