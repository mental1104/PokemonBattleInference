import random
from api.schema.pokemon import PokemonEntity
from api.schema.move import Move, MoveType
from api.schema.types import TypeHelper


class DamageResult:
    formula: str = ""
    min_damage: int = 0
    max_damage = 0
    random_damage: int  = 0
    min_damage_percent: float  = 0.0
    max_damage_percent: float = 0.0
    random_damage_percent: float  = 0.0
    
    def __init__(
        self, 
        formula="",
        min_damage=0,
        max_damage=0,
        random_damage=0,
        min_damage_percent=0.0,
        max_damage_percent=0.0,
        random_damage_percent=0.0
    ):
        self.formula = formula
        self.min_damage = min_damage
        self.max_damage = max_damage
        self.random_damage = random_damage
        self.min_damage_percent = min_damage_percent
        self.max_damage_percent = max_damage_percent
        self.random_damage_percent = random_damage_percent

    def __mul__(self, other):
        return DamageResult(
            "",
            int(self.min_damage * other),
            int(self.max_damage * other),
            int(self.random_damage * other)
        )

    def __imul__(self, other):
        min_damage = int(self.min_damage * other)
        self.min_damage = min_damage

        max_damage = int(self.max_damage * other)
        self.max_damage = max_damage

        random_damage = int(self.random_damage * other)
        self.random_damage = random_damage

        return self


def damage_chain_responsibility(func):
    def wrapper(self, *args, **kwargs):
        func(self, *args, **kwargs)
        super_func = getattr(super(type(self), self), func.__name__, None)
        if super_func:
            super_func(*args, **kwargs)
    return wrapper


class BaseDamageChain:
    
    def __init__(self):
        self.next = None
        self.env = None
        self.attacker = None
        self.defenser = None
        self.result = DamageResult()
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

    @damage_chain_responsibility
    def handle(self):
        if self.move.move_type in MoveType.get_attack_move():
            # 神秘之剑，扑击，精神冲击等需要额外考虑，这里先临时写死，后面有专门的逻辑处理这一块
            attack = self.attacker.stat.attack if self.move.move_type == MoveType.physical_move else self.attacker.stat.special_attack
            defense = self.defenser.stat.defense if self.move.move_type == MoveType.physical_move else self.defenser.stat.special_defense
            
            damage = (2 * self.attacker.level + 10)/250.0 * attack / defense * self.move.power + 2
            self.result.max_damage = int(damage)


class RandomModifier(BaseDamageChain):

    @damage_chain_responsibility
    def handle(self):
        damage = self.result.max_damage
        

        # TODO 0.85做成可配
        self.result.max_damage = int(damage)
        self.result.min_damage = int(damage * 0.85)
        multiplier = round(random.uniform(0.85, 1.0), 2)
        self.result.random_damage = int(damage * multiplier)
        self.result.random_damage_percent = self.result.random_damage / self.defenser.stat.hp * 100000 // 10 / 100


class TypeStatModifier(BaseDamageChain):

    @damage_chain_responsibility
    def handle(self):
        if self.move.move_type.get_attack_move() and \
            (self.attacker.type_1 == self.move.type or self.attacker.type_2 == self.move.type):
            self.result *= 1.5


class TypeEfficiencyModifier(BaseDamageChain):

    @damage_chain_responsibility
    def handle(self):
        type_multiplier = 1.0
        type_multiplier *= TypeHelper.get_type_efficacy(self.move.type, self.defenser.type_1) / 100.0
        if self.defenser.type_2:
            type_multiplier *= TypeHelper.get_type_efficacy(self.move.type, self.defenser.type_2) / 100.0

        self.result *= type_multiplier


class PercentModifier(BaseDamageChain):

    @damage_chain_responsibility
    def handle(self):
        def percent_decimal_places(input, place=1):
            return input * 10000 * (10 ** (place-1)) // 10 / (10 ** place)
        self.result.min_damage_percent = percent_decimal_places(self.result.min_damage / self.defenser.stat.hp)
        self.result.max_damage_percent = percent_decimal_places(self.result.max_damage / self.defenser.stat.hp)
        self.result.random_damage_percent = percent_decimal_places(self.result.random_damage / self.defenser.stat.hp)
