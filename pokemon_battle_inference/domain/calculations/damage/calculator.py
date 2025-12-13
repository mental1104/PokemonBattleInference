import copy
from pokemon_battle_inference.domain.calculations.damage.factory import (
    DamageCalculatorFactory,
)
from pokemon_battle_inference.domain.calculations.damage.modifier_chain import (
    BaseDamageChain,
)
from pokemon_battle_inference.domain.models.move import Move
from pokemon_battle_inference.domain.models.pokemon import PokemonEntity
from pokemon_battle_inference.domain.models.damage_calculator import (
    DamageResponsibility,
    DamageResult,
)


class DamageCalculator:

    def __init__(self):
        self.responsibility_list = list(DamageResponsibility)
        self.modifier = BaseDamageChain()
        for item in self.responsibility_list:
            instance = DamageCalculatorFactory.get(item)
            self.modifier.add(instance)

    def calculate(self, attacker: PokemonEntity, defenser: PokemonEntity, move: Move):
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
