import copy
import math
from api.schema.pokemon import PokemonEntity
from api.schema.move import Move, MoveType
from api.schema.types import TypeHelper
import logging
import random


def calculate(attacker: PokemonEntity, defenser: PokemonEntity, move: Move):
    if move.move_type == MoveType.special_move or move.move_type == MoveType.physical_move:
        damage = int((2 * attacker.level + 10)/250.0 * attacker.stat.special_attack / defenser.stat.special_defense * 90 + 2)
        # 本系一致加成
        if move.type in [attacker.type_1, attacker.type_2]:
            damage *= 1.5
        # 属性克制计算
        type_multiplier = 1.0
        type_multiplier *= TypeHelper.get_type_efficacy(move.type, defenser.type_1) / 100.0
        logging.info(type_multiplier)
        if defenser.type_2:
            type_multiplier *= TypeHelper.get_type_efficacy(move.type, defenser.type_2) / 100.0
        damage *= type_multiplier
    else:
        damage = 0
    
    return int(damage * 0.85), int(damage)

def calculate_percentage(attacker: PokemonEntity, defenser: PokemonEntity, move: Move):
    min_damage, max_damage = calculate(attacker, defenser, move)
    return (float(min_damage)/defenser.stat.hp, float(max_damage)/defenser.stat.hp)


class DamageResult:
    formula: str = ""
    min_damage: int = 0
    max_damage = 0
    random_damage: int  = 0.0
    min_damage_percent: float  = 0.0
    max_damage_percent: float = 0.0
    random_damage_percent: float  = 0.0


class DamageLinkage:
    
    def __init__(self):
        self.next = None
        self.env = None
        self.attacker = None
        self.defenser = None
        self.result = None
        self.move = None
    
    def set(self, attacker: PokemonEntity, defenser: PokemonEntity, move: Move, result: DamageResult):
        self.attacker = attacker
        self.defenser = defenser
        self.result = result
        self.move = move
        
    def add(self, damage_linker):
        if self.next:
            self.next.add(damage_linker)
        else:
            self.next = damage_linker
            
    def handle(self):
        if self.next:
            self.next.handle()
    

class TypeStatModifier(DamageLinkage):
    
    def handle(self):
        if self.move.move_type.get_attack_move() and \
            (self.attacker.type_1 == self.move.type or self.attacker.type_2 == self.move.type):
            self.result.max_damage *= 1.5
            logging.info(self.result.max_damage)
            
        super().handle()


class TypeEfficiencyModifier(DamageLinkage):

    def handle(self):
        type_multiplier = 1.0
        type_multiplier *= TypeHelper.get_type_efficacy(self.move.type, self.defenser.type_1) / 100.0
        logging.info(type_multiplier)
        if self.defenser.type_2:
            type_multiplier *= TypeHelper.get_type_efficacy(self.move.type, self.defenser.type_2) / 100.0

        self.result.max_damage *= type_multiplier
        super().handle()

class BasicDamageModifier(DamageLinkage):
    
    def handle(self):
        if self.move.move_type in MoveType.get_attack_move():
            # 神秘之剑，扑击，精神冲击等需要额外考虑，这里先临时写死，后面有专门的逻辑处理这一块
            attack = self.attacker.stat.attack if self.move.move_type == MoveType.physical_move else self.attacker.stat.special_attack
            defense = self.attacker.stat.defense if self.move.move_type == MoveType.physical_move else self.defenser.stat.special_defense
            damage = (2 * self.attacker.level + 10)/250.0 * attack / defense * self.move.power + 2
            self.result.max_damage = damage

        super().handle()

class FinalModifier(DamageLinkage):
    
    def handle(self):
        damage = self.result.max_damage
        

        # TODO 0.85做成可配
        self.result.max_damage = int(damage)
        self.result.min_damage = int(damage * 0.85)

        self.result.max_damage_percent = math.floor(self.result.max_damage / self.defenser.stat.hp * 1000.0) / 10
        self.result.min_damage_percent = math.floor(self.result.min_damage / self.defenser.stat.hp * 1000.0) / 10

        multiplier = round(random.uniform(0.85, 1.0), 2)
        self.result.random_damage = int(damage * multiplier)
        self.result.random_damage_percent = math.floor(self.result.random_damage / self.defenser.stat.hp * 1000.0) / 10
        
        super().handle()


class DamageCalculatorFactory:

    @staticmethod
    def get(property: str):
        if   property == "type_stat":           return TypeStatModifier()
        elif property == "type_efficiency":     return TypeEfficiencyModifier()
        elif property == "basic_damage":        return BasicDamageModifier()
        elif property == "final_modifier":      return FinalModifier()
        else:
            logging.warning(f"AbilityCalculatorFactory not supported type: {property}!")
            return DamageLinkage()

class DamageCalculator:
    
    def __init__(self):
        self.responsibility_list = ["basic_damage", "type_stat", "type_efficiency", "final_modifier"]
        self.modifier = DamageLinkage()
        for item in self.responsibility_list:
            instance = DamageCalculatorFactory.get(item)
            self.modifier.add(instance)
    
    def __refresh(self, attacker, defenser, move):
        curr = self.modifier
        result = DamageResult()
        attacker_copy = copy.deepcopy(attacker)
        defenser_copy = copy.deepcopy(defenser)
        move_copy = copy.deepcopy(move)
        while(curr):
            curr.set(attacker_copy, defenser_copy, move_copy, result)
            curr = curr.next
        return result

    def calculate(self, attacker: PokemonEntity, defenser: PokemonEntity, move: Move):
        result = self.__refresh(attacker, defenser, move)
        self.modifier.handle()
        return result
        