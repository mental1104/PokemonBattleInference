
from api.schema.types import TypeHelper
from api.common.damage_calculate.base_chain import BaseDamageChain


class TypeStatModifier(BaseDamageChain):
    
    def handle(self):
        if self.move.move_type.get_attack_move() and \
            (self.attacker.type_1 == self.move.type or self.attacker.type_2 == self.move.type):
            self.result.max_damage *= 1.5
            
        super().handle()


class TypeEfficiencyModifier(BaseDamageChain):

    def handle(self):
        type_multiplier = 1.0
        type_multiplier *= TypeHelper.get_type_efficacy(self.move.type, self.defenser.type_1) / 100.0
        if self.defenser.type_2:
            type_multiplier *= TypeHelper.get_type_efficacy(self.move.type, self.defenser.type_2) / 100.0

        self.result.max_damage *= type_multiplier
        super().handle()