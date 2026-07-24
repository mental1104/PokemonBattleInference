"""验证固定技能组置换不会改变配置、状态图和精确概率。"""

from __future__ import annotations

from dataclasses import replace
from itertools import permutations

from pokeop.application.battle_inference_effect_factory import (
    TransparentPokemonChampionEffectFactory,
)
from pokeop.application.composition.battle_inference_repository import (
    FactoryReconciledBattleInferenceRepository,
)
from pokeop.application.configuration_space import (
    GenerateConfigurationSpaceCommand,
    PokemonSpaceCommand,
)
from pokeop.application.repositories.battle_inference import (
    MechanismSupportStatus,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
    InferConfigurationSpaceBattleCommand,
    InferFixedOneOnOneBattleCommand,
    InferOneOnOneBattleUseCase,
    PokemonInferenceSelection,
)
from pokeop.domain.models.types import Type
from tests.application.use_cases.test_infer_one_on_one_battle import (
    _RULESET,
    _Repository,
    _dragonite,
    _move,
    _type,
    _weavile,
)


def _permutation_invariant_use_case() -> InferOneOnOneBattleUseCase:
    """创建四个同覆盖高威力招式组成的置换不变固定推演夹具。

    Returns:
        使用真实配置生成、回合解析、状态图与精确求解器的 application 用例。
    """
    fighting = _type(2, "fighting", Type.FIGHTING)
    attacker = replace(
        _dragonite(),
        moves=tuple(
            _move(
                move_id,
                f"permutation-move-{move_id}",
                fighting,
                500,
                support_status=MechanismSupportStatus.SUPPORTED,
            )
            for move_id in (1001, 1002, 1003, 1004)
        ),
    )
    effect_factory = TransparentPokemonChampionEffectFactory()
    repository = FactoryReconciledBattleInferenceRepository(
        repository=_Repository({149: attacker, 461: _weavile()}),
        effect_factory=effect_factory,
    )
    return InferOneOnOneBattleUseCase(
        repository=repository,
        effect_factory=effect_factory,
    )


def test_all_four_move_permutations_share_configuration_graph_and_probabilities() -> None:
    """验证四招 24 种输入顺序收敛到同一配置、初始状态图和精确胜负概率。"""
    use_case = _permutation_invariant_use_case()
    signatures = set()

    for move_order in permutations((1001, 1002, 1003, 1004)):
        selection = PokemonInferenceSelection(
            pokemon_id=149,
            move_ids=move_order,
            ability_identifier="multiscale",
        )
        result = use_case.execute_fixed(
            InferFixedOneOnOneBattleCommand(
                rules=_RULESET,
                attacker=selection,
                defender=PokemonInferenceSelection(
                    pokemon_id=461,
                    move_ids=(8,),
                    ability_identifier="pressure",
                ),
                attacker_policy=BattleActionPolicyKind.UNIFORM_RANDOM,
            )
        )
        graph = result.exploration.graph_artifact
        assert graph is not None
        root_state = graph.node(graph.root_node_id).state
        inference = result.summary.inference
        signatures.add(
            (
                selection.move_ids,
                result.summary.configuration.attacker.move_ids,
                root_state.state_key,
                tuple(
                    (slot.slot_id, slot.move_id)
                    for slot in root_state.attacker.move_slots
                ),
                inference.win_probability.value,
                inference.loss_probability.value,
                inference.draw_probability.value,
                result.summary.graph_statistics.unique_state_count,
                result.summary.graph_statistics.edge_count,
            )
        )

    assert len(signatures) == 1
    signature = signatures.pop()
    assert signature[0] == (1001, 1002, 1003, 1004)
    assert signature[1] == (1001, 1002, 1003, 1004)
    assert signature[3] == (
        (1001, 1001),
        (1002, 1002),
        (1003, 1003),
        (1004, 1004),
    )


def test_configuration_space_product_command_defaults_to_uniform_random() -> None:
    """验证批量产品入口不再把依赖槽位顺序的 FIRST_LEGAL 作为默认策略。"""
    command = InferConfigurationSpaceBattleCommand(
        rules=_RULESET,
        attacker_pokemon_id=149,
        defender_pokemon_id=461,
        configuration_space=GenerateConfigurationSpaceCommand(
            attacker=PokemonSpaceCommand(),
            defender=PokemonSpaceCommand(),
        ),
    )

    assert command.attacker_policy is BattleActionPolicyKind.UNIFORM_RANDOM
    assert command.defender_policy is BattleActionPolicyKind.UNIFORM_RANDOM
