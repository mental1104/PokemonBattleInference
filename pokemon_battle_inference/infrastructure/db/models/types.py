from sqlalchemy import Column, Integer, String

from pokemon_battle_inference.infrastructure.db import Base, with_session
from pokemon_battle_inference.domain.models.types import TypesCreate

class Types(Base):
    __tablename__ = 'types'
    __table_args__ = {"mysql_charset": "utf8"}
    id = Column(Integer, primary_key=True, comment="主键")
    name = Column(String, comment="属性名")
    
    @classmethod
    @with_session
    def create(cls, pokemon: TypesCreate, session=None):
        session.add(cls(
            id=pokemon.id,
            name=pokemon.name,
        ))
