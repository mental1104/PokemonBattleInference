from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from pokeop.api.routers.calculator import (
    get_calculator_ability_repository,
    get_calculator_repository,
)
from pokeop.api.schemas.configuration_solver import (
    SolveConfigurationRequest,
    SolveConfigurationResponse,
    solve_configuration_response_from_result,
)
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculatorAbilityRepository,
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
    ability_repository: CalculatorAbilityRepository = Depends(
        get_calculator_ability_repository
    ),
) -> SolvePokemonConfigurationUseCase:
    """创建同时读取 catalog 和合法特性的反向配置求解 use case。"""
    return SolvePokemonConfigurationUseCase(repository, ability_repository)


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
                subject_ability_identifier=request.subject_ability_identifier,
                subject_item_identifier=request.subject_item_identifier,
                level=request.level,
                goals=tuple(
                    ConfigurationGoalCommand(
                        goal_id=goal.goal_id,
                        kind=goal.kind,
                        target_pokemon_id=goal.target_pokemon_id,
                        move_id=goal.move_id,
                        required_turns=goal.required_turns,
                        target_ability_identifier=goal.target_ability_identifier,
                        target_item_identifier=goal.target_item_identifier,
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
