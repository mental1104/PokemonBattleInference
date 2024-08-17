import math
import random
from api.common.damage_calculate.base_chain import BaseDamageChain


class FinalModifier(BaseDamageChain):
    
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
