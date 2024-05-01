from db import Base
from sqlalchemy import Column, Integer, String

class Pokemon(Base):
    __tablename__ = 'pokemon'
    __table_args__ = {"mysql_charset": "utf8"}
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    ylmsn = Column(String, comment="test")