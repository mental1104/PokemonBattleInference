from pydantic import BaseModel, Field
from typing import List, Optional
from pokemon_battle_inference.domain.models.level import DefaultLevel
from pokemon_battle_inference.domain.models.nature import Nature
from pokemon_battle_inference.domain.models.move import MoveType


class PokemonModelRequest(BaseModel):
    id: int = Field(0, description="宝可梦ID")
    level: Optional[int] = Field(
        DefaultLevel.DEFAULT_100_LEVEL, description="宝可梦等级"
    )
    basepoint: Optional[List[int]] = Field(
        [0, 0, 0, 0, 0, 0],
        description="努力值分配，元素不足6个的会用0填充，超过6个的会忽略后面的内容",
    )
    individual_values: Optional[List[int]] = Field(
        [31, 31, 31, 31, 31, 31],
        description="个体值分配，元素不足6个的会用0填充，超过6个的会忽略后面的内容",
    )
    nature: Optional[Nature] = Field(Nature.ADAMANT, description="性格")


class MoveRequest(BaseModel):
    power: int = Field(40, description="技能威力")
    move_type: MoveType = Field(
        MoveType.physical_move, description="技能类型：变化/物理/特殊"
    )
    type: str = Field("Normal", description="技能属性")


class DamageRequest(BaseModel):
    attacker: PokemonModelRequest = Field(PokemonModelRequest(), description="攻击方")
    defenser: PokemonModelRequest = Field(PokemonModelRequest(), description="防守方")
    move: MoveRequest = Field(MoveRequest(), description="技能信息")


class DamageResponse(BaseModel):
    formula: str = Field("", description="计算公式")
    min_damage: int = Field(0, decription="最小伤害")
    max_damage: int = Field(0, description="最大伤害")
    random_damage: int = Field(0, description="随机伤害")
    min_damage_percent: float = Field(0.0, description="最小伤害百分比")
    max_damage_percent: float = Field(0.0, description="最大伤害百分比")
    random_damage_percent: float = Field(0.0, description="随机伤害百分比")
