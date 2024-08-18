import logging
from api.common.damage_calculate.modifier_chain import BaseDamageChain, BasicDamageModifier, PercentModifier
from api.common.damage_calculate.modifier_chain import TypeStatModifier, TypeEfficiencyModifier, RandomModifier


class DamageCalculatorFactory:

    @staticmethod
    def get(property: str):
        if   property == "type_stat":            return TypeStatModifier()
        elif property == "type_efficiency":      return TypeEfficiencyModifier()
        elif property == "basic_damage":         return BasicDamageModifier()
        elif property == "random_modifier":      return RandomModifier()
        elif property == "percent":              return PercentModifier()
        else:
            logging.warning(f"AbilityCalculatorFactory not supported type: {property}!")
            return BaseDamageChain()