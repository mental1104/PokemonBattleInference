"""独立旧伤害/历史构造与新纯Core完整差分，随机源只注入原始unit，全部数学仍由原责任链执行。"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import random
import subprocess
from pathlib import Path
from typing import Literal, cast

import pytest
from pydantic import BaseModel, ConfigDict, Field

from pokeop.domain.calculations.ability import AbilityCalculatorFactory
from pokeop.domain.calculations.damage.calculator import DamageCalculator
from pokeop.domain.models.move import Move, MoveType
from pokeop.domain.models.nature import Nature
from pokeop.domain.models.pokemon import PokemonEntity
from pokeop.domain.models.property import BasePoints, IndividualValues, PropertyEnum, SpeciesStrength, Statistic
from pokeop.domain.models.types import Type, type_efficacy


class _FrozenModel(BaseModel):
    """新codec差分边界的完整拥有值；不从原字典协议中推断默认或运行额外算法。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class _Pokemon(_FrozenModel):
    """原历史director消费的基础六值/EV原序列；传入IV从未被原HTTP使用，不属于此Core合同。"""

    level: int
    base: tuple[int, ...] = Field(min_length=6,max_length=6)
    basepoint: tuple[int, ...]
    nature: Nature | None
    types: tuple[int, ...]

    def entity(self) -> PokemonEntity:
        """复用原CommonProperty/AbilityFactory按历史builder流程生成实体，不在测试重写能力公式。"""
        base, effort = SpeciesStrength.create(self.base), BasePoints.create(self.basepoint)
        values = {}
        for field in PropertyEnum:
            # 原builder允许赋null nature，旧类型注释较窄；真实NatureHelper对此明确采用neutral。
            values[field.value] = AbilityCalculatorFactory.get(field).calculate(
                self.level, getattr(base, field.value), getattr(effort, field.value), 31, cast(Nature, self.nature)
            )
        return PokemonEntity(level=self.level, type_1=Type(self.types[0]), type_2=Type(self.types[1]) if len(self.types) == 2 else None,
            species_strength=base, basepoint=effort, individual_values=IndividualValues.create((31,31,31,31,31,31)), stat=Statistic(**values))


class _Move(_FrozenModel):
    """原旧自由招式，不含现代效果或计算附加开关。"""

    power: int
    type: int
    move_type: MoveType


class _Factor(_FrozenModel):
    """直接来自原旧TypeHelper静态表的百分制知识，避免借现代规则表替换历史语义。"""

    attacking: int
    defending: int
    percent: int


class _Request(_FrozenModel):
    """唯一正式legacy operation，unit是源随机事实，uniform与round必须由双方实际算法完成。"""

    kind: Literal["legacy_damage"] = "legacy_damage"
    attacker: _Pokemon
    defender: _Pokemon
    move: _Move
    random_unit: float
    type_chart: tuple[_Factor, ...]

    def oracle(self, monkeypatch: pytest.MonkeyPatch) -> _Result:
        """仅替换Random对象的原始random()源；原uniform/round/责任链/百分比完整执行。"""
        # random.uniform是模块Random实例的绑定方法，它读取同实例random()而非模块同名别名。
        monkeypatch.setattr(random._inst, "random", lambda: self.random_unit)
        attacker, defender = self.attacker.entity(), self.defender.entity()
        with contextlib.redirect_stdout(io.StringIO()):
            result = DamageCalculator().calculate(attacker, defender, Move(power=self.move.power, type=Type(self.move.type), move_type=self.move.move_type))
        assert attacker.stat is not None and defender.stat is not None
        return _Result(kind="legacy_damage",formula=result.formula,min_damage=str(result.min_damage),max_damage=str(result.max_damage),
            random_damage=str(result.random_damage),min_damage_percent=result.min_damage_percent,max_damage_percent=result.max_damage_percent,
            random_damage_percent=result.random_damage_percent,attacker_stats=tuple(str(getattr(attacker.stat,field.value)) for field in PropertyEnum),
            defender_stats=tuple(str(getattr(defender.stat,field.value)) for field in PropertyEnum),random_multiplier=round(0.85+(1.0-0.85)*self.random_unit,2))


class _Result(_FrozenModel):
    """原七字段与准备证据全部建模；大整数仅按正式Core decimal string传输，不经float。"""

    kind: Literal["legacy_damage"]
    formula: str
    min_damage: str
    max_damage: str
    random_damage: str
    min_damage_percent: float
    max_damage_percent: float
    random_damage_percent: float
    attacker_stats: tuple[str, ...] = Field(min_length=6,max_length=6)
    defender_stats: tuple[str, ...] = Field(min_length=6,max_length=6)
    random_multiplier: float


