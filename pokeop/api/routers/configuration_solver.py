from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException

from pokeop.api.routers.calculator import (
    get_calculator_ability_repository,
    get_calculator_repository,
)
from pokeop.api.schemas.configuration_solver import (
    ConfigurationGoalRequest,
    SearchConfigurationSpreadsRequest,
    SolveConfigurationRequest,
    SolveConfigurationResponse,
    search_configuration_spreads_response_from_result,
    solve_configuration_response_from_result,
)
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculatorAbilityRepository,
)
from pokeop.application.use_cases.search_configuration_spreads import (
    SearchPokemonStatSpreadsCommand,
    SearchPokemonStatSpreadsUseCase,
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
    """创建同时读取 catalog 和合法特性的模板求解 use case。

    Args:
        repository: 读取规则集、Pokémon、招式和道具的物化视图 repository。
        ability_repository: 读取 Pokémon 合法特性的 version-aware repository。

    Returns:
        可以从用户选定配置模板中搜索可达候选的 application use case。
    """
    return SolvePokemonConfigurationUseCase(repository, ability_repository)


def get_configuration_spread_search_use_case(
    repository: MaterializedViewCalculatorRepository = Depends(get_calculator_repository),
    ability_repository: CalculatorAbilityRepository = Depends(
        get_calculator_ability_repository
    ),
) -> SearchPokemonStatSpreadsUseCase:
    """创建 EV、IV 与性格反推 use case。

    Args:
        repository: 读取规则集、Pokémon、招式和道具的物化视图 repository。
        ability_repository: 读取 Pokémon 合法特性的 version-aware repository。

    Returns:
        根据多目标搜索合法属性分配的 application use case。
    """
    return SearchPokemonStatSpreadsUseCase(repository, ability_repository)


def _goal_commands(
    goals: Sequence[ConfigurationGoalRequest],
) -> tuple[ConfigurationGoalCommand, ...]:
    """把 HTTP 目标列表转换成 application 不可变命令。

    Args:
        goals: Pydantic 已完成基础字段校验的目标输入序列。

    Returns:
        保留目标 ID、双方机制、对手配置和随机伤害档的不可变命令元组。
    """
    return tuple(
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
        for goal in goals
    )


@router.post("/solve", response_model=SolveConfigurationResponse)
async def solve_configuration(
    request: SolveConfigurationRequest,
    use_case: SolvePokemonConfigurationUseCase = Depends(get_configuration_solver_use_case),
) -> SolveConfigurationResponse:
    """根据多组攻防目标从已有配置模板中搜索可达候选。

    Args:
        request: 固定待配置 Pokémon、机制、目标和允许模板的 HTTP 请求。
        use_case: FastAPI 依赖注入得到的 application 模板求解器。

    Returns:
        可达候选或第一组不可达证据。

    Raises:
        HTTPException: application 判断请求非法或超出当前能力边界时返回 400。
    """
    try:
        result = use_case.execute(
            SolvePokemonConfigurationCommand(
                ruleset_id=request.ruleset_id,
                subject_pokemon_id=request.subject_pokemon_id,
                subject_ability_identifier=request.subject_ability_identifier,
                subject_item_identifier=request.subject_item_identifier,
                level=request.level,
                goals=_goal_commands(request.goals),
                allowed_stat_presets=tuple(request.allowed_stat_presets),
                max_candidates=request.max_candidates,
            )
        )
    except ConfigurationSolverInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return solve_configuration_response_from_result(result)


@router.post("/search-spreads", response_model=SolveConfigurationResponse)
async def search_configuration_spreads(
    request: SearchConfigurationSpreadsRequest,
    use_case: SearchPokemonStatSpreadsUseCase = Depends(
        get_configuration_spread_search_use_case
    ),
) -> SolveConfigurationResponse:
    """根据多组攻防目标反推待配置 Pokémon 的 EV、IV 与性格。

    Args:
        request: 固定 Pokémon、特性、道具、等级和目标的 HTTP 请求。
        use_case: FastAPI 依赖注入得到的属性反推 application use case。

    Returns:
        最多十条带代表分配、等价性格和单字段安全区间的候选。

    Raises:
        HTTPException: application 判断请求非法、招式不合法或目标超出边界时返回 400。
    """
    try:
        result = use_case.execute(
            SearchPokemonStatSpreadsCommand(
                ruleset_id=request.ruleset_id,
                subject_pokemon_id=request.subject_pokemon_id,
                subject_ability_identifier=request.subject_ability_identifier,
                subject_item_identifier=request.subject_item_identifier,
                level=request.level,
                goals=_goal_commands(request.goals),
                max_candidates=request.max_candidates,
            )
        )
    except ConfigurationSolverInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return search_configuration_spreads_response_from_result(result)


__all__ = [
    "get_configuration_solver_use_case",
    "get_configuration_spread_search_use_case",
    "router",
    "search_configuration_spreads",
    "solve_configuration",
]
