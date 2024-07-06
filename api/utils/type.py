from api.schema.types import type_efficacy, Type

class TypeHelper:

    @staticmethod
    def get_type_efficacy(attacker: Type, defenser: Type):
        return type_efficacy[attacker.value][defenser.value]