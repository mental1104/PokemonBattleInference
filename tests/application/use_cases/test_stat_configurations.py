"""配置预设 application 用例测试。"""

from __future__ import annotations

from datetime import datetime, timezone

from pokeop.application.use_cases.stat_configurations import (
    SaveStatConfigurationCommand,
    StatConfigurationPreferenceRecord,
    StatConfigurationRecord,
    StatConfigurationReference,
    StatConfigurationUseCase,
)
from pokeop.domain.configuration_presets import (
    PokemonBindingKind,
    StatConfigurationRole,
    StatConfigurationSource,
    StatSpread,
    TenantScope,
)


class MemoryStatConfigurationRepository:
    """用内存结构模拟租户隔离的配置 repository。"""

    def __init__(self) -> None:
        """初始化空配置和偏好集合。"""
        self.records: dict[str, StatConfigurationRecord] = {}
        self.preferences: dict[tuple[str, str, str, str], StatConfigurationPreferenceRecord] = {}
        self.next_id = 1

    def list_custom(self, scope: TenantScope) -> tuple[StatConfigurationRecord, ...]:
        """按 tenant_id 过滤自定义配置。"""
        return tuple(record for record in self.records.values() if record.tenant_id == scope.tenant_id)

    def get_custom(self, scope: TenantScope, config_id: str) -> StatConfigurationRecord | None:
        """按 tenant_id 和 ID 读取配置。"""
        record = self.records.get(config_id)
        if record is None or record.tenant_id != scope.tenant_id:
            return None
        return record

    def create_custom(self, scope: TenantScope, command: SaveStatConfigurationCommand) -> StatConfigurationRecord:
        """创建一条内存配置。"""
        record = _record(str(self.next_id), scope.tenant_id, command)
        self.next_id += 1
        self.records[record.id] = record
        return record

    def update_custom(
        self,
        scope: TenantScope,
        config_id: str,
        command: SaveStatConfigurationCommand,
    ) -> StatConfigurationRecord:
        """更新一条内存配置。"""
        if self.get_custom(scope, config_id) is None:
            raise ValueError("missing")
        record = _record(config_id, scope.tenant_id, command)
        self.records[config_id] = record
        return record

    def soft_delete_custom(self, scope: TenantScope, config_id: str) -> None:
        """把配置标记为删除。"""
        record = self.get_custom(scope, config_id)
        if record is None:
            raise ValueError("missing")
        self.records[config_id] = StatConfigurationRecord(
            **{**record.__dict__, "is_deleted": True}
        )

    def list_preferences(self, scope: TenantScope) -> tuple[StatConfigurationPreferenceRecord, ...]:
        """按 tenant_id 过滤显示偏好。"""
        return tuple(item for item in self.preferences.values() if item.tenant_id == scope.tenant_id)

    def save_preference(
        self,
        scope: TenantScope,
        *,
        role: StatConfigurationRole,
        reference_type: StatConfigurationSource,
        reference_key: str,
        sort_order: int,
        hidden: bool,
    ) -> StatConfigurationPreferenceRecord:
        """保存内存显示偏好。"""
        record = StatConfigurationPreferenceRecord(
            tenant_id=scope.tenant_id,
            role=role,
            reference_type=reference_type,
            reference_key=reference_key,
            sort_order=sort_order,
            hidden=hidden,
            updated_at=_now(),
        )
        self.preferences[(scope.tenant_id, role.value, reference_type.value, reference_key)] = record
        return record

    def save_order(
        self,
        scope: TenantScope,
        *,
        role: StatConfigurationRole,
        ordered_references: tuple[StatConfigurationReference, ...],
    ) -> None:
        """按给定顺序批量保存偏好。"""
        for index, reference in enumerate(ordered_references):
            self.save_preference(
                scope,
                role=role,
                reference_type=reference.source,
                reference_key=reference.key,
                sort_order=index,
                hidden=False,
            )


def test_use_case_merges_filters_hides_and_sorts_with_tenant_scope() -> None:
    """
    application 用例负责把内置定义、租户自定义配置和偏好合并成统一列表。测试创建两个
    租户的 Pokémon 专属配置，断言当前租户只能看到自己的配置；同时隐藏内置极限物耐、
    保存排序后，列表和 fallback 都按可见项确定性返回。
    """
    repository = MemoryStatConfigurationRepository()
    use_case = StatConfigurationUseCase(repository)
    tenant_a = TenantScope("tenant-a")
    tenant_b = TenantScope("tenant-b")
    command = SaveStatConfigurationCommand(
        name="Scizor Bulk",
        nature_id="bold",
        evs=StatSpread.evs(hp=252, defense=252),
        ivs=StatSpread.perfect_ivs(),
        role=StatConfigurationRole.DEFENDER,
        binding_kind=PokemonBindingKind.POKEMON,
        pokemon_id=212,
    )
    created = use_case.create_custom(scope=tenant_a, command=command)
    use_case.create_custom(scope=tenant_b, command=command)

    use_case.set_hidden(
        scope=tenant_a,
        role=StatConfigurationRole.DEFENDER,
        reference=StatConfigurationReference(StatConfigurationSource.BUILTIN, "max_hp_def_plus"),
        hidden=True,
    )
    use_case.save_order(
        scope=tenant_a,
        role=StatConfigurationRole.DEFENDER,
        ordered_references=(
            StatConfigurationReference(StatConfigurationSource.CUSTOM, created.reference.key),
            StatConfigurationReference(StatConfigurationSource.BUILTIN, "max_hp"),
        ),
    )

    result = use_case.list_configurations(
        scope=tenant_a,
        role=StatConfigurationRole.DEFENDER,
        pokemon_id=212,
        include_hidden=True,
    )

    assert result.items[0].id == created.id
    assert result.fallback_id == created.id
    assert any(item.reference.key == "max_hp_def_plus" and item.hidden for item in result.items)
    assert all(item.pokemon_id in (None, 212) for item in result.items)
    assert not any(item.id == "custom:2" for item in result.items)


def _record(
    config_id: str,
    tenant_id: str,
    command: SaveStatConfigurationCommand,
) -> StatConfigurationRecord:
    """从保存命令创建内存 record。"""
    return StatConfigurationRecord(
        id=config_id,
        tenant_id=tenant_id,
        name=command.name,
        nature_id=command.nature_id,
        evs=command.evs,
        ivs=command.ivs,
        role=command.role,
        binding_kind=command.binding_kind,
        pokemon_id=command.pokemon_id,
        is_deleted=False,
        created_at=_now(),
        updated_at=_now(),
    )


def _now() -> datetime:
    """返回固定测试时间。"""
    return datetime(2026, 7, 31, tzinfo=timezone.utc)
