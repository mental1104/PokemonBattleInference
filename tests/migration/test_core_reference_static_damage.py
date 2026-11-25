"""明确reference_static上下文与原无实时状态DamageContext完整责任链的真实差分。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import DamageContext, MoveCategory
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.grounding import GroundingState
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_generation
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.weather import Weather
from pokeop.domain.models.types import Type
from tests.migration.test_core_damage import DamageOperation, DamageResponse, _DamageOracle, _reference


class ReferenceStaticOperation(DamageOperation):
    """原完整伤害操作加唯一明确上下文，不在测试端清空能力或预先计算倍率。"""

    context: Literal["reference_static"] = "reference_static"


@pytest.fixture
def reference_static_damage_runner() -> Path:
    """明确真实typed入口差分进程；未编译时skip，不用原Python冒充Core。"""
    value = os.getenv("PBI_REFERENCE_STATIC_DAMAGE_RUNNER")
    if value is None:
        pytest.skip("PBI_REFERENCE_STATIC_DAMAGE_RUNNER is required")
    runner = Path(value)
    assert runner.is_file()
    return runner


class TestCoreReferenceStaticDamage:
    """两种动态层能力在原静态上下文的无hook语义，以及所有其他显式事实完整保留。"""

    def test_complete_original_static_chain_for_all_ability_pairs(self, reference_static_damage_runner: Path) -> None:
        """192例覆盖全部九种能力双侧组合、九代际、显式环境/道具/进化/接地和自定义无序随机档。"""
        rng = random.Random(60401)
        base = _reference()
        abilities = tuple(DamageAbility)
        items = tuple(DamageItem)
        types = tuple(Type)
        contexts: list[DamageContext] = []
        operations: list[ReferenceStaticOperation] = []
        for index in range(192):
            move_type = rng.choice(types)
            attacker = replace(base.attacker, level=rng.randint(1, 100), types=tuple(rng.sample(types, 2)),
                ability=abilities[index % len(abilities)], item=rng.choice(items), grounding_state=rng.choice((None, *GroundingState)),
                stats=StatValues(*(rng.randint(1, 999) for _ in range(6))))
            defender = replace(base.defender, types=tuple(rng.sample(types, 2)),
                ability=abilities[(index // len(abilities)) % len(abilities)], item=rng.choice(items), can_evolve=bool(index & 1),
                grounding_state=rng.choice((None, *GroundingState)), stats=StatValues(*(rng.randint(1, 999) for _ in range(6))))
            ruleset = resolve_ruleset_by_generation(index % 9 + 1)
            if index % 4 == 0:
                # 原Multiscale静态无hook，策略中该动态倍率即使改变也不能误入最终伤害。
                ruleset = replace(ruleset, damage_policy=replace(ruleset.damage_policy,
                    multiscale_damage_multiplier=0.3125, random_damage_multipliers=(1.0, 0.0, 0.85, 0.85, 0.5)))
            context = replace(base, attacker=attacker, defender=defender,
                move=replace(base.move, type=move_type, category=rng.choice((MoveCategory.PHYSICAL, MoveCategory.SPECIAL)),
                    power=rng.choice((1, 40, 60, 61, 80, 120, 250))), ruleset=ruleset,
                environment=BattleEnvironment(weather=rng.choice((None, *Weather)), terrain=rng.choice((None, *Terrain)),
                    defender_side=SideConditions(bool(index & 2), bool(index & 4), bool(index & 8))),
                is_critical=bool(index & 16), is_spread_move=bool(index & 32), is_protect_reduced=bool(index & 64), is_multi_target_battle=bool(index & 128))
            contexts.append(context)
            operations.append(ReferenceStaticOperation(**_DamageOracle.operation(context).model_dump()))
        result = subprocess.run([str(reference_static_damage_runner)], input="".join(operation.model_dump_json() + "\n" for operation in operations),
            text=True, capture_output=True, check=True, timeout=60)
        lines = result.stdout.splitlines()
        assert len(lines) == len(contexts)
        for line, context in zip(lines, contexts, strict=True):
            _DamageOracle.check(context, DamageResponse.model_validate_json(line))
