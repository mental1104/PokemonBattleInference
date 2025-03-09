from db import Base
from schema.pokemon import PokemonCreate
from sqlalchemy import Column, Integer, String, ARRAY
import logging

class Pokemon(Base):
    __tablename__ = 'pokemon'
    id = Column(Integer, primary_key=True, comment="主键")
    name = Column(String, comment="宝可梦默认名")
    type_1 = Column(Integer, comment="第一属性")
    type_2 = Column(Integer, comment="第二属性", nullable=True)
    hp = Column(Integer, comment="体力种族值")
    attack = Column(Integer, comment="攻击种族值")
    defense = Column(Integer, comment="防御种族值")
    special_attack = Column(Integer, comment="特攻种族值")
    special_defense = Column(Integer, comment="特防种族值")
    speed = Column(Integer, comment="速度种族值")
    move_ids = Column(ARRAY(Integer), comment="技能id")
    ability = Column(ARRAY(Integer), comment="特性列表")

    @staticmethod
    def count(session):
        return session.count(Pokemon).scalar()
        
    @staticmethod
    def create(session, pokemon: PokemonCreate):
        ret = session.add(Pokemon(
            id=pokemon.id,
            name=pokemon.name,
            type_1=pokemon.type_1,
            type_2=pokemon.type_2,
            hp=pokemon.hp,
            attack=pokemon.attack,
            defense=pokemon.defense,
            special_attack=pokemon.special_attack,
            special_defense=pokemon.special_defense,
            speed=pokemon.speed,
            move_ids=pokemon.move_ids,
            ability=pokemon.ability
        ))
        logging.info(ret)
        logging.info(ret)
    
    @staticmethod
    def get_by_id(session, idx):
        res = session.query(Pokemon).filter(Pokemon.id == idx)
        res = res.first()
        return res

