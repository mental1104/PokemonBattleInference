"""暴露技能组合预览和单个固定配置精确概率推演。"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException

from pokeop.api.schemas.fixed_battle import (
    FixedBattleSummaryRequest,
    MoveSetCombinationsRequest,
    MoveSetCombinationsResponse,
    fixed_battle_summary_response,
    move_set_combinations_response,
)
from pokeop.api.schemas.inference import BattleInferenceSummaryResponse
from pokeop.application.battle_candidate_pool.admission import (
    StrictMechanismAdmissionRejected,
    ValidateFixedMechanismSelectionUseCase,
)
from pokeop.application.battle_candidate_pool.listing import (
    BattleCandidatePoolNotFound,
    ListBattleCandidatePoolUseCase,
)
from pokeop.application.battle_inference_effect_factory import (
    TransparentPokemonChampionEffectFactory,
)
from pokeop.application.composition.battle_inference_repository import (
    FactoryReconciledBattleInferenceRepository,
)
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.use_cases.admitted_fixed_battle import (
    RunAdmittedFixedBattleSummaryUseCase,
)
from pokeop.application.use_cases.fixed_battle_workflow import (
    EnumerateMoveSetCombinationsCommand,
    EnumerateMoveSetCombinationsUseCase,
    InferFixedBattleSummaryUseCase,
    build_fixed_inference_command,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
    BattleInferenceExecutionError,
    InferOneOnOneBattleUseCase,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.persistence.battle_inference.repository import (
    MaterializedViewBattleInferenceRepository,
)


ROUTE_PREFIX_OVERRIDE = "/v1/inference"
router = APIRouter()


def inference_use_case() -> InferOneOnOneBattleUseCase:
    """创建候选准入和固定摘要共享的 repository/effect composition。

    Returns:
        使用 version-aware 物化视图 repository 和透明中性 effect factory 的用例。
    """
    effect_factory = TransparentPokemonChampionEffectFactory()
    repository = FactoryReconciledBattleInferenceRepository(
        repository=MaterializedViewBattleInferenceRepository(),
        effect_factory=effect_factory,
    )
    return InferOneOnOneBattleUseCase(
        repository=repository,
        effect_factory=effect_factory,
    )


def combination_use_case() -> EnumerateMoveSetCombinationsUseCase:
    """创建只枚举技能组合的 application 查询用例。

    Returns:
        复用正式候选池 repository 和 effect factory 的无状态组合用例。
    """
    inference = inference_use_case()
    return EnumerateMoveSetCombinationsUseCase(
        ListBattleCandidatePoolUseCase(
            repository=inference.repository,
            effect_factory=inference.effect_factory,
        )
    )


def summary_use_case() -> RunAdmittedFixedBattleSummaryUseCase:
    """创建包含严格准入和轻量精确求解的 application 用例。

    Returns:
        API 无需理解候选池机制判断的固定配置业务编排对象。
    """
    inference = inference_use_case()
    return RunAdmittedFixedBattleSummaryUseCase(
        admission_use_case=ValidateFixedMechanismSelectionUseCase(
            inference.repository,
            inference.effect_factory,
        ),
        summary_use_case=InferFixedBattleSummaryUseCase(inference),
    )


CombinationUseCaseDependency = Annotated[
    EnumerateMoveSetCombinationsUseCase,
    Depends(combination_use_case),
]
SummaryUseCaseDependency = Annotated[
    RunAdmittedFixedBattleSummaryUseCase,
    Depends(summary_use_case),
]


def _rules(
    *,
    ruleset_id: str,
    version_group_id: int,
    level: int,
    max_turns: int,
) -> BattleInferenceRules:
    """构造双方共享的首版 1v1 规则对象。

    Args:
        ruleset_id: 当前固定推演规则集稳定标识。
        version_group_id: 招式学习和历史机制使用的 PokeAPI version group。
        level: 双方共享的战斗等级。
        max_turns: 本次固定配置允许完整执行的最大回合号。

    Returns:
        禁止换人和特殊形态变化的正式领域规则对象。
    """
    return BattleInferenceRules(
        ruleset_id=ruleset_id,
        version_group_id=version_group_id,
        level=level,
        max_turns=max_turns,
    )


def _policy(value: str) -> BattleActionPolicyKind:
    """把 HTTP 稳定字符串映射为 application 行动策略枚举。

    Args:
        value: ``uniform-random`` 或仅供开发调试的 ``first-legal``。

    Returns:
        固定推演命令使用的显式策略枚举。

    Raises:
        ValueError: value 不是当前固定推演支持的策略时抛出。
    """
    if value == "uniform-random":
        return BattleActionPolicyKind.UNIFORM_RANDOM
    if value == "first-legal":
        return BattleActionPolicyKind.FIRST_LEGAL
    raise ValueError(f"unsupported battle action policy: {value!r}")


def _raise_http_error(error: Exception) -> NoReturn:
    """把候选池、准入和固定求解异常转换为稳定 HTTP 语义。

    Args:
        error: application 或 persistence 边界抛出的稳定异常。

    Raises:
        HTTPException: 候选不存在返回 404；输入、准入和资源截断返回 422。
    """
    if isinstance(error, BattleCandidatePoolNotFound):
        status_code = 404
        code = "fixed_battle_candidate_pool_not_found"
    elif isinstance(error, StrictMechanismAdmissionRejected):
        status_code = 422
        code = "fixed_battle_mechanism_rejected"
    elif isinstance(error, BattleInferenceExecutionError):
        status_code = 422
        code = "fixed_battle_not_completely_solved"
    else:
        status_code = 422
        code = "fixed_battle_invalid_request"
    detail: dict[str, object] = {"code": code, "message": str(error)}
    if isinstance(error, StrictMechanismAdmissionRejected):
        detail["failures"] = [
            {
                "requested_identifier": failure.requested_identifier,
                "status": failure.status.value,
                "reason": failure.reason,
                "missing_mechanism_identifiers": list(
                    failure.missing_mechanism_identifiers
                ),
            }
            for failure in error.failures
        ]
    raise HTTPException(status_code=status_code, detail=detail) from error


@router.post(
    "/move-set-combinations",
    response_model=MoveSetCombinationsResponse,
    summary="枚举双方候选池产生的规范化技能组",
)
def enumerate_move_set_combinations(
    request: MoveSetCombinationsRequest,
    use_case: CombinationUseCaseDependency,
) -> MoveSetCombinationsResponse:
    """严格校验候选后返回左右技能组，不启动 worker 或状态图。

    Args:
        request: 双方固定配置、候选技能池和精确规则轴。
        use_case: 可被测试 dependency override 替换的组合枚举用例。

    Returns:
        每侧最多 210 个技能组以及理论配置对数量。

    Raises:
        HTTPException: 候选池不存在或输入没有通过严格组合校验时抛出。
    """
    try:
        if request.attacker.level != request.defender.level:
            raise ValueError("both sides must use the same level in v1")
        rules = _rules(
            ruleset_id=request.ruleset_id,
            version_group_id=request.version_group_id,
            level=request.attacker.level,
            max_turns=20,
        )
        result = use_case.execute(
            EnumerateMoveSetCombinationsCommand(
                rules=rules,
                calculation_revision=request.calculation_revision,
                attacker=request.attacker.to_application(),
                attacker_candidate_move_ids=tuple(
                    request.attacker.candidate_move_ids
                ),
                defender=request.defender.to_application(),
                defender_candidate_move_ids=tuple(
                    request.defender.candidate_move_ids
                ),
            )
        )
        return move_set_combinations_response(result)
    except (BattleCandidatePoolNotFound, ValueError) as error:
        _raise_http_error(error)


@router.post(
    "/fixed-one-on-one",
    response_model=BattleInferenceSummaryResponse,
    summary="精确求解一个双方固定配置快照",
)
def infer_fixed_one_on_one(
    request: FixedBattleSummaryRequest,
    use_case: SummaryUseCaseDependency,
) -> BattleInferenceSummaryResponse:
    """对用户选中的一个技能组配置计算精确胜、负、平和期望回合。

    Args:
        request: 双方固定配置、已选技能组、行动策略和单配置图预算。
        use_case: 负责严格准入和轻量精确求解的 application 用例。

    Returns:
        明确绑定行动策略假设的精确概率摘要；不包含 graph ID 和代表路径。

    Raises:
        HTTPException: 机制未通过准入、图被截断或输入不符合首版边界时抛出。
    """
    try:
        if request.attacker.level != request.defender.level:
            raise ValueError("both sides must use the same level in v1")
        rules = _rules(
            ruleset_id=request.ruleset_id,
            version_group_id=request.version_group_id,
            level=request.attacker.level,
            max_turns=request.limits.max_turns,
        )
        command = build_fixed_inference_command(
            rules=rules,
            attacker=request.attacker.to_application(),
            attacker_move_ids=tuple(request.attacker.move_ids),
            defender=request.defender.to_application(),
            defender_move_ids=tuple(request.defender.move_ids),
            attacker_policy=_policy(request.attacker_policy),
            defender_policy=_policy(request.defender_policy),
            graph_limits=StateGraphLimits(
                max_nodes=request.limits.max_nodes,
                max_edges=request.limits.max_edges,
                max_turns=request.limits.max_turns,
            ),
        )
        return fixed_battle_summary_response(use_case.execute(command))
    except (
        BattleCandidatePoolNotFound,
        StrictMechanismAdmissionRejected,
        BattleInferenceExecutionError,
        ValueError,
    ) as error:
        _raise_http_error(error)


__all__ = ["router"]
