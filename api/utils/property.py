from api.utils.nature import NatureHelper

class PropertyCalculator:
    @staticmethod
    def calculate_hp(level: int, species_strength: int, basepoint: int = 252, individual_values: int = 31):
        result = ((species_strength * 2 + individual_values + basepoint / 4) * level) / 100.0 + 10 + level
        return int(result)

    @staticmethod
    def calculate_ability(property, level: int, species_strength: int, basepoint: int = 252, individual_values: int = 31, nature: str = ""):
        result = (((species_strength * 2 + individual_values + basepoint / 4) * level) / 100.0 + 5) * NatureHelper.get_effectiveness(property.value, nature)
        return int(result)