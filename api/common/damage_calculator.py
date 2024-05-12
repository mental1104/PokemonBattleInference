from pydantic import BaseModel, field_validator 
from typing import Optional
from enum import Enum
import sys
sys.path.append("../")
from schema.damage_calculator import Attacker, Defender, Move
from db import setup, open_session
from models.pokemon import Pokemon


class CommonProperty(BaseModel):
    hp: int = 0
    attack: int = 0
    defense: int = 0
    special_attack: int = 0
    special_defense: int = 0
    speed: int = 0

# 个体值
class IndividualValues(CommonProperty):
    pass

# 种族值
class SpeciesStrength(CommonProperty):
    pass

# 努力值
class BasePoints(CommonProperty):
    pass

# 最终能力值
class Statistic(CommonProperty):
    pass

# 性格增益


class MoveType:
    physical_move = "physical_move"
    special_move = "special_move"
    status_move =  "status_move"


class Move:
    power: Optional[int] = None
    move_type: MoveType


class PropertyCalculator:
    @staticmethod
    def calculate_hp(level: int, species_strength: int, basepoint: int = 252, individual_values: int = 31):
        result = ((species_strength * 2 + individual_values + basepoint / 4) * level) / 100.0 + 10 + level
        return int(result)

    @staticmethod
    def calculate_ability(property, level: int, species_strength: int, basepoint: int = 252, individual_values: int = 31, nature: str = ""):
        result = (((species_strength * 2 + individual_values + basepoint / 4) * level) / 100.0 + 5) * NatureHelper.get_effectiveness(property.value, nature)
        return int(result)

class Nature(str, Enum):
    HARDY = 'Hardy'  # 勤奋
    LONELY = 'Lonely' # 怕寂寞
    ADAMANT = 'Adamant' # 固执
    NAUGHTY = 'Naughty' # 顽皮
    BRAVE = 'Brave' # 勇敢
    BOLD = 'Bold' # 大胆
    DOCILE = 'Docile' # 坦率
    IMPISH = 'Impish' # 淘气
    LAX = 'Lax' # 乐天
    RELAXED = 'Relaxed' # 悠闲
    MODEST = 'Modest' # 内敛
    MILD = 'Mild' # 慢吞吞
    BASHFUL = 'Bashful' # 害羞
    RASH = 'Rash' # 马虎
    QUIET = 'Quiet' # 冷静
    CALM = 'Calm' # 温和
    GENTLE = 'Gentle' # 温顺
    CAREFUL = 'Careful' # 慎重
    QUIRKY = 'Quirky' # 浮躁
    SASSY = 'Sassy' # 自大
    TIMID = 'Timid' # 胆小
    HASTY = 'Hasty' # 急躁
    JOLLY = 'Jolly' # 爽朗
    NAIVE = 'Naive' # 天真
    SERIOUS = 'Serious' # 认真


nature_dict = {
    'Hardy':   {'attack': 1.0, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 1.0}, 
    'Lonely':  {'attack': 1.1, 'defense': 0.9, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 1.0}, 
    'Adamant': {'attack': 1.1, 'defense': 1.0, 'special_attack': 0.9, 'special_defense': 1.0, 'speed': 1.0}, 
    'Naughty': {'attack': 1.1, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 0.9, 'speed': 1.0}, 
    'Brave':   {'attack': 1.1, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 0.9}, 
    'Bold':    {'attack': 0.9, 'defense': 1.1, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 1.0}, 
    'Docile':  {'attack': 1.0, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 1.0}, 
    'Impish':  {'attack': 1.0, 'defense': 1.1, 'special_attack': 0.9, 'special_defense': 1.0, 'speed': 1.0}, 
    'Lax':     {'attack': 1.0, 'defense': 1.1, 'special_attack': 1.0, 'special_defense': 0.9, 'speed': 1.0}, 
    'Relaxed': {'attack': 1.0, 'defense': 1.1, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 0.9}, 
    'Modest':  {'attack': 0.9, 'defense': 1.0, 'special_attack': 1.1, 'special_defense': 1.0, 'speed': 1.0}, 
    'Mild':    {'attack': 1.0, 'defense': 0.9, 'special_attack': 1.1, 'special_defense': 1.0, 'speed': 1.0}, 
    'Bashful': {'attack': 1.0, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 1.0}, 
    'Rash':    {'attack': 1.0, 'defense': 1.0, 'special_attack': 1.1, 'special_defense': 0.9, 'speed': 1.0}, 
    'Quiet':   {'attack': 1.0, 'defense': 1.0, 'special_attack': 1.1, 'special_defense': 1.0, 'speed': 1.0}, 
    'Calm':    {'attack': 0.9, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 1.1, 'speed': 1.0}, 
    'Gentle':  {'attack': 1.0, 'defense': 0.9, 'special_attack': 1.0, 'special_defense': 1.1, 'speed': 1.0}, 
    'Careful': {'attack': 1.0, 'defense': 1.0, 'special_attack': 0.9, 'special_defense': 1.1, 'speed': 1.0}, 
    'Quirky':  {'attack': 1.0, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 1.0}, 
    'Sassy':   {'attack': 1.0, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 1.1, 'speed': 0.9}, 
    'Timid':   {'attack': 0.9, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 1.1}, 
    'Hasty':   {'attack': 1.0, 'defense': 0.9, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 1.1}, 
    'Jolly':   {'attack': 1.0, 'defense': 1.0, 'special_attack': 0.9, 'special_defense': 1.0, 'speed': 1.1}, 
    'Naive':   {'attack': 1.0, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 0.9, 'speed': 1.1}, 
    'Serious': {'attack': 1.0, 'defense': 1.0, 'special_attack': 1.0, 'special_defense': 1.0, 'speed': 1.0}
}


