"""验证通用 1v1 技能池合同、规范化身份和批量聚合语义。"""

from __future__ import annotations

import json
from dataclasses import fields
from fractions import Fraction
from pathlib import Path

import pytest

from pokeop.application.configuration_space.one_on_one import (
    BatchProbabilitySummary,
    ConfigurationCoverageSummary,
    ConfigurationDimensionMode,
    ConfigurationExecutionStatus,
    ConfigurationIssuePage,
    ConfigurationReference,
    ConfigurationTaskProgress,
    ConfigurationTaskStatus,
    ExactRatio,
    FailedConfigurationDetail,
    FixedPokemonConfiguration,
    MechanismAdmissionPolicy,
    MechanismCoverageSummary,
    GraphStatisticsSummary,
    MoveCandidatePool,
    NormalizedOneOnOneConfiguration,
    ONE_ON_ONE_CONTRACT_VERSION,
    OnDemandGraphRequest,
    OnDemandGraphResult,
    OneOnOneActionPolicy,
    OneOnOneBatchSummary,
    OneOnOneConfigurationWeightAssumption,
    OneOnOneContractError,
    OneOnOneDimensionModes,
    OneOnOneMovePoolCommand,
    PokemonMovePoolSelection,
    SuccessfulConfigurationSummary,
    TruncatedConfigurationDetail,
    count_configuration_pairs,
    count_move_sets,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "web"
    / "src"
    / "fixtures"
    / "contracts"
    / "one_on_one_move_pool.v1.json"
)


@pytest.mark.parametrize(
    ("candidate_count", "expected_count"),
    ((1, 1), (3, 1), (4, 1), (10, 210)),
)
def test_move_set_count_freezes_v1_combination_semantics(
    candidate_count: int,
    expected_count: int,
) -> None:
    """1、3、4、10 个候选必须分别生成 1、1、1、210 个无序技能组。"""
    assert count_move_sets(candidate_count) == expected_count


def test_maximum_twenty_move_budget_generates_44100_configuration_pairs() -> None:
    """10+10 的最坏预算必须精确生成 210×210 个配置对。"""
    assert count_configuration_pairs(10, 10) == 44_100


def test_candidate_budget_rejects_more_than_twenty_moves() -> None:
    """双方总候选数超过 20 时必须在进入后台任务前快速失败。"""
    with pytest.raises(OneOnOneContractError, match="total at most 20"):
        count_configuration_pairs(10, 11)


def test_configuration_id_is_invariant_to_move_order() -> None:
    """相同 move_id 集合的点击顺序和初始槽位排列不得改变配置 ID。"""
    first = _configuration(
        revision="battle-inference.summary-exploration.v1",
        attacker_move_ids=(355, 245, 280),
        defender_move_ids=(420, 252, 269, 400),
    )
    reordered = _configuration(
        revision="battle-inference.summary-exploration.v1",
        attacker_move_ids=(280, 355, 245),
        defender_move_ids=(269, 420, 400, 252),
    )

    assert first.attacker_move_ids == (245, 280, 355)
    assert first.defender_move_ids == (252, 269, 400, 420)
    assert first.configuration_id == reordered.configuration_id


def test_calculation_revision_invalidates_configuration_id() -> None:
    """计算语义修订变化必须生成不同 ID，阻止旧结果或缓存被错误复用。"""
    previous = _configuration(
        revision="battle-inference.summary-exploration.v1",
        attacker_move_ids=(245,),
        defender_move_ids=(252,),
    )
    incompatible = _configuration(
        revision="battle-inference.summary-exploration.v2",
        attacker_move_ids=(245,),
        defender_move_ids=(252,),
    )

    assert previous.configuration_id != incompatible.configuration_id


def test_batch_summary_preserves_failed_and_truncated_denominator() -> None:
    """失败和截断权重必须进入 unresolved 字段，而不是对成功子集重新归一化。"""
    summary = OneOnOneBatchSummary(
        task_id="task-82",
        contract_version=ONE_ON_ONE_CONTRACT_VERSION,
        ruleset_id="pokemon-champion",
        version_group_id=31,
        calculation_revision="battle-inference.summary-exploration.v1",
        weight_assumption=(
            OneOnOneConfigurationWeightAssumption.UNIFORM_CONFIGURATION_PAIR
        ),
        attacker_policy=OneOnOneActionPolicy.UNIFORM_RANDOM_LEGAL_ACTION,
        defender_policy=OneOnOneActionPolicy.UNIFORM_RANDOM_LEGAL_ACTION,
        coverage=ConfigurationCoverageSummary(
            total_configuration_count=4,
            success_count=2,
            failed_count=1,
            truncated_count=1,
            success_weight=ExactRatio(1, 2),
            failed_weight=ExactRatio(1, 4),
            truncated_weight=ExactRatio(1, 4),
        ),
        probabilities=BatchProbabilitySummary(
            win_probability=ExactRatio(3, 8),
            loss_probability=ExactRatio(1, 8),
            draw_probability=ExactRatio(0, 1),
            unresolved_configuration_weight=ExactRatio(1, 2),
        ),
        mechanism_coverage=MechanismCoverageSummary(
            included=("move:245",),
            excluded_partial=("move:355",),
            excluded_unsupported=("move:9999",),
        ),
    )

    assert summary.coverage.success_weight.value == Fraction(1, 2)
    assert summary.probabilities.unresolved_configuration_weight.value == Fraction(1, 2)
    assert "graph_artifact" not in {field.name for field in fields(OneOnOneBatchSummary)}


