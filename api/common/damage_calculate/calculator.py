import copy
from api.common.damage_calculate.factory import DamageCalculatorFactory
from api.common.damage_calculate.modifier_chain import BaseDamageChain, DamageResult
from api.schema.move import Move
from api.schema.pokemon import PokemonEntity

global_responsibility_list = [
    "basic_damage",
    "random_modifier",
    "type_stat",
    "type_efficiency",
    "percent"
]

class DamageCalculator:
    
    def __init__(self):
        self.responsibility_list = global_responsibility_list
        self.modifier = BaseDamageChain()
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
