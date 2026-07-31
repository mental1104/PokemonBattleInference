from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException

from pokeop.api.routers.calculator import (
    get_calculator_ability_repository,
    get_calculator_repository,
)
from pokeop.api.schemas.configuration_solver import ConfigurationGoalRequest
from pokeop.api.schemas.configuration_solver_with_speed import (
    ConfigurationSpeedGoalRequest,
    SearchConfigurationSpreadsWithSpeedRequest,
    SolveConfigurationWithSpeedRequest,
    SolveConfigurationWithSpeedResponse,
    search_configuration_spreads_with_speed_response_from_result,
    solve_configuration_with_speed_response_from_result,
)
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculatorAbilityRepository,
)
from pokeop.application.use_cases.configuration_speed_goals import (
    ConfigurationSpeedGoalCommand,
)
from pokeop.application.use_cases.search_configuration_spreads_with_speed import (
    SearchPokemonStatSpreadsWithSpeedCommand,
    SearchPokemonStatSpreadsWithSpeedUseCase,
)
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalCommand,
    ConfigurationSolverInputError,
)
from pokeop.application.use_cases.solve_configuration_with_speed import (
    SolvePokemonConfigurationWithSpeedCommand,
    SolvePokemonConfigurationWithSpeedUseCase,
)
from pokeop.persistence.calculator import MaterializedViewCalculatorRepository

router = APIRouter()


def get_configuration_solver_use_case(
    repository: MaterializedViewCalculatorRepository = Depends(get_calculator_repository),
    ability_repository: CalculatorAbilityRepository = Depends(
        get_calculator_ability_repository
    ),
) -> SolvePokemonConfigurationWithSpeedUseCase:
    """创建支持伤害目标与严格速度目标的模板求解 use case。

    Args:
        repository: 读取规则集、Pokémon、招式和道具的物化视图 repository。
        ability_repository: 读取 Pokémon 合法特性的 version-aware repository。

    Returns:
        可以从用户选定配置模板中搜索双类目标可达候选的 application use case。
    """
    return SolvePokemonConfigurationWithSpeedUseCase(repository, ability_repository)


def get_configuration_spread_search_use_case(
    repository: MaterializedViewCalculatorRepository = Depends(get_calculator_repository),
    ability_repository: CalculatorAbilityRepository = Depends(
        get_calculator_ability_repository
    ),
) -> SearchPokemonStatSpreadsWithSpeedUseCase:
    """创建支持严格速度目标的 EV、IV 与性格反推 use case。

    Args:
        repository: 读取规则集、Pokémon、招式和道具的物化视图 repository。
        ability_repository: 读取 Pokémon 合法特性的 version-aware repository。

    Returns:
        根据伤害和速度目标搜索合法属性分配的 application use case。
    """
    return SearchPokemonStatSpreadsWithSpeedUseCase(repository, ability_repository)


def _goal_commands(
    goals: Sequence[ConfigurationGoalRequest],
) -> tuple[ConfigurationGoalCommand, ...]:
    """把 HTTP 伤害目标列表转换成 application 不可变命令。

    Args:
        goals: Pydantic 已完成基础字段校验的攻防目标输入序列。

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


def _speed_goal_commands(
    goals: Sequence[ConfigurationSpeedGoalRequest],
) -> tuple[ConfigurationSpeedGoalCommand, ...]:
    """把 HTTP 速度目标列表转换成 application 不可变命令。

    Args:
        goals: 已完成字段校验的目标 Pokémon 与配置序列。

    Returns:
        按请求顺序保留稳定 ID、目标 Pokémon 和配置快照的命令元组。
    """
    return tuple(
        ConfigurationSpeedGoalCommand(
            goal_id=goal.goal_id,
            target_pokemon_id=goal.target_pokemon_id,
            target_stat_preset=goal.target_stat_preset,
        )
        for goal in goals
    )


@router.post("/solve", response_model=SolveConfigurationWithSpeedResponse)
async def solve_configuration(
    request: SolveConfigurationWithSpeedRequest,
    use_case: SolvePokemonConfigurationWithSpeedUseCase = Depends(
        get_configuration_solver_use_case
    ),
) -> SolveConfigurationWithSpeedResponse:
    """根据伤害与严格速度目标从已有配置模板中搜索可达候选。

    Args:
        request: 固定待配置 Pokémon、机制、双类目标和允许模板的 HTTP 请求。
        use_case: FastAPI 依赖注入得到的速度感知模板求解器。

    Returns:
        可达候选或第一组伤害、速度不可达证据。

    Raises:
        HTTPException: application 判断请求非法或超出当前能力边界时返回 400。
    """
    try:
        result = use_case.execute(
            SolvePokemonConfigurationWithSpeedCommand(
                ruleset_id=request.ruleset_id,
                subject_pokemon_id=request.subject_pokemon_id,
                subject_ability_identifier=request.subject_ability_identifier,
                subject_item_identifier=request.subject_item_identifier,
                level=request.level,
                goals=_goal_commands(request.goals),
                # 直接调用 router 的旧测试会传入原 SolveConfigurationRequest；缺少扩展字段时
                # 按空速度目标处理，保持原入口兼容。
                speed_goals=_speed_goal_commands(
                    getattr(request, "speed_goals", ())
                ),
                allowed_stat_presets=tuple(request.allowed_stat_presets),
                max_candidates=request.max_candidates,
            )
        )
    except ConfigurationSolverInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return solve_configuration_with_speed_response_from_result(result)


@router.post("/search-spreads", response_model=SolveConfigurationWithSpeedResponse)
async def search_configuration_spreads(
    request: SearchConfigurationSpreadsWithSpeedRequest,
    use_case: SearchPokemonStatSpreadsWithSpeedUseCase = Depends(
        get_configuration_spread_search_use_case
    ),
) -> SolveConfigurationWithSpeedResponse:
    """根据伤害与严格速度目标反推待配置 Pokémon 的 EV、IV 与性格。

    Args:
        request: 固定 Pokémon、特性、道具、等级和双类目标的 HTTP 请求。
        use_case: FastAPI 依赖注入得到的速度感知属性反推 use case。

    Returns:
        最多十条带代表分配、等价性格、速度线和单字段安全区间的候选。

    Raises:
        HTTPException: application 判断请求非法、配置不合法或目标超出边界时返回 400。
    """
    try:
        result = use_case.execute(
            SearchPokemonStatSpreadsWithSpeedCommand(
                ruleset_id=request.ruleset_id,
                subject_pokemon_id=request.subject_pokemon_id,
                subject_ability_identifier=request.subject_ability_identifier,
                subject_item_identifier=request.subject_item_identifier,
                level=request.level,
                goals=_goal_commands(request.goals),
                speed_goals=_speed_goal_commands(
                    getattr(request, "speed_goals", ())
                ),
                max_candidates=request.max_candidates,
            )
        )
    except ConfigurationSolverInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return search_configuration_spreads_with_speed_response_from_result(result)


__all__ = [
    "get_configuration_solver_use_case",
    "get_configuration_spread_search_use_case",
    "router",
    "search_configuration_spreads",
    "solve_configuration",
]
