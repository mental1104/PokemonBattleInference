import logging
import math
from abc import ABC, abstractmethod
from api.schema.property import PropertyEnum, BasePoints, SpeciesStrength, IndividualValues
from api.schema.nature import Nature
from api.schema.nature import NatureHelper

# https://wiki.52poke.com/wiki/%E8%83%BD%E5%8A%9B
class AbilityCalculatorFactory:
    @staticmethod
    def get(property: PropertyEnum):
        if   property == PropertyEnum.ATTACK:          return AttackCalculator()
        elif property == PropertyEnum.DEFENSE:         return DefenseCalculator()
        elif property == PropertyEnum.SPEED:           return SpeedCalculator()
        elif property == PropertyEnum.SPECIAL_ATTACK:  return SpecialAttackCalculator()
        elif property == PropertyEnum.SPECIAL_DEFENSE: return SpecialDefenseCalculator()
        elif property == PropertyEnum.HP:              return HPCalculator()
        else:
            logging.warning(f"AbilityCalculatorFactory not supported type: {property}!")
            return PropertyBase

class PropertyBase(ABC):
    @abstractmethod
    def calculate(self, level, species_strength, basepoint, individual_values, nature: Nature):
        pass

    @abstractmethod
    def get_basepoint(self, level, ability, species_strength, individual_values, nature):
        pass


class CommonAbilityCalculator(PropertyBase):
    
    def calculate(self, level, species_strength, basepoint, individual_values, nature: Nature):
        # 基础能力计算
        result = (((species_strength * 2 + individual_values + (basepoint/4)) * level) / 100.0 + 5)
        return result

    def get_basepoint(self, level, ability, species_strength, individual_values, nature: Nature):
        # 反推能力值
        result = ((ability - 5) * 100 / level - species_strength * 2 - individual_values) * 4
        return math.ceil(result)

class HPCalculator(PropertyBase):
    def calculate(self, level, species_strength, basepoint, individual_values, nature: Nature):
        result = (((species_strength * 2 + individual_values + basepoint / 4) * level) / 100) + 10 + level
        return int(result)

    def get_basepoint(self, level, ability, species_strength, individual_values, nature):
        basepoint = ((ability - level - 10) * 100 / level - species_strength * 2 - individual_values) * 4
        return math.ceil(basepoint)


class AttackCalculator(CommonAbilityCalculator):
    def calculate(self, level, species_strength, basepoint, individual_values, nature: Nature):
        result = super().calculate(level, species_strength, basepoint, individual_values, nature)
        return int(result * NatureHelper.get_effectiveness(PropertyEnum.ATTACK, nature))

    def get_basepoint(self, level, ability, species_strength, individual_values, nature):
        degrade_ability = math.ceil(ability / NatureHelper.get_effectiveness(PropertyEnum.ATTACK, nature))
        return super().get_basepoint(level, degrade_ability, species_strength, individual_values, nature)


class DefenseCalculator(CommonAbilityCalculator):
    def calculate(self, level, species_strength, basepoint, individual_values, nature: Nature):
        result = super().calculate(level, species_strength, basepoint, individual_values, nature)
        return int(result * NatureHelper.get_effectiveness(PropertyEnum.DEFENSE, nature))

    def get_basepoint(self, level, ability, species_strength, individual_values, nature):
        degrade_ability = math.ceil(ability / NatureHelper.get_effectiveness(PropertyEnum.DEFENSE, nature))
        return super().get_basepoint(level, degrade_ability, species_strength, individual_values, nature)


class SpeedCalculator(CommonAbilityCalculator):
    def calculate(self, level, species_strength, basepoint, individual_values, nature: Nature):
        result = super().calculate(level, species_strength, basepoint, individual_values, nature)
        return int(result * NatureHelper.get_effectiveness(PropertyEnum.SPEED, nature))

    def get_basepoint(self, level, ability, species_strength, individual_values, nature):
        degrade_ability = math.ceil(ability / NatureHelper.get_effectiveness(PropertyEnum.SPEED, nature))
        return super().get_basepoint(level, degrade_ability, species_strength, individual_values, nature)


class SpecialAttackCalculator(CommonAbilityCalculator):
    def calculate(self, level, species_strength, basepoint, individual_values, nature: Nature):
        result = super().calculate(level, species_strength, basepoint, individual_values, nature)
        return int(result * NatureHelper.get_effectiveness(PropertyEnum.SPECIAL_ATTACK, nature))

    def get_basepoint(self, level, ability, species_strength, individual_values, nature):
        degrade_ability = math.ceil(ability / NatureHelper.get_effectiveness(PropertyEnum.SPECIAL_ATTACK, nature))
        return super().get_basepoint(level, degrade_ability, species_strength, individual_values, nature)


class SpecialDefenseCalculator(CommonAbilityCalculator):
    def calculate(self, level, species_strength: SpeciesStrength, basepoint: BasePoints, individual_values: IndividualValues, nature: Nature):
        result = super().calculate(level, species_strength, basepoint, individual_values, nature)
        return int(result * NatureHelper.get_effectiveness(PropertyEnum.SPECIAL_DEFENSE, nature))

    def get_basepoint(self, level, ability, species_strength, individual_values, nature):
        degrade_ability = math.ceil(ability / NatureHelper.get_effectiveness(PropertyEnum.SPECIAL_DEFENSE, nature))
        return super().get_basepoint(level, degrade_ability, species_strength, individual_values, nature)
