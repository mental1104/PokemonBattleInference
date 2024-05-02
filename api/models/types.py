from db import Base
from sqlalchemy import Column, Integer, String
from schema.types import TypesCreate

class Types(Base):
    __tablename__ = 'types'
    __table_args__ = {"mysql_charset": "utf8"}
    id = Column(Integer, primary_key=True, comment="主键")
    name = Column(String, comment="属性名")
    
    @staticmethod
    def create(session, pokemon: TypesCreate):
        session.add(Types(
            id=pokemon.id,
            name=pokemon.name,
        ))