def test_fixture_keeps_python_contract_and_frontend_fields_in_sync() -> None:
    """共享 JSON fixture 必须能直接构造 Python DTO，并固定关键枚举和配置身份。"""
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    command_data = fixture["command"]
    command = OneOnOneMovePoolCommand(
        contract_version=command_data["contract_version"],
        ruleset_id=command_data["ruleset_id"],
        version_group_id=command_data["version_group_id"],
        calculation_revision=command_data["calculation_revision"],
        attacker=_selection(command_data["attacker"]),
        defender=_selection(command_data["defender"]),
        dimensions=OneOnOneDimensionModes(
            **{
                key: ConfigurationDimensionMode(value)
                for key, value in command_data["dimensions"].items()
            }
        ),
        weight_assumption=OneOnOneConfigurationWeightAssumption(
            command_data["weight_assumption"]
        ),
        attacker_policy=OneOnOneActionPolicy(command_data["attacker_policy"]),
        defender_policy=OneOnOneActionPolicy(command_data["defender_policy"]),
        mechanism_admission=MechanismAdmissionPolicy(
            command_data["mechanism_admission"]
        ),
    )
    configuration = next(command.iter_configurations())

    assert fixture["contract_version"] == ONE_ON_ONE_CONTRACT_VERSION
    assert {field.name for field in fields(OneOnOneMovePoolCommand)} == set(
        command_data
    )
    assert {field.name for field in fields(PokemonMovePoolSelection)} == set(
        command_data["attacker"]
    )
    assert {field.name for field in fields(OneOnOneBatchSummary)} == set(
        fixture["batch_summary"]
    )
    assert {field.name for field in fields(SuccessfulConfigurationSummary)} == set(
        fixture["batch_summary"]["top_configurations"][0]
    )
    assert {field.name for field in fields(ConfigurationReference)} == set(
        fixture["batch_summary"]["top_configurations"][0]["configuration"]
    )
    assert {field.name for field in fields(ConfigurationIssuePage)} == set(
        fixture["issue_page"]
    )
    assert {field.name for field in fields(FailedConfigurationDetail)} == set(
        fixture["issue_page"]["items"][0]
    )
    assert {field.name for field in fields(TruncatedConfigurationDetail)} == set(
        fixture["issue_page"]["items"][1]
    )
    assert fixture["enum_values"]["dimension_mode"] == [
        value.value for value in ConfigurationDimensionMode
    ]
    assert fixture["enum_values"]["configuration_weight_assumption"] == [
        value.value for value in OneOnOneConfigurationWeightAssumption
    ]
    assert fixture["enum_values"]["action_policy"] == [
        value.value for value in OneOnOneActionPolicy
    ]
    assert fixture["enum_values"]["mechanism_admission_policy"] == [
        value.value for value in MechanismAdmissionPolicy
    ]
    assert fixture["enum_values"]["configuration_execution_status"] == [
        value.value for value in ConfigurationExecutionStatus
    ]
    assert fixture["enum_values"]["configuration_task_status"] == [
        value.value for value in ConfigurationTaskStatus
    ]
    assert command.configuration_pair_count == fixture["expected"][
        "configuration_pair_count"
    ]
    assert configuration.configuration_id == fixture["expected"]["configuration_id"]


def test_fixture_exposes_stable_progress_and_on_demand_graph_request_types() -> None:
    """任务进度和按需图请求 fixture 必须通过同一组 DTO 校验。"""
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    progress_data = fixture["task_progress"]
    issue_page_data = fixture["issue_page"]
    request_data = fixture["on_demand_graph_request"]

    progress = ConfigurationTaskProgress(
        task_id=progress_data["task_id"],
        status=ConfigurationTaskStatus(progress_data["status"]),
        total_configuration_count=progress_data["total_configuration_count"],
        processed_count=progress_data["processed_count"],
        success_count=progress_data["success_count"],
        failed_count=progress_data["failed_count"],
        truncated_count=progress_data["truncated_count"],
        cancellation_requested=progress_data["cancellation_requested"],
    )
    issue_page = ConfigurationIssuePage(
        task_id=issue_page_data["task_id"],
        offset=issue_page_data["offset"],
        limit=issue_page_data["limit"],
        total=issue_page_data["total"],
        items=(
            _failed_detail(issue_page_data["items"][0]),
            _truncated_detail(issue_page_data["items"][1]),
        ),
    )
    graph_request = OnDemandGraphRequest(**request_data)
    graph_result = OnDemandGraphResult(
        configuration_id=graph_request.configuration_id,
        calculation_revision=graph_request.calculation_revision,
        root_node_id=0,
        graph_artifact=object(),
    )

    assert progress.progress.value == Fraction(3, 4)
    assert issue_page.total == 2
    assert graph_request.configuration_id == fixture["expected"]["configuration_id"]
    assert graph_result.root_node_id == 0


