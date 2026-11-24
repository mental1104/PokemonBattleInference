"""从真实 C ABI 逐项对照 Python 直接伤害链；知识按请求注入，不依赖数据库。"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import random
import statistics
import subprocess
import time
from collections.abc import Sequence
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import BattleMove, BattlePokemon, DamageContext, MoveCategory
from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.grounding import GroundingState
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifiers import DamageCalculationState, build_default_damage_chain
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_generation
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.weather import Weather
from pokeop.domain.models.types import Type, TypeHelper


class _Contract(BaseModel):
    """固定协议边界，冻结模型并拒绝未知字段，避免测试自身吞掉新输出。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PokemonSnapshot(_Contract):
    """C ABI 需要的完整宝可梦知识/能力快照；无配置或数据库引用。"""

    level: int
    types: tuple[Type, ...]
    stats: StatValues
    ability: DamageAbility | Literal["none"]
    item: DamageItem | Literal["none"]
    can_evolve: bool
    grounding: GroundingState | None


class MoveSnapshot(_Contract):
    """固定威力招式的只读协议数据，不包含动态效果。"""

    type: Type
    category: MoveCategory
    power: int


class TypeEfficacySnapshot(_Contract):
    """一条从旧知识接口取出的相克值，测试不另存第二张属性表。"""

    attacking: Type
    defending: Type
    percent: int


class DamageOperation(_Contract):
    """一次伤害计算的完整序列化合同；策略直接复用旧声明式 dataclass。"""

    kind: Literal["damage"] = "damage"
    generation_id: int
    attacker: PokemonSnapshot
    defender: PokemonSnapshot
    move: MoveSnapshot
    type_chart: tuple[TypeEfficacySnapshot, ...]
    policy: DamagePolicy
    weather: Weather | Literal["none"]
    terrain: Terrain | Literal["none"]
    defender_side: SideConditions
    critical: bool
    spread: bool
    protect_reduced: bool
    multi_target: bool


class DamageBatch(_Contract):
    """一次进程调用可以处理多批，所有批次均遵守正式的 v1 C ABI。"""

    schema_version: Literal[1] = 1
    operations: tuple[DamageOperation, ...]


class ExactFraction(_Contract):
    """精确分子/分母字符串，测试比较时不转 float。"""

    numerator: str
    denominator: str

    def value(self) -> Fraction:
        """返回经过 Python Fraction 规范化的精确值，无参数、无副作用。"""
        return Fraction(int(self.numerator), int(self.denominator))


class DamageTrace(_Contract):
    """单条修正的全部对外字段，含明确为空的随机/固定倍率。"""

    key: str
    stage: str
    source: str
    reason: str
    multiplier: float | None
    min_multiplier: float | None
    max_multiplier: float | None


class DamageResponse(_Contract):
    """完整伤害响应；精确 KO 由同一 Core 派生。"""

    kind: Literal["damage"]
    damage_ruleset_id: str
    rolls: tuple[int, ...]
    defender_hp: int
    base_damage: int
    trace: tuple[DamageTrace, ...]
    ohko: ExactFraction
    two_hit: ExactFraction
    guaranteed_ohko: bool
    guaranteed_two_hit: bool


class DamageEnvelope(_Contract):
    """成功批次必须给出版本和每个完整响应；错误不能伪装成成功结果。"""

    schema_version: Literal[1]
    engine_version: Literal["0.6.0"]
    rules_version: Literal["calculation-rules.v6"]
    results: tuple[DamageResponse, ...]


class DamageBenchmark(_Contract):
    """直接伤害批次实测；保留两端不同开销边界，不推断完整推演性能。"""

    schema_version: Literal[1] = 1
    workload: Literal["scizor-sylveon-direct-damage"] = "scizor-sylveon-direct-damage"
    engine_version: Literal["0.6.0"] = "0.6.0"
    case_count: int
    repeats: int
    platform: str
    python_version: str
    compiler: str
    binary_sha256: str
    result_sha256: str
    python_seconds: tuple[float, ...]
    cpp_process_seconds: tuple[float, ...]
    python_median_seconds: float
    cpp_process_median_seconds: float
    measurement_boundary: str


