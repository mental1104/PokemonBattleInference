"""验证推演 HTTP 顶层合同不会混淆全局结论与当前探索路径。"""

from fractions import Fraction

from pokeop.api.schemas.inference import battle_inference_journey_response
from pokeop.application.solver.models import (
    GraphNodeId,
    StateGraphBuildResult,
    StateGraphStatistics,
    StateGraphTerminalCounts,
)
from pokeop.application.use_cases.infer_battle import (
    BattleInferenceResult,
    BattleProbability,
    ConfigurationCoverage,
    ConfigurationWeighting,
    ConfigurationWeightSource,
    MechanismCoverage,
    OutcomeCounts,
    PolicyDescriptor,
    RepresentativePathReference,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BATTLE_INFERENCE_CALCULATION_REVISION,
    BattleConfigurationSummary,
    BattleExplorationEntry,
    BattleInferenceCompleteness,
    BattleInferenceSummary,
    FixedOneOnOneBattleResult,
    GraphInferenceSummary,
    PokemonConfigurationSummary,
    RepresentativeBattlePath,
    RepresentativePathStep,
)
from pokeop.domain.battle.inference_outcome import BattleSide, TerminalOutcome
from pokeop.domain.battle.inference_rules import BattleInferenceRules


def _pokemon_summary(pokemon_id: int, name: str) -> PokemonConfigurationSummary:
    """创建 API 合同测试需要的一侧最小配置摘要。

    Args:
        pokemon_id: PokeAPI Pokémon 稳定整数 ID。
        name: 测试展示名称。

    Returns:
        具备完整能力值和单招式字段的 application 配置 DTO。
    """
    return PokemonConfigurationSummary(
        pokemon_id=pokemon_id,
        name=name,
        level=50,
        ability_identifier="test-ability",
        item_identifier="none",
        move_ids=(1,),
        move_names=("test-move",),
        hp=150,
        attack=120,
        defense=100,
        special_attack=90,
        special_defense=100,
        speed=110,
        dimension_labels=(("moves", "test-move"),),
    )


def _result() -> FixedOneOnOneBattleResult:
    """构造同时持有全局 summary 与完整图 artifact 的稳定 application 结果。

    Returns:
        可直接交给 HTTP schema 转换器的固定 1v1 推演结果。
    """
    rules = BattleInferenceRules(version_group_id=25)
    representative_path = RepresentativeBattlePath(
        reference="path:attacker-win:node-1",
        outcome=TerminalOutcome.ATTACKER_WIN,
        steps=(
            RepresentativePathStep(
                node_id=0,
                turn_number=1,
                phase="action-selection",
                attacker_hp=150,
                defender_hp=150,
                outcome="non-terminal",
                events=(),
            ),
        ),
    )
    inference = BattleInferenceResult(
        rules=rules,
        observer=BattleSide.ATTACKER,
        win_probability=BattleProbability(Fraction(3, 4)),
        loss_probability=BattleProbability(Fraction(1, 4)),
        draw_probability=BattleProbability(Fraction(0)),
        expected_turns=Fraction(5, 2),
        attacker_policy=PolicyDescriptor(
            policy_id="first-legal-action",
            description="测试攻击策略",
        ),
        defender_policy=PolicyDescriptor(
            policy_id="uniform-random",
            description="测试防守策略",
        ),
        configuration_coverage=ConfigurationCoverage(1, 1),
        configuration_weighting=ConfigurationWeighting(
            source=ConfigurationWeightSource.FIXED_CONFIGURATION,
            description="固定测试配置",
        ),
        mechanism_coverage=MechanismCoverage(
            included=("move:test-move",),
            excluded=("ability:test-ability:real-behavior",),
        ),
        representative_paths=(
            RepresentativePathReference(
                outcome=TerminalOutcome.ATTACKER_WIN,
                reference=representative_path.reference,
            ),
        ),
        outcome_counts=OutcomeCounts(
            attacker_wins=1,
            defender_wins=1,
            draws=0,
        ),
    )
    graph_artifact = StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=(),
        edges=(),
        components=(),
        statistics=StateGraphStatistics(
            unique_state_count=2,
            edge_count=1,
            max_turn_number=2,
            terminal_counts=StateGraphTerminalCounts(
                attacker_wins=1,
                defender_wins=1,
                draws=0,
                non_terminal=0,
                unknown=0,
            ),
            closed_cycle_count=0,
            terminal_reachable_cycle_count=0,
        ),
    )
    return FixedOneOnOneBattleResult(
        summary=BattleInferenceSummary(
            configuration=BattleConfigurationSummary(
                attacker=_pokemon_summary(149, "dragonite"),
                defender=_pokemon_summary(461, "weavile"),
            ),
            inference=inference,
            graph_statistics=GraphInferenceSummary(
                unique_state_count=2,
                edge_count=1,
                max_turn_number=2,
                closed_cycle_count=0,
                terminal_reachable_cycle_count=0,
                is_complete=True,
                truncation_reasons=(),
            ),
            representative_paths=(representative_path,),
            completeness=BattleInferenceCompleteness(
                graph_complete=True,
                solver_status="solved",
                truncation_reasons=(),
                diagnostics=(),
            ),
        ),
        exploration=BattleExplorationEntry(
            root_node_id=0,
            calculation_revision=BATTLE_INFERENCE_CALCULATION_REVISION,
            expandable=True,
            graph_artifact=graph_artifact,
            graph_handle=None,
        ),
    )


def test_response_separates_global_summary_from_exploration_entry() -> None:
    """验证代表路径只属于 summary，完整图 artifact 不会泄漏到 HTTP JSON。

    顶层必须只有 ``summary`` 与 ``exploration``。胜负概率、图统计和代表路径来自
    完整求解结果；exploration 只暴露根节点、可选 graph ID、计算版本与可展开状态，
    因而代表路径不能被误当成用户当前选择路径或后续节点查询入口。
    """
    payload = battle_inference_journey_response(_result()).model_dump()

    assert set(payload) == {"summary", "exploration"}
    assert payload["summary"]["win_probability"]["numerator"] == 3
    assert payload["summary"]["loss_probability"]["numerator"] == 1
    assert payload["summary"]["graph"]["unique_state_count"] == 2
    assert payload["summary"]["representative_paths"][0]["reference"] == (
        "path:attacker-win:node-1"
    )
    assert "representative_paths" not in payload["exploration"]
    assert "graph_artifact" not in payload["exploration"]
    assert payload["exploration"] == {
        "root_node_id": 0,
        "graph_id": None,
        "calculation_revision": BATTLE_INFERENCE_CALCULATION_REVISION,
        "expandable": True,
    }
