"""配置预设统一 HTTP API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from pokeop.api.schemas.stat_configurations import (
    NatureResponse,
    SaveOrderRequest,
    SaveStatConfigurationRequest,
    SetHiddenRequest,
    StatConfigurationListResponse,
    StatConfigurationResponse,
    configuration_response,
    list_response,
)
from pokeop.application.use_cases.stat_configurations import (
    StatConfigurationError,
    StatConfigurationRepository,
    StatConfigurationUseCase,
)
from pokeop.domain.configuration_presets import StatConfigurationRole, TenantScope
from pokeop.persistence.stat_configurations import PostgresStatConfigurationRepository

ROUTE_PREFIX_OVERRIDE = "/v1/stat-configurations"
router = APIRouter()


def get_tenant_scope(x_pokeop_tenant: str | None = Header(default=None)) -> TenantScope:
    """解析当前请求租户。

    当前仓库没有认证或租户上下文，因此生产默认使用开发租户；测试和未来网关可通过
    服务端可信 header 覆盖。这里不接受 body/query 中的 tenant_id，避免前端直接越权。
    """
    tenant_id = (x_pokeop_tenant or "default-tenant").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant scope is empty")
    return TenantScope(tenant_id)


def get_repository() -> StatConfigurationRepository:
    """创建配置预设 repository 依赖。"""
    return PostgresStatConfigurationRepository()


def get_use_case(
    repository: StatConfigurationRepository = Depends(get_repository),
) -> StatConfigurationUseCase:
    """创建配置预设 application 用例。"""
    return StatConfigurationUseCase(repository)


@router.get("", response_model=StatConfigurationListResponse)
async def list_configurations(
    role: StatConfigurationRole = Query(description="当前页面侧：attacker 或 defender。"),
    pokemon_id: int = Query(gt=0, description="当前选中的 PokeAPI pokemon_id。"),
    include_hidden: bool = Query(default=False, description="是否包含隐藏项，管理弹窗使用 true。"),
    scope: TenantScope = Depends(get_tenant_scope),
    use_case: StatConfigurationUseCase = Depends(get_use_case),
) -> StatConfigurationListResponse:
    """按当前 Pokémon 与攻防位置读取可用配置。"""
    if role is StatConfigurationRole.BOTH:
        raise HTTPException(status_code=400, detail="role must be attacker or defender")
    try:
        return list_response(
            use_case.list_configurations(
                scope=scope,
                role=role,
                pokemon_id=pokemon_id,
                include_hidden=include_hidden,
            )
        )
    except StatConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/natures", response_model=list[NatureResponse])
async def list_natures(
    use_case: StatConfigurationUseCase = Depends(get_use_case),
) -> list[NatureResponse]:
    """返回合法宝可梦性格元数据。"""
    return [NatureResponse(**item) for item in use_case.list_natures()]


@router.post("", response_model=StatConfigurationResponse, status_code=201)
async def create_configuration(
    request: SaveStatConfigurationRequest,
    scope: TenantScope = Depends(get_tenant_scope),
    use_case: StatConfigurationUseCase = Depends(get_use_case),
) -> StatConfigurationResponse:
    """创建租户共享自定义配置。"""
    try:
        return configuration_response(
            use_case.create_custom(scope=scope, command=request.to_command())
        )
    except (StatConfigurationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{config_id}", response_model=StatConfigurationResponse)
async def update_configuration(
    config_id: str,
    request: SaveStatConfigurationRequest,
    scope: TenantScope = Depends(get_tenant_scope),
    use_case: StatConfigurationUseCase = Depends(get_use_case),
) -> StatConfigurationResponse:
    """完整更新租户自定义配置；内置配置不会进入该接口。"""
    try:
        return configuration_response(
            use_case.update_custom(
                scope=scope,
                config_id=config_id,
                command=request.to_command(),
            )
        )
    except (StatConfigurationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{config_id}", status_code=204, response_model=None)
async def delete_configuration(
    config_id: str,
    scope: TenantScope = Depends(get_tenant_scope),
    use_case: StatConfigurationUseCase = Depends(get_use_case),
) -> Response:
    """软删除租户自定义配置。"""
    try:
        use_case.delete_custom(scope=scope, config_id=config_id)
    except StatConfigurationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/hidden", status_code=204, response_model=None)
async def set_hidden(
    request: SetHiddenRequest,
    scope: TenantScope = Depends(get_tenant_scope),
    use_case: StatConfigurationUseCase = Depends(get_use_case),
) -> Response:
    """隐藏或恢复一条内置/自定义配置。"""
    try:
        use_case.set_hidden(
            scope=scope,
            role=request.role,
            reference=request.reference.to_application(),
            hidden=request.hidden,
        )
    except StatConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/order", status_code=204, response_model=None)
async def save_order(
    request: SaveOrderRequest,
    scope: TenantScope = Depends(get_tenant_scope),
    use_case: StatConfigurationUseCase = Depends(get_use_case),
) -> Response:
    """批量保存当前角色排序。"""
    try:
        use_case.save_order(
            scope=scope,
            role=request.role,
            ordered_references=tuple(item.to_application() for item in request.references),
        )
    except StatConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)


__all__ = ["get_repository", "get_tenant_scope", "get_use_case", "router"]