def _configuration(
    *,
    revision: str,
    attacker_move_ids: tuple[int, ...],
    defender_move_ids: tuple[int, ...],
) -> NormalizedOneOnOneConfiguration:
    """创建只用于合同身份测试的固定快龙/玛纽拉配置。"""
    return NormalizedOneOnOneConfiguration(
        ruleset_id="pokemon-champion",
        version_group_id=31,
        calculation_revision=revision,
        attacker=FixedPokemonConfiguration(
            pokemon_id=149,
            form_id=None,
            level=50,
            stat_profile_id="max_atk_plus",
            ability_identifier="multiscale",
            item_identifier=None,
        ),
        attacker_move_ids=attacker_move_ids,
        defender=FixedPokemonConfiguration(
            pokemon_id=461,
            form_id=None,
            level=50,
            stat_profile_id="max_atk_plus",
            ability_identifier="pressure",
            item_identifier="choice-band",
        ),
        defender_move_ids=defender_move_ids,
    )


def _configuration_reference(data: dict[str, object]) -> ConfigurationReference:
    """把 fixture 中的配置引用转换为显式 Python DTO。"""
    attacker_move_ids = data["attacker_move_ids"]
    defender_move_ids = data["defender_move_ids"]
    if not isinstance(attacker_move_ids, list) or not isinstance(
        defender_move_ids, list
    ):
        raise AssertionError("fixture configuration reference shape is invalid")
    return ConfigurationReference(
        configuration_id=str(data["configuration_id"]),
        attacker_move_ids=tuple(int(move_id) for move_id in attacker_move_ids),
        defender_move_ids=tuple(int(move_id) for move_id in defender_move_ids),
    )


def _graph_statistics(data: dict[str, object]) -> GraphStatisticsSummary:
    """把 fixture 中的轻量图规模转换为显式 Python DTO。"""
    return GraphStatisticsSummary(
        node_count=int(data["node_count"]),
        edge_count=int(data["edge_count"]),
        max_turn_number=int(data["max_turn_number"]),
    )


def _failed_detail(data: dict[str, object]) -> FailedConfigurationDetail:
    """把 fixture 中的失败详情转换为显式 Python DTO。"""
    configuration = data["configuration"]
    weight = data["configuration_weight"]
    graph_statistics = data["graph_statistics"]
    if not isinstance(configuration, dict) or not isinstance(weight, dict):
        raise AssertionError("fixture failed detail shape is invalid")
    if graph_statistics is not None and not isinstance(graph_statistics, dict):
        raise AssertionError("fixture failed graph statistics shape is invalid")
    return FailedConfigurationDetail(
        configuration=_configuration_reference(configuration),
        configuration_weight=ExactRatio(
            int(weight["numerator"]), int(weight["denominator"])
        ),
        reason_code=str(data["reason_code"]),
        message=str(data["message"]),
        graph_statistics=(
            None
            if graph_statistics is None
            else _graph_statistics(graph_statistics)
        ),
    )


def _truncated_detail(data: dict[str, object]) -> TruncatedConfigurationDetail:
    """把 fixture 中的截断详情转换为显式 Python DTO。"""
    configuration = data["configuration"]
    weight = data["configuration_weight"]
    reason_codes = data["reason_codes"]
    graph_statistics = data["graph_statistics"]
    if (
        not isinstance(configuration, dict)
        or not isinstance(weight, dict)
        or not isinstance(reason_codes, list)
        or not isinstance(graph_statistics, dict)
    ):
        raise AssertionError("fixture truncated detail shape is invalid")
    return TruncatedConfigurationDetail(
        configuration=_configuration_reference(configuration),
        configuration_weight=ExactRatio(
            int(weight["numerator"]), int(weight["denominator"])
        ),
        reason_codes=tuple(str(reason) for reason in reason_codes),
        graph_statistics=_graph_statistics(graph_statistics),
    )


def _selection(data: dict[str, object]) -> PokemonMovePoolSelection:
    """把共享 fixture 的单边固定配置和候选池转换为显式 Python DTO。"""
    fixed_data = data["fixed"]
    candidate_move_ids = data["candidate_move_ids"]
    if not isinstance(fixed_data, dict) or not isinstance(candidate_move_ids, list):
        raise AssertionError("fixture selection shape is invalid")
    return PokemonMovePoolSelection(
        fixed=_fixed_configuration(fixed_data),
        candidate_move_ids=tuple(int(move_id) for move_id in candidate_move_ids),
    )


def _fixed_configuration(data: dict[str, object]) -> FixedPokemonConfiguration:
    """把共享 fixture 的固定配置字段转换为显式 Python DTO。"""
    return FixedPokemonConfiguration(
        pokemon_id=int(data["pokemon_id"]),
        form_id=None if data["form_id"] is None else int(data["form_id"]),
        level=int(data["level"]),
        stat_profile_id=str(data["stat_profile_id"]),
        ability_identifier=str(data["ability_identifier"]),
        item_identifier=(
            None if data["item_identifier"] is None else str(data["item_identifier"])
        ),
    )
