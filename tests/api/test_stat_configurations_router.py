"""配置预设 router 测试。"""

from __future__ import annotations

import pytest

from pokeop.api.routers import stat_configurations
from pokeop.api.schemas.stat_configurations import SaveStatConfigurationRequest, StatSpreadSchema
from pokeop.application.use_cases.stat_configurations import StatConfigurationUseCase
from pokeop.domain.configuration_presets import (
    PokemonBindingKind,
    StatConfigurationRole,
    TenantScope,
)
from tests.application.use_cases.test_stat_configurations import MemoryStatConfigurationRepository


@pytest.mark.anyio
async def test_router_creates_and_lists_tenant_scoped_configuration() -> None:
    """
    router 只负责 HTTP schema 转换、tenant scope 解析和业务错误映射。该测试直接注入
    application 用例，创建 tenant-a 的自定义配置后，用 tenant-b 查询同一 Pokémon，
    断言不会跨租户泄漏自定义配置，同时保留内置配置可见。
    """
    repository = MemoryStatConfigurationRepository()
    use_case = StatConfigurationUseCase(repository)

    created = await stat_configurations.create_configuration(
        _save_request(),
        scope=TenantScope("tenant-a"),
        use_case=use_case,
    )
    tenant_a = await stat_configurations.list_configurations(
        role=StatConfigurationRole.DEFENDER,
        pokemon_id=212,
        include_hidden=True,
        scope=TenantScope("tenant-a"),
        use_case=use_case,
    )
    tenant_b = await stat_configurations.list_configurations(
        role=StatConfigurationRole.DEFENDER,
        pokemon_id=212,
        include_hidden=True,
        scope=TenantScope("tenant-b"),
        use_case=use_case,
    )

    assert created.source == "custom"
    assert any(item.id == created.id for item in tenant_a.items)
    assert not any(item.id == created.id for item in tenant_b.items)
    assert any(item.source == "builtin" for item in tenant_b.items)


def test_tenant_scope_uses_default_without_client_tenant_id() -> None:
    """
    当前仓库没有认证系统，router 采用服务端默认租户作为最小抽象；这条测试锁定
    未来接入认证前不会从 body/query 信任客户端 tenant_id。
    """
    assert stat_configurations.get_tenant_scope(None).tenant_id == "default-tenant"
    assert stat_configurations.get_tenant_scope("tenant-from-gateway").tenant_id == "tenant-from-gateway"


def _save_request() -> SaveStatConfigurationRequest:
    """创建一条合法自定义耐久配置请求。"""
    return SaveStatConfigurationRequest(
        name="Scizor Bulk",
        nature_id="bold",
        evs=StatSpreadSchema(
            hp=252,
            attack=0,
            defense=252,
            special_attack=0,
            special_defense=0,
            speed=0,
        ),
        ivs=StatSpreadSchema(
            hp=31,
            attack=31,
            defense=31,
            special_attack=31,
            special_defense=31,
            speed=31,
        ),
        role=StatConfigurationRole.DEFENDER,
        binding_kind=PokemonBindingKind.POKEMON,
        pokemon_id=212,
    )
