"""配置预设 API 的请求和响应 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from pokeop.application.use_cases.stat_configurations import (
    SaveStatConfigurationCommand,
    StatConfigurationListResult,
    StatConfigurationReference,
    StatConfigurationView,
)
from pokeop.domain.configuration_presets import (
    MAX_PRESET_NAME_LENGTH,
    PokemonBindingKind,
    StatConfigurationRole,
    StatConfigurationSource,
    StatSpread,
)


class StatSpreadSchema(BaseModel):
    """六项能力投入的 JSON 表达。"""

    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int

    def to_evs(self) -> StatSpread:
        """按努力值规则转换并校验。"""
        return StatSpread.evs(**self.model_dump())

    def to_ivs(self) -> StatSpread:
        """按个体值规则转换并校验。"""
        return StatSpread.ivs(**self.model_dump())


class SaveStatConfigurationRequest(BaseModel):
    """创建或编辑自定义配置的请求。"""

    name: str = Field(min_length=1, max_length=MAX_PRESET_NAME_LENGTH)
    nature_id: str = Field(min_length=1)
    evs: StatSpreadSchema
    ivs: StatSpreadSchema = Field(default_factory=lambda: StatSpreadSchema(
        hp=31,
        attack=31,
        defense=31,
        special_attack=31,
        special_defense=31,
        speed=31,
    ))
    role: StatConfigurationRole
    binding_kind: PokemonBindingKind
    pokemon_id: int | None = None

    @model_validator(mode="after")
    def validate_binding(self) -> "SaveStatConfigurationRequest":
        """校验 Pokémon 绑定字段形状。"""
        if self.binding_kind is PokemonBindingKind.GLOBAL and self.pokemon_id is not None:
            raise ValueError("global configuration must not include pokemon_id")
        if self.binding_kind is PokemonBindingKind.POKEMON and (
            self.pokemon_id is None or self.pokemon_id <= 0
        ):
            raise ValueError("pokemon binding requires positive pokemon_id")
        return self

    def to_command(self) -> SaveStatConfigurationCommand:
        """转换为 application 保存命令。"""
        return SaveStatConfigurationCommand(
            name=self.name.strip(),
            nature_id=self.nature_id,
            evs=self.evs.to_evs(),
            ivs=self.ivs.to_ivs(),
            role=self.role,
            binding_kind=self.binding_kind,
            pokemon_id=self.pokemon_id,
        )


class ConfigurationReferenceRequest(BaseModel):
    """前端操作内置或自定义配置时传入的带类型引用。"""

    source: StatConfigurationSource
    key: str = Field(min_length=1)

    def to_application(self) -> StatConfigurationReference:
        """转换为 application 统一引用。"""
        return StatConfigurationReference(source=self.source, key=self.key)


class SaveOrderRequest(BaseModel):
    """批量保存排序的请求。"""

    role: StatConfigurationRole
    references: list[ConfigurationReferenceRequest]

    @model_validator(mode="after")
    def validate_role(self) -> "SaveOrderRequest":
        """排序只接受具体攻方或防守方列表。"""
        if self.role is StatConfigurationRole.BOTH:
            raise ValueError("order role must be attacker or defender")
        return self


class SetHiddenRequest(BaseModel):
    """隐藏或恢复配置的请求。"""

    role: StatConfigurationRole
    reference: ConfigurationReferenceRequest
    hidden: bool

    @model_validator(mode="after")
    def validate_role(self) -> "SetHiddenRequest":
        """隐藏偏好按页面侧保存，不能保存 both。"""
        if self.role is StatConfigurationRole.BOTH:
            raise ValueError("hidden role must be attacker or defender")
        return self


class NatureResponse(BaseModel):
    """合法性格元数据。"""

    identifier: str
    label: str
    increased_stat: str | None
    decreased_stat: str | None


class StatConfigurationResponse(BaseModel):
    """统一配置读取模型。"""

    id: str
    source: StatConfigurationSource
    key: str
    name: str
    nature_id: str
    evs: StatSpreadSchema
    ivs: StatSpreadSchema
    role: StatConfigurationRole
    binding_kind: PokemonBindingKind
    pokemon_id: int | None
    description: str
    hidden: bool
    visible: bool
    sort_order: int
    editable: bool
    renamable: bool
    deletable: bool
    hideable: bool
    snapshot_profile_id: str
    updated_at: datetime | None


class StatConfigurationListResponse(BaseModel):
    """配置列表接口响应。"""

    items: list[StatConfigurationResponse]
    visible_items: list[StatConfigurationResponse]
    default_visible_limit: int
    fallback_id: str | None


def spread_response(spread: StatSpread) -> StatSpreadSchema:
    """把 domain StatSpread 转换为 HTTP schema。"""
    return StatSpreadSchema(**spread.to_dict())


def configuration_response(view: StatConfigurationView) -> StatConfigurationResponse:
    """把 application view 转换为 HTTP 响应。"""
    return StatConfigurationResponse(
        id=view.id,
        source=view.source,
        key=view.reference.key,
        name=view.name,
        nature_id=view.nature_id,
        evs=spread_response(view.evs),
        ivs=spread_response(view.ivs),
        role=view.role,
        binding_kind=view.binding_kind,
        pokemon_id=view.pokemon_id,
        description=view.description,
        hidden=view.hidden,
        visible=view.visible,
        sort_order=view.sort_order,
        editable=view.editable,
        renamable=view.renamable,
        deletable=view.deletable,
        hideable=view.hideable,
        snapshot_profile_id=view.snapshot_profile_id,
        updated_at=view.updated_at,
    )


def list_response(result: StatConfigurationListResult) -> StatConfigurationListResponse:
    """把 application 列表结果转换为 HTTP 响应。"""
    return StatConfigurationListResponse(
        items=[configuration_response(item) for item in result.items],
        visible_items=[configuration_response(item) for item in result.visible_items],
        default_visible_limit=result.default_visible_limit,
        fallback_id=result.fallback_id,
    )


__all__ = [
    "NatureResponse",
    "SaveOrderRequest",
    "SaveStatConfigurationRequest",
    "SetHiddenRequest",
    "StatConfigurationListResponse",
    "StatConfigurationResponse",
    "configuration_response",
    "list_response",
]
