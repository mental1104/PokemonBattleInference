import logging
from api.schema.damage_calculator import DamageResponsibility
from api.common.damage_calculate.modifier_chain import BaseDamageChain, BasicDamageModifier, PercentModifier
from api.common.damage_calculate.modifier_chain import TypeStatModifier, TypeEfficiencyModifier, RandomModifier


class DamageCalculatorFactory:

    @staticmethod
    def get(property: DamageResponsibility):
        if   property == DamageResponsibility.TYPE_STAT:            return TypeStatModifier()
        elif property == DamageResponsibility.TYPE_EFFICIENCY:      return TypeEfficiencyModifier()
        elif property == DamageResponsibility.BASIC_DAMAGE:         return BasicDamageModifier()
        elif property == DamageResponsibility.RANDOM_MODIFIER:      return RandomModifier()
        elif property == DamageResponsibility.PERCENT:              return PercentModifier()
        else:
            logging.warning(f"AbilityCalculatorFactory not supported type: {property}!")
            return BaseDamageChain()