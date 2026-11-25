"""提供 issue #92 固定二十招式候选池与惰性配置对生成器。"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from fractions import Fraction
from itertools import combinations

from pokeop.application.configuration_space import (
    BattleConfiguration,
    ConfiguredMove,
    PokemonBattleConfiguration,
)
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.use_cases.infer_one_on_one_battle import BattleActionPolicyKind
from pokeop.application.use_cases.stream_configuration_pairs.models import (
    ConfigurationPairWorkItem,
)
from pokeop.benchmarks.models import (
    BenchmarkCaseInput,
    BenchmarkWorkloadKind,
    BenchmarkWorkloadSpec,
)
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.specs import MoveSpec
from pokeop.domain.battle.stats import StatProfile, StatValues
from pokeop.domain.models.types import Type


WORKLOADS: tuple[BenchmarkWorkloadSpec, ...] = (
    BenchmarkWorkloadSpec(
        workload_id="attack-19x1",
        description="极端不对称纯攻击池，固定验证 3,876 个配置对。",
        attacker_move_count=19,
        defender_move_count=1,
        kind=BenchmarkWorkloadKind.ATTACK_ONLY,
        graph_limits=StateGraphLimits(max_nodes=20_000, max_edges=80_000, max_turns=20),
    ),
    BenchmarkWorkloadSpec(
        workload_id="attack-12x8",
        description="中度不对称纯攻击池，固定验证 34,650 个配置对。",
        attacker_move_count=12,
        defender_move_count=8,
        kind=BenchmarkWorkloadKind.ATTACK_ONLY,
        graph_limits=StateGraphLimits(max_nodes=20_000, max_edges=80_000, max_turns=20),
    ),
    BenchmarkWorkloadSpec(
        workload_id="attack-10x10",
        description="对称纯攻击池，固定验证最大 44,100 个配置对。",
        attacker_move_count=10,
        defender_move_count=10,
        kind=BenchmarkWorkloadKind.ATTACK_ONLY,
        graph_limits=StateGraphLimits(max_nodes=20_000, max_edges=80_000, max_turns=20),
    ),
    BenchmarkWorkloadSpec(
        workload_id="mixed-10x10",
        description="攻击、无伤害状态与具体 move effect 混合的中等图规模场景。",
        attacker_move_count=10,
        defender_move_count=10,
        kind=BenchmarkWorkloadKind.MIXED,
        graph_limits=StateGraphLimits(max_nodes=20_000, max_edges=80_000, max_turns=20),
    ),
    BenchmarkWorkloadSpec(
        workload_id="cyclic-10x10",
        description="以无伤害状态招式为主，验证循环、SCC 与显式回合截断。",
        attacker_move_count=10,
        defender_move_count=10,
        kind=BenchmarkWorkloadKind.CYCLIC,
        graph_limits=StateGraphLimits(max_nodes=20_000, max_edges=80_000, max_turns=20),
    ),
    BenchmarkWorkloadSpec(
        workload_id="budget-stop-10x10",
        description="使用紧预算的循环池，验证部分覆盖与具体截断配置可追溯。",
        attacker_move_count=10,
        defender_move_count=10,
        kind=BenchmarkWorkloadKind.CYCLIC,
        graph_limits=StateGraphLimits(max_nodes=500, max_edges=2_000, max_turns=8),
    ),
)


def workload_by_id(workload_id: str) -> BenchmarkWorkloadSpec:
    """按稳定 ID 读取固定 workload。

    Args:
        workload_id: CLI 与报告使用的规范化 workload 标识。

    Returns:
        与标识完全匹配的不可变 workload 规格。

    Raises:
        ValueError: 当前 fixture 版本不存在该标识。
    """
    for workload in WORKLOADS:
        if workload.workload_id == workload_id:
            return workload
    raise ValueError(f"unknown workload_id: {workload_id}")


def iter_benchmark_cases(
    workload: BenchmarkWorkloadSpec,
    *,
    skip_pair_ids: frozenset[str] = frozenset(),
) -> Iterator[BenchmarkCaseInput]:
    """惰性生成 workload 全部配置对，避免预构造 44,100 个 case 对象。

    Args:
        workload: 固定候选分配、机制类型和单 pair 图限制。
        skip_pair_ids: 恢复执行时已经完成的稳定 pair ID 集合。

    Yields:
        可直接在当前进程或子进程执行的不可变配置对输入。
    """
    attacker_moves, defender_moves = _move_pools(workload)
    attacker_configurations = _side_configurations(
        side="attacker",
        pokemon_id=149,
        move_pool=attacker_moves,
    )
    defender_configurations = _side_configurations(
        side="defender",
        pokemon_id=461,
        move_pool=defender_moves,
    )
    rules = BattleInferenceRules(
        version_group_id=31,
        max_turns=workload.graph_limits.max_turns,
    )
    total_pairs = workload.pair_count
    weight = Fraction(1, total_pairs)
    for attacker_id, attacker in attacker_configurations:
        for defender_id, defender in defender_configurations:
            pair_id = _pair_id(workload.workload_id, attacker_id, defender_id)
            if pair_id in skip_pair_ids:
                continue
            yield BenchmarkCaseInput(
                work_item=ConfigurationPairWorkItem(
                    pair_id=pair_id,
                    attacker_configuration_id=attacker_id,
                    defender_configuration_id=defender_id,
                    configuration_weight=weight,
                    configuration=BattleConfiguration(
                        attacker=attacker,
                        defender=defender,
                    ),
                ),
                rules=rules,
                attacker_policy=BattleActionPolicyKind.UNIFORM_RANDOM,
                defender_policy=BattleActionPolicyKind.UNIFORM_RANDOM,
                graph_limits=workload.graph_limits,
            )


def _move_pools(
    workload: BenchmarkWorkloadSpec,
) -> tuple[tuple[ConfiguredMove, ...], tuple[ConfiguredMove, ...]]:
    """根据固定机制类型生成双方合计二十个合成招式快照。

    Args:
        workload: 决定机制类别与双方候选切分位置的固定规格。

    Returns:
        攻击方和防守方候选招式元组，顺序与 fixture 版本稳定一致。
    """
    moves = tuple(_configured_move(workload.kind, index) for index in range(20))
    split = workload.attacker_move_count
    return moves[:split], moves[split:]


def _configured_move(kind: BenchmarkWorkloadKind, index: int) -> ConfiguredMove:
    """创建稳定 ID、PP、分类和可选 effect 的合成 benchmark 招式。

    Args:
        kind: 纯攻击、混合机制或循环风险类别。
        index: fixture 中从零开始的招式位置，用于派生稳定 ID 和字段。

    Returns:
        可直接进入 application 配置和真实回合 resolver 的招式快照。
    """
    move_id = 90_000 + index
    effect_identifier: str | None = None
    if kind is BenchmarkWorkloadKind.ATTACK_ONLY:
        category = MoveCategory.PHYSICAL if index % 2 == 0 else MoveCategory.SPECIAL
        power = 55 + (index % 5) * 10
    elif kind is BenchmarkWorkloadKind.MIXED:
        if index % 5 == 0:
            category = MoveCategory.STATUS
            power = 0
        else:
            category = MoveCategory.PHYSICAL if index % 2 == 0 else MoveCategory.SPECIAL
            power = 50 + (index % 4) * 15
            effect_identifier = ("ice_punch", "fake_out", "brick_break")[index % 3]
    else:
        if index % 3:
            category = MoveCategory.STATUS
            power = 0
        else:
            category = MoveCategory.PHYSICAL
            power = 20
    return ConfiguredMove(
        move_spec=MoveSpec(
            move_id=move_id,
            move=BattleMove(
                name=f"benchmark-move-{index:02d}",
                type=Type.NORMAL,
                category=category,
                power=power,
            ),
            max_pp=20,
        ),
        effect_identifier=effect_identifier,
    )


def _side_configurations(
    *,
    side: str,
    pokemon_id: int,
    move_pool: tuple[ConfiguredMove, ...],
) -> tuple[tuple[str, PokemonBattleConfiguration], ...]:
    """把候选池转换为产品规范的单边配置集合。

    Args:
        side: 用于稳定配置 ID 和展示名称的 attacker 或 defender。
        pokemon_id: 合成配置使用的正整数 Pokémon ID。
        move_pool: 一侧固定候选池；达到四招时枚举无序四招组合。

    Returns:
        稳定配置 ID 与不可变 Pokémon 配置组成的元组。
    """
    selected_sets = combinations(move_pool, min(4, len(move_pool)))
    base_stats = StatValues(80, 90, 80, 90, 80, 90)
    result: list[tuple[str, PokemonBattleConfiguration]] = []
    for selected in selected_sets:
        move_ids = tuple(move.move_spec.move_id for move in selected)
        configuration_id = f"{side}-" + "-".join(str(value) for value in move_ids)
        result.append(
            (
                configuration_id,
                PokemonBattleConfiguration(
                    ruleset_id="pokemon-champion",
                    version_group_id=31,
                    pokemon_id=pokemon_id,
                    name=f"benchmark-{side}",
                    level=50,
                    types=(Type.NORMAL,),
                    stats=StatValues(155, 120, 110, 120, 110, 120),
                    stat_profile=StatProfile(base_stats=base_stats),
                    moves=tuple(selected),
                    ability_identifier="none",
                    item_identifier="none",
                    can_evolve=False,
                ),
            )
        )
    return tuple(result)


def _pair_id(workload_id: str, attacker_id: str, defender_id: str) -> str:
    """根据 workload 与双方配置 ID 生成可恢复的稳定 pair ID。

    Args:
        workload_id: 固定 fixture 中的 workload 标识。
        attacker_id: 攻击方规范化配置 ID。
        defender_id: 防守方规范化配置 ID。

    Returns:
        带 workload 前缀的 SHA-256 幂等配置对标识。
    """
    digest = hashlib.sha256(
        f"{workload_id}\0{attacker_id}\0{defender_id}".encode("utf-8")
    ).hexdigest()
    return f"bench-{workload_id}-{digest}"


__all__ = ["WORKLOADS", "iter_benchmark_cases", "workload_by_id"]
