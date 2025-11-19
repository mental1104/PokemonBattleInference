import logging

from sqlalchemy import ARRAY, Column, Integer, String

from pokemon_battle_inference.infrastructure.db import Base, with_session
from pokemon_battle_inference.domain.models.pokemon import PokemonCreate

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

    @classmethod
    @with_session
    def count(cls, session=None):
        return session.query(cls).count()
        
    @classmethod
    @with_session
    def create(cls, pokemon: PokemonCreate, session=None):
        instance = cls(
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
        )
        session.add(instance)
        logging.info("queued pokemon #%s for persistence", pokemon.id)
        return instance
    
    @classmethod
    @with_session
    def get_by_id(cls, idx, session=None):
        return session.query(cls).filter(cls.id == idx).first()
