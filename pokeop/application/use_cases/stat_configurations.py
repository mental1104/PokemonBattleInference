"""配置预设管理的 application 用例。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from pokeop.domain.configuration_presets import (
    MAX_PRESET_NAME_LENGTH,
    NATURES,
    PokemonBindingKind,
    StatConfiguration,
    StatConfigurationRole,
    StatConfigurationSource,
    StatSpread,
    TenantScope,
)


@dataclass(frozen=True, slots=True)
class StatConfigurationRecord:
    """持久化层返回的一条租户自定义配置记录。"""

    id: str
    tenant_id: str
    name: str
    nature_id: str
    evs: StatSpread
    ivs: StatSpread
    role: StatConfigurationRole
    binding_kind: PokemonBindingKind
    pokemon_id: int | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StatConfigurationPreferenceRecord:
    """持久化层返回的一条配置显示偏好。"""

    tenant_id: str
    role: StatConfigurationRole
    reference_type: StatConfigurationSource
    reference_key: str
    sort_order: int
    hidden: bool
    updated_at: datetime


class StatConfigurationRepository(Protocol):
    """application 依赖的配置预设持久化端口。"""

    def list_custom(self, scope: TenantScope) -> tuple[StatConfigurationRecord, ...]:
        """列出当前租户未删除和已删除标记之外的自定义配置。"""

    def get_custom(self, scope: TenantScope, config_id: str) -> StatConfigurationRecord | None:
        """按稳定 ID 读取当前租户的一条自定义配置；不存在时返回 None。"""

    def create_custom(self, scope: TenantScope, command: "SaveStatConfigurationCommand") -> StatConfigurationRecord:
        """创建当前租户共享的自定义配置。"""

    def update_custom(self, scope: TenantScope, config_id: str, command: "SaveStatConfigurationCommand") -> StatConfigurationRecord:
        """完整更新当前租户的一条自定义配置。"""

    def soft_delete_custom(self, scope: TenantScope, config_id: str) -> None:
        """软删除当前租户的一条自定义配置，历史任务快照不受影响。"""

    def list_preferences(self, scope: TenantScope) -> tuple[StatConfigurationPreferenceRecord, ...]:
        """列出当前租户全部显示偏好。"""

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
        """幂等保存单条显示偏好。"""

    def save_order(
        self,
        scope: TenantScope,
        *,
        role: StatConfigurationRole,
        ordered_references: tuple["StatConfigurationReference", ...],
    ) -> None:
        """在一个事务中批量保存当前角色的排序。"""


@dataclass(frozen=True, slots=True)
class StatConfigurationReference:
    """统一引用内置 key 或自定义配置 ID。"""

    source: StatConfigurationSource
    key: str

    def stable_id(self) -> str:
        """返回前端可直接作为 v-for key 和操作对象的带类型 ID。"""
        return f"{self.source.value}:{self.key}"


@dataclass(frozen=True, slots=True)
class SaveStatConfigurationCommand:
    """创建或编辑自定义配置的 application 命令。"""

    name: str
    nature_id: str
    evs: StatSpread
    ivs: StatSpread
    role: StatConfigurationRole
    binding_kind: PokemonBindingKind
    pokemon_id: int | None = None

    def to_domain(self, key: str, source: StatConfigurationSource) -> StatConfiguration:
        """把保存命令转换为纯领域配置并执行全部业务校验。"""
        return StatConfiguration(
            key=key,
            source=source,
            name=self.name,
            nature_id=self.nature_id,
            evs=self.evs,
            ivs=self.ivs,
            role=self.role,
            binding_kind=self.binding_kind,
            pokemon_id=self.pokemon_id,
        )


@dataclass(frozen=True, slots=True)
class StatConfigurationView:
    """API 返回给前端的统一配置读取模型。"""

    id: str
    reference: StatConfigurationReference
    name: str
    source: StatConfigurationSource
    nature_id: str
    evs: StatSpread
    ivs: StatSpread
    role: StatConfigurationRole
    binding_kind: PokemonBindingKind
    pokemon_id: int | None
    description: str
    hidden: bool
    sort_order: int
    visible: bool
    editable: bool
    renamable: bool
    deletable: bool
    hideable: bool
    snapshot_profile_id: str
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class StatConfigurationListResult:
    """配置列表与当前默认回退选择。"""

    items: tuple[StatConfigurationView, ...]
    visible_items: tuple[StatConfigurationView, ...]
    default_visible_limit: int
    fallback_id: str | None


class StatConfigurationError(ValueError):
    """表示配置管理中的业务错误。"""


def _builtin(
    key: str,
    name: str,
    *,
    nature_id: str,
    evs: StatSpread,
    role: StatConfigurationRole,
    description: str,
) -> StatConfiguration:
    """构造一条内置配置定义。"""
    return StatConfiguration(
        key=key,
        source=StatConfigurationSource.BUILTIN,
        name=name,
        nature_id=nature_id,
        evs=evs,
        ivs=StatSpread.perfect_ivs(),
        role=role,
        description=description,
    )


BUILTIN_CONFIGURATIONS: dict[str, StatConfiguration] = {
    preset.key: preset
    for preset in (
        _builtin(
            "no_investment",
            "无投入",
            nature_id="hardy",
            evs=StatSpread.evs(),
            role=StatConfigurationRole.BOTH,
            description="0 EV、6V、中性性格，适合做无投入基线。",
        ),
        _builtin(
            "max_atk_plus",
            "极限物攻",
            nature_id="adamant",
            evs=StatSpread.evs(attack=252),
            role=StatConfigurationRole.ATTACKER,
            description="252 Attack EV、攻击性格，用于物理攻击方上限。",
        ),
        _builtin(
            "max_spatk_plus",
            "极限特攻",
            nature_id="modest",
            evs=StatSpread.evs(special_attack=252),
            role=StatConfigurationRole.ATTACKER,
            description="252 Special Attack EV、特攻性格，用于特殊攻击方上限。",
        ),
        _builtin(
            "max_speed_plus",
            "极限速度",
            nature_id="jolly",
            evs=StatSpread.evs(speed=252),
            role=StatConfigurationRole.BOTH,
            description="252 Speed EV、速度性格，用于速度线比较。",
        ),
        _builtin(
            "max_hp",
            "满 HP",
            nature_id="hardy",
            evs=StatSpread.evs(hp=252),
            role=StatConfigurationRole.DEFENDER,
            description="252 HP EV、中性性格，用于基础耐久线。",
        ),
        _builtin(
            "max_hp_def_plus",
            "极限物耐",
            nature_id="bold",
            evs=StatSpread.evs(hp=252, defense=252),
            role=StatConfigurationRole.DEFENDER,
            description="252 HP / 252 Defense EV、防御性格。",
        ),
        _builtin(
            "max_hp_spdef_plus",
            "极限特耐",
            nature_id="calm",
            evs=StatSpread.evs(hp=252, special_defense=252),
            role=StatConfigurationRole.DEFENDER,
            description="252 HP / 252 Special Defense EV、特防性格。",
        ),
    )
}


class StatConfigurationUseCase:
    """编排内置配置、租户自定义配置和显示偏好的合并读取与写入。"""

    def __init__(self, repository: StatConfigurationRepository) -> None:
        """保存配置 repository 端口。

        Args:
            repository: 负责租户自定义配置和显示偏好持久化的实现。
        """
        self._repository = repository

    def list_configurations(
        self,
        *,
        scope: TenantScope,
        role: StatConfigurationRole,
        pokemon_id: int,
        include_hidden: bool = False,
    ) -> StatConfigurationListResult:
        """读取当前 Pokémon 和角色可用的统一配置列表。"""
        if pokemon_id <= 0:
            raise StatConfigurationError("pokemon_id must be positive")
        preferences = {
            (item.role, item.reference_type, item.reference_key): item
            for item in self._repository.list_preferences(scope)
        }
        views: list[StatConfigurationView] = []
        for builtin in BUILTIN_CONFIGURATIONS.values():
            if builtin.applies_to(pokemon_id=pokemon_id, role=role):
                views.append(self._view_from_domain(builtin, role=role, preferences=preferences, updated_at=None))
        for record in self._repository.list_custom(scope):
            if record.is_deleted:
                continue
            domain = _domain_from_record(record)
            if domain.applies_to(pokemon_id=pokemon_id, role=role):
                views.append(self._view_from_domain(domain, role=role, preferences=preferences, updated_at=record.updated_at))

        views.sort(key=lambda item: (item.hidden, item.sort_order, item.source.value, item.name, item.id))
        visible = tuple(item for item in views if not item.hidden)
        returned = tuple(views if include_hidden else visible)
        return StatConfigurationListResult(
            items=returned,
            visible_items=visible,
            default_visible_limit=6,
            fallback_id=visible[0].id if visible else None,
        )

    def create_custom(
        self,
        *,
        scope: TenantScope,
        command: SaveStatConfigurationCommand,
    ) -> StatConfigurationView:
        """创建租户共享自定义配置并返回统一读取模型。"""
        command.to_domain("new", StatConfigurationSource.CUSTOM)
        record = self._repository.create_custom(scope, command)
        return self._view_from_domain(
            _domain_from_record(record),
            role=record.role,
            preferences={},
            updated_at=record.updated_at,
        )

    def update_custom(
        self,
        *,
        scope: TenantScope,
        config_id: str,
        command: SaveStatConfigurationCommand,
    ) -> StatConfigurationView:
        """完整更新租户自定义配置。"""
        command.to_domain(config_id, StatConfigurationSource.CUSTOM)
        record = self._repository.update_custom(scope, config_id, command)
        return self._view_from_domain(
            _domain_from_record(record),
            role=record.role,
            preferences={},
            updated_at=record.updated_at,
        )

    def delete_custom(self, *, scope: TenantScope, config_id: str) -> None:
        """软删除租户自定义配置，避免历史计算输入失去解释能力。"""
        self._repository.soft_delete_custom(scope, config_id)

    def set_hidden(
        self,
        *,
        scope: TenantScope,
        role: StatConfigurationRole,
        reference: StatConfigurationReference,
        hidden: bool,
    ) -> None:
        """隐藏或恢复配置显示偏好。"""
        self._ensure_reference_exists(scope, reference)
        self._repository.save_preference(
            scope,
            role=role,
            reference_type=reference.source,
            reference_key=reference.key,
            sort_order=0,
            hidden=hidden,
        )

    def save_order(
        self,
        *,
        scope: TenantScope,
        role: StatConfigurationRole,
        ordered_references: tuple[StatConfigurationReference, ...],
    ) -> None:
        """批量保存当前角色配置排序。"""
        seen: set[str] = set()
        for reference in ordered_references:
            if reference.stable_id() in seen:
                raise StatConfigurationError("duplicate configuration reference in order")
            seen.add(reference.stable_id())
            self._ensure_reference_exists(scope, reference)
        self._repository.save_order(scope, role=role, ordered_references=ordered_references)

    def list_natures(self) -> tuple[dict[str, str | None], ...]:
        """返回合法性格元数据，供前端选择器统一展示。"""
        return tuple(
            {
                "identifier": nature.identifier,
                "label": nature.label,
                "increased_stat": nature.increased_stat.value if nature.increased_stat else None,
                "decreased_stat": nature.decreased_stat.value if nature.decreased_stat else None,
            }
            for nature in NATURES.values()
        )

    def _view_from_domain(
        self,
        config: StatConfiguration,
        *,
        role: StatConfigurationRole,
        preferences: dict[tuple[StatConfigurationRole, StatConfigurationSource, str], StatConfigurationPreferenceRecord],
        updated_at: datetime | None,
    ) -> StatConfigurationView:
        """把领域配置和偏好合并成统一前端读取模型。"""
        reference = StatConfigurationReference(config.source, config.key)
        preference = preferences.get((role, config.source, config.key))
        sort_order = preference.sort_order if preference else 1_000 + _default_sort_order(config)
        hidden = preference.hidden if preference else False
        is_custom = config.source is StatConfigurationSource.CUSTOM
        return StatConfigurationView(
            id=reference.stable_id(),
            reference=reference,
            name=config.name,
            source=config.source,
            nature_id=config.nature_id,
            evs=config.evs,
            ivs=config.ivs,
            role=config.role,
            binding_kind=config.binding_kind,
            pokemon_id=config.pokemon_id,
            description=config.description,
            hidden=hidden,
            sort_order=sort_order,
            visible=not hidden,
            editable=is_custom,
            renamable=is_custom,
            deletable=is_custom,
            hideable=True,
            snapshot_profile_id=config.snapshot_profile_id(),
            updated_at=updated_at,
        )

    def _ensure_reference_exists(self, scope: TenantScope, reference: StatConfigurationReference) -> None:
        """确认显示偏好引用的是已知内置或当前租户自定义配置。"""
        if reference.source is StatConfigurationSource.BUILTIN:
            if reference.key not in BUILTIN_CONFIGURATIONS:
                raise StatConfigurationError("builtin configuration not found")
            return
        record = self._repository.get_custom(scope, reference.key)
        if record is None or record.is_deleted:
            raise StatConfigurationError("custom configuration not found")


def _domain_from_record(record: StatConfigurationRecord) -> StatConfiguration:
    """把持久化记录转换为领域配置。"""
    return StatConfiguration(
        key=record.id,
        source=StatConfigurationSource.CUSTOM,
        name=record.name,
        nature_id=record.nature_id,
        evs=record.evs,
        ivs=record.ivs,
        role=record.role,
        binding_kind=record.binding_kind,
        pokemon_id=record.pokemon_id,
        description="租户共享自定义配置。",
    )


def _default_sort_order(config: StatConfiguration) -> int:
    """返回无显式偏好时的稳定排序值，自定义配置默认跟随内置项之后。"""
    builtin_order = tuple(BUILTIN_CONFIGURATIONS)
    if config.source is StatConfigurationSource.BUILTIN:
        return builtin_order.index(config.key) if config.key in builtin_order else 500
    return 10_000


def now_utc() -> datetime:
    """返回带 UTC 时区的当前时间，供 repository 测试注入前的默认实现使用。"""
    return datetime.now(timezone.utc)


__all__ = [
    "BUILTIN_CONFIGURATIONS",
    "MAX_PRESET_NAME_LENGTH",
    "SaveStatConfigurationCommand",
    "StatConfigurationError",
    "StatConfigurationListResult",
    "StatConfigurationPreferenceRecord",
    "StatConfigurationRecord",
    "StatConfigurationReference",
    "StatConfigurationRepository",
    "StatConfigurationUseCase",
    "StatConfigurationView",
]
