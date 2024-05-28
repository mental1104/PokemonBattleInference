from enum import Enum

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