class TestLegacyDamage:
    """完整旧算法差分，包含实际边界和随机样本；不以原HTTP的NameError冒充已迁移计算。"""

    def test_complete_historical_algorithm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """逐项核对全部历史stats/七字段/随机倍率；覆盖分数EV、Quiet、非5倍等级与decimal舍入边界。"""
        executable = os.environ.get("PBI_LEGACY_DAMAGE_RUNNER")
        if not executable:
            pytest.skip("PBI_LEGACY_DAMAGE_RUNNER is required")
        chart = tuple(_Factor(attacking=attack,defending=defend,percent=type_efficacy[attack][defend]) for attack in range(1,19) for defend in range(1,19))
        planner = random.Random(20261124)
        requests = []
        units = [0.0,1.0,0.5,math.nextafter(1.0,0.0)]
        for hundredth in range(85,100):
            unit = ((hundredth/100+0.005)-0.85)/(1.0-0.85)
            units.extend((math.nextafter(unit,0.0),unit,math.nextafter(unit,1.0)))
        for index in range(360):
            level = planner.randint(1,100)
            nature = list(Nature)[index%25] if index%29 else None
            attacker = _Pokemon(level=level,base=tuple(planner.randint(10,255) for _ in range(6)),basepoint=tuple(planner.randint(0,800) for _ in range(6)),nature=nature,types=(1,) if index%3 else (10,9))
            defender = _Pokemon(level=planner.randint(1,100),base=tuple(planner.randint(10,255) for _ in range(6)),basepoint=tuple(planner.randint(0,800) for _ in range(6)),nature=list(Nature)[(index+13)%25],types=(8,) if index%7==0 else (12,9))
            unit = units[index] if index<len(units) else planner.random()
            requests.append(_Request(attacker=attacker,defender=defender,move=_Move(power=(-20 if index%31==0 else planner.randint(0,300)),type=(1 if index%2 else 10),move_type=list(MoveType)[index%3]),random_unit=unit,type_chart=chart))
        # 输入EV超过2**53仍由原float与任意精度int处理，Core不能在int64或百分比转换处静默截断。
        for effort in (2**53+3,2**60+7,2**63-1):
            attacker=_Pokemon(level=100,base=(100,100,100,100,100,100),basepoint=(0,effort,0,effort,0,0,999999),nature=Nature.ADAMANT,types=(1,))
            defender=_Pokemon(level=53,base=(100,100,100,100,100,100),basepoint=(2,2,2,2,2,2),nature=Nature.QUIET,types=(1,))
            requests.append(_Request(attacker=attacker,defender=defender,move=_Move(power=255,type=1,move_type=MoveType.physical_move),random_unit=0.5,type_chart=chart))
        # 原旧schema没有现代EV/等级边界；保留零/负等级和负EV的实际float/int行为，而不新增官方限制。
        for level in (-5,-1,0,1,53,100):
            attacker=_Pokemon(level=level,base=(100,100,100,100,100,100),basepoint=(-5,-1,2,3,5,7),nature=Nature.QUIET,types=(10,))
            defender=_Pokemon(level=level,base=(100,100,100,100,100,100),basepoint=(2,2,2,2,2,2),nature=None,types=(12,9))
            requests.append(_Request(attacker=attacker,defender=defender,move=_Move(power=95,type=10,move_type=MoveType.special_move),random_unit=0.5,type_chart=chart))
        payload="\n".join(request.model_dump_json() for request in requests)+"\n"
        execution=subprocess.run([executable],input=payload,text=True,capture_output=True,check=True)
        outputs=execution.stdout.splitlines()
        assert len(outputs)==len(requests),execution.stderr
        expected=[]
        for request,line in zip(requests,outputs,strict=True):
            actual=_Result.model_validate_json(line)
            original=request.oracle(monkeypatch)
            assert actual==original,(request.model_dump(),actual.model_dump(),original.model_dump())
            expected.append(original.model_dump(mode="json"))
        report=os.environ.get("PBI_LEGACY_DAMAGE_REPORT")
        if report:
            Path(report).write_text(json.dumps({"cases":len(requests),"inputs":[request.model_dump(mode="json") for request in requests],"expected":expected},ensure_ascii=False))
