from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from pokeop.api.schemas.calculator import (
    CalculateDamageRequest,
    CalculateDamageResponse,
    MoveSearchPageResponse,
    PokemonDetailResponse,
    PokemonSearchItem,
    StatPresetResponse,
    damage_response_from_result,
    move_search_page_from_result,
    pokemon_detail_from_profile,
    pokemon_search_item_from_result,
)
from pokeop.application.use_cases.calculate_catalog_damage import (
    ATTACKER_PRESETS,
    DEFAULT_RULESET_ID,
    DEFENDER_PRESETS,
    CalculateCatalogDamageCommand,
    CalculateCatalogDamageUseCase,
    CalculateCatalogPokemonCommand,
    CalculatorCatalogRepository,
    CalculatorInputError,
)
from pokeop.application.use_cases.list_calculable_moves import (
    CalculatorMoveCatalogRepository,
    CalculatorMoveFilterCategory,
    CalculatorMoveQueryError,
    ListCalculatorMovesQuery,
    ListCalculatorMovesUseCase,
)
from pokeop.persistence.calculator import MaterializedViewCalculatorRepository

router = APIRouter()


def get_calculator_repository() -> MaterializedViewCalculatorRepository:
    """创建 calculator repository 依赖。

    Returns:
        基于 PostgreSQL 物化视图的 repository 实例；测试可通过 FastAPI dependency
        override 替换为 fake repository。
    """
    return MaterializedViewCalculatorRepository()


def get_calculator_use_case(
    repository: CalculatorCatalogRepository = Depends(get_calculator_repository),
) -> CalculateCatalogDamageUseCase:
    """创建数据库驱动伤害计算 use case。"""
    return CalculateCatalogDamageUseCase(repository)


def get_calculator_move_use_case(
    repository: CalculatorMoveCatalogRepository = Depends(get_calculator_repository),
) -> ListCalculatorMovesUseCase:
    """创建招式复合过滤与分页查询 use case。"""
    return ListCalculatorMovesUseCase(repository)


@router.get("/pokemon", response_model=list[PokemonSearchItem])
async def search_pokemon(
    query: str = Query(default="", description="中文名或 identifier 搜索词。"),
    ruleset_id: str = Query(default=DEFAULT_RULESET_ID, description="当前规则集。"),
    limit: int = Query(default=20, ge=1, le=50, description="最大返回数量。"),
    repository: CalculatorCatalogRepository = Depends(get_calculator_repository),
) -> list[PokemonSearchItem]:
    """搜索当前规则集下可用于 calculator 的宝可梦。"""
    results = repository.search_pokemon(ruleset_id=ruleset_id, query=query, limit=limit)
    return [pokemon_search_item_from_result(item, ruleset_id=ruleset_id) for item in results]


@router.get("/pokemon/{pokemon_id}", response_model=PokemonDetailResponse)
async def get_pokemon_detail(
    pokemon_id: int,
    ruleset_id: str = Query(default=DEFAULT_RULESET_ID, description="当前规则集。"),
    repository: CalculatorCatalogRepository = Depends(get_calculator_repository),
) -> PokemonDetailResponse:
    """读取一只宝可梦在当前规则集下的页面摘要和基础战斗资料。"""
    profile = repository.get_pokemon_profile(ruleset_id=ruleset_id, pokemon_id=pokemon_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="pokemon not found in ruleset")
    return pokemon_detail_from_profile(profile, ruleset_id=ruleset_id)


@router.get("/pokemon/{pokemon_id}/moves", response_model=MoveSearchPageResponse)
async def list_pokemon_moves(
    pokemon_id: int,
    ruleset_id: str = Query(default=DEFAULT_RULESET_ID, description="当前规则集。"),
    query: str = Query(default="", description="中文名或 identifier 搜索词。"),
    category: CalculatorMoveFilterCategory = Query(
        default=CalculatorMoveFilterCategory.ALL,
        description="全部、物理或特殊招式。",
    ),
    type_identifiers: list[str] | None = Query(
        default=None,
        alias="type",
        description="可重复传入的属性 identifier；多个值之间使用 OR。",
    ),
    limit: int = Query(default=10, ge=1, le=50, description="单页最大返回数量。"),
    offset: int = Query(default=0, ge=0, description="稳定排序结果的起始偏移。"),
    use_case: ListCalculatorMovesUseCase = Depends(get_calculator_move_use_case),
) -> MoveSearchPageResponse:
    """按文本、类别和属性复合筛选一只 Pokémon 的可计算招式。"""
    try:
        result = use_case.execute(
            ListCalculatorMovesQuery(
                ruleset_id=ruleset_id,
                pokemon_id=pokemon_id,
                query=query,
                category=category,
                type_identifiers=tuple(type_identifiers or ()),
                limit=limit,
                offset=offset,
            )
        )
    except CalculatorMoveQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return move_search_page_from_result(result)


@router.get("/presets", response_model=dict[str, list[StatPresetResponse]])
async def list_stat_presets() -> dict[str, list[StatPresetResponse]]:
    """返回前端配置模板文案，保证 UI 展示与 application 解释同源。"""
    return {
        "attacker": [StatPresetResponse(**preset.__dict__) for preset in ATTACKER_PRESETS.values()],
        "defender": [StatPresetResponse(**preset.__dict__) for preset in DEFENDER_PRESETS.values()],
    }


@router.post("/damage", response_model=CalculateDamageResponse)
async def calculate_damage(
    request: CalculateDamageRequest,
    use_case: CalculateCatalogDamageUseCase = Depends(get_calculator_use_case),
) -> CalculateDamageResponse:
    """执行基础伤害计算，不信任前端传入任何派生战斗资料。"""
    try:
        result = use_case.execute(
            CalculateCatalogDamageCommand(
                ruleset_id=request.ruleset_id,
                attacker=CalculateCatalogPokemonCommand(
                    pokemon_id=request.attacker.pokemon_id,
                    level=request.attacker.level,
                    stat_preset=request.attacker.stat_preset,
                ),
                defender=CalculateCatalogPokemonCommand(
                    pokemon_id=request.defender.pokemon_id,
                    level=request.defender.level,
                    stat_preset=request.defender.stat_preset,
                ),
                move_id=request.move_id,
            )
        )
    except CalculatorInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return damage_response_from_result(result)


__all__ = [
    "get_calculator_move_use_case",
    "get_calculator_repository",
    "get_calculator_use_case",
    "router",
]