class _DamageOracle:
    """集中管理 Python 快照到正式合同的适配，以及对完整结果的独立检查。"""

    @staticmethod
    def pokemon(value: BattlePokemon) -> PokemonSnapshot:
        """value 为只读旧领域快照；返回不含名称/隐式 UNKNOWN 的固定输入。"""
        return PokemonSnapshot(
            level=value.level, types=value.types, stats=value.stats,
            ability="none" if value.ability is DamageAbility.UNKNOWN else value.ability.value,
            item="none" if value.item is DamageItem.UNKNOWN else value.item.value,
            can_evolve=value.can_evolve, grounding=value.grounding_state,
        )

    @classmethod
    def operation(cls, context: DamageContext) -> DamageOperation:
        """context 为完整旧输入；返回含全部所需相克知识的协议对象，不修改原对象。"""
        assert context.ruleset is not None
        return DamageOperation(
            generation_id=context.ruleset.generation_id,
            attacker=cls.pokemon(context.attacker), defender=cls.pokemon(context.defender),
            move=MoveSnapshot(type=context.move.type, category=context.move.category, power=context.move.power),
            type_chart=tuple(TypeEfficacySnapshot(attacking=context.move.type, defending=value,
                              percent=TypeHelper.get_type_efficacy(context.move.type, value))
                             for value in {entry.value: entry for entry in context.defender.types}.values()),
            policy=context.ruleset.damage_policy,
            weather=context.environment.weather or "none", terrain=context.environment.terrain or "none",
            defender_side=context.environment.defender_side, critical=context.is_critical,
            spread=context.is_spread_move, protect_reduced=context.is_protect_reduced,
            multi_target=context.is_multi_target_battle,
        )

    @staticmethod
    def check(context: DamageContext, actual: DamageResponse) -> None:
        """context 为 oracle 输入，actual 为真实 ABI 响应；逐字段严格核对，无容差放宽。"""
        expected = calculate_damage_rolls(context)
        state = build_default_damage_chain().handle(DamageCalculationState.from_context(context))
        assert actual.rolls == expected.rolls
        assert actual.defender_hp == expected.defender_hp
        assert actual.base_damage == state.base_damage
        assert context.ruleset is not None
        assert actual.damage_ruleset_id == f"python-compatible.gen{context.ruleset.generation_id}.v1"
        assert len(actual.trace) == len(expected.applied_modifiers)
        for entry, reference in zip(actual.trace, expected.applied_modifiers, strict=True):
            assert entry.key == reference.key
            assert entry.stage == reference.stage
            assert entry.source == reference.source
            assert entry.reason == reference.reason
            assert entry.multiplier == reference.multiplier
            assert entry.min_multiplier == reference.min_multiplier
            assert entry.max_multiplier == reference.max_multiplier
        rolls, hp = expected.rolls, expected.defender_hp
        assert actual.ohko.value() == Fraction(sum(value >= hp for value in rolls), len(rolls))
        assert actual.two_hit.value() == Fraction(sum(a + b >= hp for a in rolls for b in rolls), len(rolls) ** 2)
        assert actual.guaranteed_ohko == (min(rolls) >= hp)
        assert actual.guaranteed_two_hit == (2 * min(rolls) >= hp)

    @classmethod
    def run(cls, runner: Path, contexts: Sequence[DamageContext]) -> tuple[DamageResponse, ...]:
        """runner 为实际 C ABI 程序，contexts 为只读样本；返回核对后的逐项结果。

        批次限制在 100 项，避免测试本身超出正式请求预算；整个进程有明确超时。
        """
        batches = tuple(DamageBatch(operations=tuple(cls.operation(value) for value in contexts[start:start + 100]))
                        for start in range(0, len(contexts), 100))
        completed = subprocess.run([str(runner)], input="\n".join(batch.model_dump_json() for batch in batches) + "\n",
                                   text=True, capture_output=True, check=True, timeout=45)
        lines = completed.stdout.splitlines()
        assert len(lines) == len(batches)
        actual = tuple(result for line in lines for result in DamageEnvelope.model_validate_json(line).results)
        assert len(actual) == len(contexts)
        for context, result in zip(contexts, actual, strict=True):
            cls.check(context, result)
        return actual


@pytest.fixture(scope="module")
def damage_runner() -> Path:
    """返回已构建的 ABI 程序；未构建可跳过，显式配置错误必须失败，不在测试内构建。"""
    configured = os.environ.get("PBI_CORE_VECTOR_RUNNER")
    directory = Path(configured).parent if configured else Path(__file__).resolve().parents[2] / "build/core"
    path = directory / "pbi_abi_vectors"
    if not path.is_file() or not os.access(path, os.X_OK):
        if configured:
            pytest.fail("configured core build must contain pbi_abi_vectors")
        pytest.skip("run make test-core to enable C ABI damage differential tests")
    return path


def _reference() -> DamageContext:
    """无参数；返回冻结的螳螂物理钢系招式对仙子伊布的原测试输入。"""
    return DamageContext(
        attacker=BattlePokemon("scizor", 50, (Type.BUG, Type.STEEL), StatValues(177, 182, 120, 67, 100, 85)),
        defender=BattlePokemon("sylveon", 50, (Type.FAIRY,), StatValues(202, 85, 85, 130, 150, 80)),
        move=BattleMove("bullet-punch", Type.STEEL, MoveCategory.PHYSICAL, 40),
        ruleset=resolve_ruleset_by_generation(9),
    )


