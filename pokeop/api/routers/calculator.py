from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from pokeop.api.schemas.calculator import (
    CalculateDamageRequest,
    CalculateDamageResponse,
    MoveSearchItem,
    PokemonDetailResponse,
    PokemonSearchItem,
    StatPresetResponse,
    damage_response_from_result,
    move_search_item_from_result,
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
from pokeop.persistence.calculator import MaterializedViewCalculatorRepository

router = APIRouter()


def get_calculator_repository() -> CalculatorCatalogRepository:
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


@router.get("/pokemon", response_model=list[PokemonSearchItem])
async def search_pokemon(
    query: str = Query(default="", description="中文名或 identifier 搜索词。"),
    ruleset_id: str = Query(default=DEFAULT_RULESET_ID, description="当前规则集。"),
    limit: int = Query(default=20, ge=1, le=50, description="最大返回数量。"),
    repository: CalculatorCatalogRepository = Depends(get_calculator_repository),
) -> list[PokemonSearchItem]:
    """搜索当前规则集下可用于 calculator 的宝可梦。"""
    results = repository.search_pokemon(ruleset_id=ruleset_id, query=query, limit=limit)
    return [pokemon_search_item_from_result(item) for item in results]


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
    return pokemon_detail_from_profile(profile)


@router.get("/pokemon/{pokemon_id}/moves", response_model=list[MoveSearchItem])
async def list_pokemon_moves(
    pokemon_id: int,
    ruleset_id: str = Query(default=DEFAULT_RULESET_ID, description="当前规则集。"),
    query: str = Query(default="", description="中文名或 identifier 搜索词。"),
    limit: int = Query(default=50, ge=1, le=100, description="最大返回数量。"),
    repository: CalculatorCatalogRepository = Depends(get_calculator_repository),
) -> list[MoveSearchItem]:
    """列出一只宝可梦当前可学且基础模式可计算的招式。"""
    results = repository.list_calculable_moves(
        ruleset_id=ruleset_id,
        pokemon_id=pokemon_id,
        query=query,
        limit=limit,
    )
    return [move_search_item_from_result(item) for item in results]


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
    "get_calculator_repository",
    "get_calculator_use_case",
    "router",
]
