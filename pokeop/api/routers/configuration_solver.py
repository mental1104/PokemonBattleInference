from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from pokeop.api.routers.calculator import get_calculator_repository
from pokeop.api.schemas.configuration_solver import (
    SolveConfigurationRequest,
    SolveConfigurationResponse,
    solve_configuration_response_from_result,
)
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalCommand,
    ConfigurationSolverInputError,
    SolvePokemonConfigurationCommand,
    SolvePokemonConfigurationUseCase,
)
from pokeop.persistence.calculator import MaterializedViewCalculatorRepository

router = APIRouter()


def get_configuration_solver_use_case(
    repository: MaterializedViewCalculatorRepository = Depends(get_calculator_repository),
) -> SolvePokemonConfigurationUseCase:
    """创建反向配置求解 use case。

    Args:
        repository: 复用 calculator 的物化视图读取 repository。

    Returns:
        已绑定 repository 的 application use case。
    """
    return SolvePokemonConfigurationUseCase(repository)


@router.post("/solve", response_model=SolveConfigurationResponse)
async def solve_configuration(
    request: SolveConfigurationRequest,
    use_case: SolvePokemonConfigurationUseCase = Depends(get_configuration_solver_use_case),
) -> SolveConfigurationResponse:
    """根据多组攻防目标反向搜索同一只 Pokémon 的可用配置。"""
    try:
        result = use_case.execute(
            SolvePokemonConfigurationCommand(
                ruleset_id=request.ruleset_id,
                subject_pokemon_id=request.subject_pokemon_id,
                level=request.level,
                goals=tuple(
                    ConfigurationGoalCommand(
                        goal_id=goal.goal_id,
                        kind=goal.kind,
                        target_pokemon_id=goal.target_pokemon_id,
                        move_id=goal.move_id,
                        required_turns=goal.required_turns,
                        target_stat_preset=goal.target_stat_preset,
                        damage_roll_policy=goal.damage_roll_policy,
                    )
                    for goal in request.goals
                ),
                allowed_stat_presets=tuple(request.allowed_stat_presets),
                max_candidates=request.max_candidates,
            )
        )
    except ConfigurationSolverInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return solve_configuration_response_from_result(result)


__all__ = [
    "get_configuration_solver_use_case",
    "router",
    "solve_configuration",
]