class TestCoreDamage:
    """逐项伤害/trace/精确 KO 差分，以及知识和规则显式失败合同。"""

    def test_frozen_reference(self, damage_runner: Path) -> None:
        """damage_runner 为真实 ABI 程序；冻结 16 档和 246/256 二击率防止 oracle 同改。"""
        result, = _DamageOracle.run(damage_runner, (_reference(),))
        assert result.rolls == (99, 100, 101, 102, 104, 105, 106, 107, 108, 109, 111, 112, 113, 114, 115, 117)
        assert result.two_hit.value() == Fraction(123, 128)

    def test_types_generations_and_combined_effects(self, damage_runner: Path) -> None:
        """damage_runner 为真实 ABI 程序；覆盖全部属性配对、9 代际及 3072 组组合效果。"""
        randomizer = random.Random(20261124)
        reference = _reference()
        contexts: list[DamageContext] = []
        types = tuple(Type)
        abilities = tuple(DamageAbility)[:7]
        items = tuple(DamageItem)
        for attacking in types:
            for defending in types:
                contexts.append(replace(reference,
                    attacker=replace(reference.attacker, types=(attacking,)),
                    defender=replace(reference.defender, types=(defending,)),
                    move=replace(reference.move, type=attacking)))
        for index in range(3072):
            move_type = randomizer.choice(types)
            attacker = replace(reference.attacker, level=randomizer.randint(1, 100),
                types=(move_type,) if index % 2 else tuple(randomizer.sample(types, 2)),
                stats=StatValues(*(randomizer.randint(1, 999) for _ in range(6))),
                ability=randomizer.choice(abilities), item=randomizer.choice(items),
                grounding_state=randomizer.choice((None, *GroundingState)))
            defender = replace(reference.defender, types=tuple(randomizer.sample(types, 2)),
                stats=StatValues(*(randomizer.randint(1, 999) for _ in range(6))),
                ability=randomizer.choice(abilities), item=randomizer.choice(items), can_evolve=bool(index % 2),
                grounding_state=randomizer.choice((None, *GroundingState)))
            contexts.append(replace(reference, attacker=attacker, defender=defender,
                move=replace(reference.move, type=move_type, category=randomizer.choice((MoveCategory.PHYSICAL, MoveCategory.SPECIAL)),
                             power=randomizer.choice((1, 59, 60, 61, 80, 120, 250))),
                ruleset=resolve_ruleset_by_generation(index % 9 + 1),
                environment=BattleEnvironment(weather=randomizer.choice((None, *Weather)), terrain=randomizer.choice((None, *Terrain)),
                    defender_side=SideConditions(bool(index & 1), bool(index & 2), bool(index & 4))),
                is_critical=bool(index & 8), is_spread_move=bool(index & 16),
                is_protect_reduced=bool(index & 32), is_multi_target_battle=bool(index & 64)))
        _DamageOracle.run(damage_runner, contexts)


    def test_custom_policy_and_floor_boundaries(self, damage_runner: Path) -> None:
        """damage_runner 为真实 ABI 程序；自定义全部策略、无序随机槽位及大整数除法不得漂移。"""
        reference = _reference()
        contexts: list[DamageContext] = []
        for generation in range(1, 10):
            ruleset = resolve_ruleset_by_generation(generation)
            policy = DamagePolicy(
                terrain_boost_multiplier=1.2345, misty_terrain_dragon_multiplier=0.3125,
                weather_boost_multiplier=1.625, weather_weaken_multiplier=0.375,
                sandstorm_rock_spdef_multiplier=1.125, snow_ice_defense_multiplier=1.875, hail_ice_defense_multiplier=1.25,
                screen_single_target_multiplier=0.625, screen_multi_target_multiplier=0.7,
                aurora_veil_single_target_multiplier=0.375, aurora_veil_multi_target_multiplier=0.8,
                critical_hit_multiplier=1.75, spread_move_multiplier=0.6, protect_damage_multiplier=0.3,
                same_type_attack_bonus_multiplier=1.8, technician_base_power_threshold=80, technician_base_power_multiplier=1.625,
                adaptability_stab_multiplier=2.125, thick_fat_damage_multiplier=0.625, filter_damage_multiplier=0.8,
                sniper_critical_multiplier=1.625, multiscale_damage_multiplier=0.3, life_orb_damage_multiplier=1.4,
                choice_item_attack_multiplier=1.625, expert_belt_damage_multiplier=1.25, eviolite_defense_multiplier=1.875,
                burn_physical_attack_multiplier=0.25, random_damage_multipliers=(1.0, 0.0, 0.25, 0.85, 0.85, 0.5),
            )
            for index in range(126):
                ability = tuple(DamageAbility)[index % 7]
                move_type = (Type.FIRE, Type.WATER, Type.ELECTRIC, Type.PSYCHIC, Type.GRASS, Type.DRAGON, Type.ICE)[index % 7]
                contexts.append(replace(reference,
                    attacker=replace(reference.attacker, types=(move_type,), ability=ability, item=tuple(DamageItem)[index % 6]),
                    defender=replace(reference.defender, types=(Type.ROCK, Type.ICE),
                        ability=tuple(DamageAbility)[(index // 7) % 7], item=DamageItem.EVIOLITE, can_evolve=True),
                    move=replace(reference.move, type=move_type, category=MoveCategory.SPECIAL if index % 2 else MoveCategory.PHYSICAL),
                    ruleset=replace(ruleset, damage_policy=policy),
                    environment=BattleEnvironment(weather=tuple(Weather)[index % len(Weather)],
                        terrain=tuple(Terrain)[index % len(Terrain)], defender_side=SideConditions(True, True, True)),
                    is_critical=bool(index & 1), is_spread_move=True, is_protect_reduced=True, is_multi_target_battle=bool(index & 2)))
        # 分子超过 2**53 但结果仍在 int64；CPython int/int 正确舍入不能以 float(n)/float(d) 替代。
        for attack in (2147483647, 2147483601, 2000000001):
            for defense in (3, 101, 2147483647):
                contexts.append(replace(reference,
                    attacker=replace(reference.attacker, level=100, stats=replace(reference.attacker.stats, attack=attack)),
                    defender=replace(reference.defender, stats=replace(reference.defender.stats, defense=defense)),
                    move=replace(reference.move, power=2147483647)))
        _DamageOracle.run(damage_runner, contexts)


def benchmark_damage(runner: Path, count: int, repeats: int, output: Path) -> None:
    """测量当前冻结伤害批次并写出真实样本，不修改生产/知识数据。

    Args:
        runner: 已构建的真实 C ABI 进程入口。
        count: 每次伤害计算数量，必须为正。
        repeats: 两端采样次数，必须为正。
        output: JSON 报告路径，父目录按需创建。
    """
    if count <= 0 or repeats <= 0:
        raise ValueError("count and repeats must be positive")
    context = _reference()
    reference, = _DamageOracle.run(runner, (context,))
    operation = _DamageOracle.operation(context)
    requests = "\n".join(DamageBatch(operations=(operation,) * min(100, count - start)).model_dump_json()
                         for start in range(0, count, 100)) + "\n"
    python_times: list[float] = []
    cpp_times: list[float] = []
    expected = calculate_damage_rolls(context)
    result_digest = ""
    for _ in range(repeats):
        started = time.perf_counter()
        python_results = tuple(calculate_damage_rolls(context) for _ in range(count))
        python_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        completed = subprocess.run([str(runner)], input=requests, text=True, capture_output=True, check=True, timeout=60)
        cpp_times.append(time.perf_counter() - started)
        actual = tuple(result for line in completed.stdout.splitlines() for result in DamageEnvelope.model_validate_json(line).results)
        if len(actual) != count or any(result != reference for result in actual) or any(result != expected for result in python_results):
            raise RuntimeError("damage benchmark results differ from the frozen oracle")
        result_digest = hashlib.sha256(completed.stdout.encode()).hexdigest()
    compiler = subprocess.run(["c++", "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    report = DamageBenchmark(
        case_count=count, repeats=repeats, platform=platform.platform(), python_version=platform.python_version(), compiler=compiler,
        binary_sha256=hashlib.sha256(runner.read_bytes()).hexdigest(), result_sha256=result_digest,
        python_seconds=tuple(python_times), cpp_process_seconds=tuple(cpp_times),
        python_median_seconds=statistics.median(python_times), cpp_process_median_seconds=statistics.median(cpp_times),
        measurement_boundary="Python: direct damage and full trace objects. C++: process, input JSON, direct damage, exact KO, full output JSON and IPC. Request generation and oracle checks excluded. Shared NAS; no full battle or pure C ABI speedup claim.",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(output)


def main() -> None:
    """解析独立 benchmark 参数并运行；普通 pytest 收集不会执行此入口。"""
    parser = argparse.ArgumentParser(description="Benchmark verified direct damage via the actual C ABI runner")
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    benchmark_damage(args.runner, args.count, args.repeats, args.output)


if __name__ == "__main__":
    main()
