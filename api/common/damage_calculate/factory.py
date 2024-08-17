import logging
from api.common.damage_calculate.base_chain import BaseDamageChain, BasicDamageModifier
from api.common.damage_calculate.type_chain import TypeStatModifier, TypeEfficiencyModifier
from api.common.damage_calculate.probability_chain import FinalModifier


class DamageCalculatorFactory:

    @staticmethod
    def get(property: str):
        if   property == "type_stat":           return TypeStatModifier()
        elif property == "type_efficiency":     return TypeEfficiencyModifier()
        elif property == "basic_damage":        return BasicDamageModifier()
        elif property == "final_modifier":      return FinalModifier()
        else:
            logging.warning(f"AbilityCalculatorFactory not supported type: {property}!")
            return BaseDamageChain()