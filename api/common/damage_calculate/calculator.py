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
        attacker_copy = copy.deepcopy(attacker)
        defenser_copy = copy.deepcopy(defenser)
        move_copy = copy.deepcopy(move)

        # 初始化结果
        initial_result = DamageResult()
        
        # 设置攻击者、防御者和招式到责任链中
        curr = self.modifier
        while curr:
            curr.attacker = attacker_copy
            curr.defenser = defenser_copy
            curr.move = move_copy
            curr = curr.next

        # 从责任链开始传递
        final_result = self.modifier.handle(initial_result)
        return final_result

    def calculate(self, attacker: PokemonEntity, defenser: PokemonEntity, move: Move):
        result = self.__refresh(attacker, defenser, move)
        self.modifier.handle(result)
        return result
