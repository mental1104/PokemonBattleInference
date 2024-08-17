from api.schema.pokemon import PokemonEntity
from api.schema.move import Move, MoveType


class DamageResult:
    formula: str = ""
    min_damage: int = 0
    max_damage = 0
    random_damage: int  = 0.0
    min_damage_percent: float  = 0.0
    max_damage_percent: float = 0.0
    random_damage_percent: float  = 0.0

class BaseDamageChain:
    
    def __init__(self):
        self.next = None
        self.env = None
        self.attacker = None
        self.defenser = None
        self.result = None
        self.move = None
    
    def set(self, attacker: PokemonEntity, defenser: PokemonEntity, move: Move, result: DamageResult):
        self.attacker = attacker
        self.defenser = defenser
        self.result = result
        self.move = move
        
    def add(self, damage_linker):
        if self.next:
            self.next.add(damage_linker)
        else:
            self.next = damage_linker
            
    def handle(self):
        if self.next:
            self.next.handle()


class BasicDamageModifier(BaseDamageChain):
    
    def handle(self):
        if self.move.move_type in MoveType.get_attack_move():
            # 神秘之剑，扑击，精神冲击等需要额外考虑，这里先临时写死，后面有专门的逻辑处理这一块
            attack = self.attacker.stat.attack if self.move.move_type == MoveType.physical_move else self.attacker.stat.special_attack
            defense = self.attacker.stat.defense if self.move.move_type == MoveType.physical_move else self.defenser.stat.special_defense
            damage = (2 * self.attacker.level + 10)/250.0 * attack / defense * self.move.power + 2
            self.result.max_damage = damage

        super().handle()
