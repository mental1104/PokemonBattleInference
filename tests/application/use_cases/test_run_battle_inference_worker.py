"""验证子进程输入边界和单/多进程结果一致性。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

from pokeop.application.configuration_space import (
    BattleConfiguration,
    ConfiguredMove,
    PokemonBattleConfiguration,
)
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
)
from pokeop.application.use_cases.run_battle_inference_worker import (
    PreparedBattleInferenceCase,
    execute_prepared_battle_inference_case,
)
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.specs import MoveSpec
from pokeop.domain.battle.stats import StatProfile, StatValues
from pokeop.domain.models.types import Type


def _pokemon(pokemon_id: int, move_id: int) -> PokemonBattleConfiguration:
    """创建可 pickle 且会在极小图预算下快速结束的合成配置。"""
    base_stats = StatValues(80, 90, 80, 70, 80, 90)
    return PokemonBattleConfiguration(
        ruleset_id="pokemon-champion",
        version_group_id=31,
        pokemon_id=pokemon_id,
        name=f"pokemon-{pokemon_id}",
        level=50,
        types=(Type.NORMAL,),
        stats=StatValues(155, 120, 110, 100, 110, 120),
        stat_profile=StatProfile(base_stats=base_stats),
        moves=(
            ConfiguredMove(
                move_spec=MoveSpec(
                    move_id=move_id,
                    move=BattleMove(
                        f"move-{move_id}",
                        Type.NORMAL,
                        MoveCategory.PHYSICAL,
                        50,
                    ),
                    max_pp=10,
                ),
                effect_identifier=None,
            ),
        ),
        ability_identifier="none",
        item_identifier="none",
        can_evolve=False,
    )


def test_process_pool_matches_direct_single_configuration_result() -> None:
    """相同不可变输入在当前进程和子进程必须产生完全相同的轻量摘要。"""
    rules = BattleInferenceRules(
        ruleset_id="pokemon-champion",
        version_group_id=31,
        level=50,
        max_turns=1,
    )
    prepared = PreparedBattleInferenceCase(
        configuration_pair_id="pair-87",
        attacker_configuration_id="attacker-87",
        defender_configuration_id="defender-87",
        configuration=BattleConfiguration(
            attacker=_pokemon(149, 1),
            defender=_pokemon(461, 2),
        ),
        rules=rules,
        attacker_policy=BattleActionPolicyKind.FIRST_LEGAL,
        defender_policy=BattleActionPolicyKind.FIRST_LEGAL,
        graph_limits=StateGraphLimits(max_nodes=20, max_edges=40, max_turns=1),
    )

    direct = execute_prepared_battle_inference_case(prepared)
    with ProcessPoolExecutor(max_workers=1) as executor:
        parallel = executor.submit(
            execute_prepared_battle_inference_case,
            prepared,
        ).result(timeout=30)

    assert parallel == direct
    assert parallel.pair_id == "pair-87"
