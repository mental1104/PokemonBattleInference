from api.schema.nature import nature_dict

class NatureHelper:
    @staticmethod
    def get_effectiveness(property, nature):
        return nature_dict.get(nature, {}).get(property, 1.0)