class PropertyEnum(str, Enum):
    HP = "hp"
    ATTACK = "attack"
    DEFENSE = "defense"
    SPECIAL_ATTACK = "special_attack"
    SPECIAL_DEFENSE = "special_defense"
    SPEED = "speed"


class NatureHelper:
    @staticmethod
    def get_effectiveness(property, nature):
        return nature_dict.get(nature, {}).get(property, 1.0)

class PokemonEntity:
    def __init__(self, 
        id, 
        level: int,
        basepoint: BasePoints,
        individual_values: IndividualValues,
        nature: Nature,
        ability_index = 1,
        item_index = 1,
    ):
        self.id = id
        self.name = ""
        self.level = level
        species_strength = SpeciesStrength()

        with open_session() as session:
            pokemon_record = Pokemon.get_by_id(session, id)
            if pokemon_record is not None:
                species_strength = SpeciesStrength(
                    hp=pokemon_record.hp,
                    attack=pokemon_record.attack,
                    defense=pokemon_record.defense,
                    special_attack=pokemon_record.special_attack,
                    special_defense=pokemon_record.special_defense,
                    speed=pokemon_record.speed
                )
                self.name = pokemon_record.name

        self.nature = nature
        self.species_strength = species_strength
        self.basepoint = basepoint
        self.individual_values = individual_values
        self.stat = Statistic()
        self.refresh()
    
    def refresh(self):
        self.stat.hp = PropertyCalculator.calculate_hp(self.level, self.species_strength.hp, self.basepoint.hp, self.individual_values.hp)
        self.stat.attack = PropertyCalculator.calculate_ability(PropertyEnum.ATTACK, self.level, self.species_strength.attack, self.basepoint.attack, self.individual_values.attack, self.nature)
        self.stat.defense = PropertyCalculator.calculate_ability(PropertyEnum.DEFENSE, self.level, self.species_strength.defense, self.basepoint.defense, self.individual_values.defense, self.nature)
        self.stat.special_attack = PropertyCalculator.calculate_ability(PropertyEnum.SPECIAL_ATTACK, self.level, self.species_strength.special_attack, self.basepoint.special_attack, self.individual_values.special_attack, self.nature)
        self.stat.special_defense = PropertyCalculator.calculate_ability(PropertyEnum.SPECIAL_DEFENSE, self.level, self.species_strength.special_defense, self.basepoint.special_defense, self.individual_values.special_defense, self.nature)
        self.stat.speed = PropertyCalculator.calculate_ability(PropertyEnum.SPEED, self.level, self.species_strength.speed, self.basepoint.speed, self.individual_values.speed, self.nature)


class DamageCalculator:
    
    @staticmethod
    def calculate(attacker: Attacker, defender: Defender, move: Move):
        pass
    

if __name__ == "__main__":
    setup()
    pokemon = PokemonEntity(
        6, 
        100, 
        BasePoints(special_attack=252, speed=252, hp=4), 
        IndividualValues(hp=31, attack=31, defense=31, special_attack=31, special_defense=31, speed=31), 
        Nature.TIMID
    )
    print(pokemon.stat)