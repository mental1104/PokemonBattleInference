import logging
from pokeop.domain.models.damage_calculator import (
    DamageResponsibility,
)
from pokeop.domain.calculations.damage.modifier_chain import (
    BaseDamageChain,
    BasicDamageModifier,
    PercentModifier,
    TypeStatModifier,
    TypeEfficiencyModifier,
    RandomModifier,
)


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
