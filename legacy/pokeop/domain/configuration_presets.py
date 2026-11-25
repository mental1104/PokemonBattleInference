"""定义宝可梦配置预设的纯领域模型和值约束。"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

from pokeop.domain.battle.stats import NatureModifier, StatProfile, StatValues
from pokeop.domain.models.pokemon_fields import StatField


STAT_FIELDS: tuple[StatField, ...] = (
    StatField.HP,
    StatField.ATTACK,
    StatField.DEFENSE,
    StatField.SPECIAL_ATTACK,
    StatField.SPECIAL_DEFENSE,
    StatField.SPEED,
)
"""配置预设支持编辑的六项能力字段，顺序同时用于 API 和快照编码。"""

MAX_PRESET_NAME_LENGTH = 48
"""用户自定义配置名称的统一长度上限。"""

SNAPSHOT_PREFIX = "preset-snapshot:"
"""提交到计算链路的配置快照前缀，避免与内置业务 key 冲突。"""


class StatConfigurationRole(StrEnum):
    """表示配置可以被攻击方、防守方或双方使用。"""

    ATTACKER = "attacker"
    DEFENDER = "defender"
    BOTH = "both"

    def matches(self, requested: "StatConfigurationRole") -> bool:
        """判断当前配置是否适用于请求侧。

        Args:
            requested: 页面当前正在筛选的攻击方或防守方角色。

        Returns:
            配置为 both 或与请求角色相同时返回 True。
        """
        return self is StatConfigurationRole.BOTH or self is requested


class StatConfigurationSource(StrEnum):
    """标识配置定义来源。"""

    BUILTIN = "builtin"
    CUSTOM = "custom"


class PokemonBindingKind(StrEnum):
    """声明配置绑定到全部 Pokémon 或某个具体 pokemon_id。"""

    GLOBAL = "global"
    POKEMON = "pokemon"


@dataclass(frozen=True, slots=True)
class TenantScope:
    """表示当前请求可见的租户范围。

    Args:
        tenant_id: 服务端解析出的租户稳定标识；当前无认证系统时使用默认开发租户。
    """

    tenant_id: str

    def __post_init__(self) -> None:
        """校验租户标识可以安全参与持久化查询。"""
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class StatSpread:
    """保存六项整数能力投入，并按 EV 或 IV 规则校验边界。

    Args:
        hp: HP 对应数值。
        attack: Attack 对应数值。
        defense: Defense 对应数值。
        special_attack: Special Attack 对应数值。
        special_defense: Special Defense 对应数值。
        speed: Speed 对应数值。
    """

    hp: int = 0
    attack: int = 0
    defense: int = 0
    special_attack: int = 0
    special_defense: int = 0
    speed: int = 0

    @classmethod
    def evs(cls, **values: int) -> Self:
        """创建并校验努力值分布。

        Args:
            values: 六项能力字段的整数值，缺失字段按 0 处理。

        Returns:
            单项 0..252 且总和不超过 510 的努力值分布。
        """
        spread = cls(**values)
        spread.validate_evs()
        return spread

    @classmethod
    def ivs(cls, **values: int) -> Self:
        """创建并校验个体值分布。

        Args:
            values: 六项能力字段的整数值，缺失字段按 31 处理时应由调用方显式传入。

        Returns:
            单项 0..31 的个体值分布。
        """
        spread = cls(**values)
        spread.validate_ivs()
        return spread

    @classmethod
    def perfect_ivs(cls) -> Self:
        """创建六项均为 31 的默认个体值。"""
        return cls(31, 31, 31, 31, 31, 31)

    def total(self) -> int:
        """返回六项总和。"""
        return sum(self.values())

    def values(self) -> tuple[int, int, int, int, int, int]:
        """按固定能力顺序返回六项数值。"""
        return (
            self.hp,
            self.attack,
            self.defense,
            self.special_attack,
            self.special_defense,
            self.speed,
        )

    def validate_evs(self) -> None:
        """校验努力值单项和总量边界。

        Raises:
            ValueError: 任一单项不是整数、超出 0..252，或总和超过 510 时抛出。
        """
        if any(isinstance(value, bool) or not isinstance(value, int) for value in self.values()):
            raise ValueError("EV values must be integers")
        if any(value < 0 or value > 252 for value in self.values()):
            raise ValueError("each EV value must be between 0 and 252")
        if self.total() > 510:
            raise ValueError("total EVs must not exceed 510")

    def validate_ivs(self) -> None:
        """校验个体值单项边界。

        Raises:
            ValueError: 任一单项不是整数或超出 0..31 时抛出。
        """
        if any(isinstance(value, bool) or not isinstance(value, int) for value in self.values()):
            raise ValueError("IV values must be integers")
        if any(value < 0 or value > 31 for value in self.values()):
            raise ValueError("each IV value must be between 0 and 31")

    def to_stat_values(self) -> StatValues:
        """转换为现有 domain 能力值对象。"""
        return StatValues(
            hp=self.hp,
            attack=self.attack,
            defense=self.defense,
            special_attack=self.special_attack,
            special_defense=self.special_defense,
            speed=self.speed,
        )

    def to_dict(self) -> dict[str, int]:
        """转换为 API 和快照使用的字段字典。"""
        return {
            "hp": self.hp,
            "attack": self.attack,
            "defense": self.defense,
            "special_attack": self.special_attack,
            "special_defense": self.special_defense,
            "speed": self.speed,
        }


@dataclass(frozen=True, slots=True)
class NatureDefinition:
    """保存合法宝可梦性格及其能力修正。"""

    identifier: str
    label: str
    increased_stat: StatField | None
    decreased_stat: StatField | None

    def modifier(self) -> NatureModifier:
        """转换为现有 domain 计算使用的 NatureModifier。"""
        modifier = NatureModifier.neutral()
        if self.increased_stat is not None:
            modifier = modifier.with_modifier(self.increased_stat, 1.1)
        if self.decreased_stat is not None:
            modifier = modifier.with_modifier(self.decreased_stat, 0.9)
        return modifier


def _nature(identifier: str, label: str, inc: StatField | None, dec: StatField | None) -> NatureDefinition:
    """构造一条性格定义，集中避免调用处重复字段。"""
    return NatureDefinition(identifier, label, inc, dec)


NATURES: dict[str, NatureDefinition] = {
    item.identifier: item
    for item in (
        _nature("hardy", "Hardy", None, None),
        _nature("lonely", "Lonely", StatField.ATTACK, StatField.DEFENSE),
        _nature("brave", "Brave", StatField.ATTACK, StatField.SPEED),
        _nature("adamant", "Adamant", StatField.ATTACK, StatField.SPECIAL_ATTACK),
        _nature("naughty", "Naughty", StatField.ATTACK, StatField.SPECIAL_DEFENSE),
        _nature("bold", "Bold", StatField.DEFENSE, StatField.ATTACK),
        _nature("docile", "Docile", None, None),
        _nature("relaxed", "Relaxed", StatField.DEFENSE, StatField.SPEED),
        _nature("impish", "Impish", StatField.DEFENSE, StatField.SPECIAL_ATTACK),
        _nature("lax", "Lax", StatField.DEFENSE, StatField.SPECIAL_DEFENSE),
        _nature("timid", "Timid", StatField.SPEED, StatField.ATTACK),
        _nature("hasty", "Hasty", StatField.SPEED, StatField.DEFENSE),
        _nature("serious", "Serious", None, None),
        _nature("jolly", "Jolly", StatField.SPEED, StatField.SPECIAL_ATTACK),
        _nature("naive", "Naive", StatField.SPEED, StatField.SPECIAL_DEFENSE),
        _nature("modest", "Modest", StatField.SPECIAL_ATTACK, StatField.ATTACK),
        _nature("mild", "Mild", StatField.SPECIAL_ATTACK, StatField.DEFENSE),
        _nature("quiet", "Quiet", StatField.SPECIAL_ATTACK, StatField.SPEED),
        _nature("bashful", "Bashful", None, None),
        _nature("rash", "Rash", StatField.SPECIAL_ATTACK, StatField.SPECIAL_DEFENSE),
        _nature("calm", "Calm", StatField.SPECIAL_DEFENSE, StatField.ATTACK),
        _nature("gentle", "Gentle", StatField.SPECIAL_DEFENSE, StatField.DEFENSE),
        _nature("sassy", "Sassy", StatField.SPECIAL_DEFENSE, StatField.SPEED),
        _nature("careful", "Careful", StatField.SPECIAL_DEFENSE, StatField.SPECIAL_ATTACK),
        _nature("quirky", "Quirky", None, None),
    )
}


@dataclass(frozen=True, slots=True)
class StatConfiguration:
    """表示一份可用于计算的完整宝可梦能力配置。"""

    key: str
    source: StatConfigurationSource
    name: str
    nature_id: str
    evs: StatSpread
    ivs: StatSpread
    role: StatConfigurationRole
    binding_kind: PokemonBindingKind = PokemonBindingKind.GLOBAL
    pokemon_id: int | None = None
    description: str = ""

    def __post_init__(self) -> None:
        """校验配置名称、性格、投入、适用角色和 Pokémon 绑定。"""
        if not self.key.strip():
            raise ValueError("configuration key must not be blank")
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("configuration name must not be blank")
        if len(normalized_name) > MAX_PRESET_NAME_LENGTH:
            raise ValueError(f"configuration name must be at most {MAX_PRESET_NAME_LENGTH} characters")
        if self.nature_id not in NATURES:
            raise ValueError(f"unsupported nature: {self.nature_id}")
        self.evs.validate_evs()
        self.ivs.validate_ivs()
        if self.binding_kind is PokemonBindingKind.GLOBAL and self.pokemon_id is not None:
            raise ValueError("global configuration must not bind pokemon_id")
        if self.binding_kind is PokemonBindingKind.POKEMON and (
            isinstance(self.pokemon_id, bool) or self.pokemon_id is None or self.pokemon_id <= 0
        ):
            raise ValueError("pokemon-bound configuration requires a positive pokemon_id")
        object.__setattr__(self, "name", normalized_name)

    def applies_to(self, *, pokemon_id: int, role: StatConfigurationRole) -> bool:
        """判断配置是否适合当前 Pokémon 和攻防位置。"""
        if not self.role.matches(role):
            return False
        if self.binding_kind is PokemonBindingKind.GLOBAL:
            return True
        return self.pokemon_id == pokemon_id

    def to_profile(self, base_stats: StatValues) -> StatProfile:
        """把配置应用到指定宝可梦种族值，生成计算用 StatProfile。"""
        return StatProfile(
            base_stats=base_stats,
            evs=self.evs.to_stat_values(),
            ivs=self.ivs.to_stat_values(),
            nature_modifier=NATURES[self.nature_id].modifier(),
        )

    def snapshot_profile_id(self) -> str:
        """生成可直接提交到计算链路的不可变配置快照引用。"""
        payload = {
            "nature_id": self.nature_id,
            "evs": self.evs.to_dict(),
            "ivs": self.ivs.to_dict(),
            "label": self.name,
            "source": self.source.value,
            "key": self.key,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return SNAPSHOT_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def stat_configuration_from_snapshot(value: str) -> dict[str, Any] | None:
    """解析计算请求携带的配置快照。

    Args:
        value: 前端传入的 stat preset/profile 字符串。

    Returns:
        快照字典；不是快照格式时返回 None。

    Raises:
        ValueError: 快照无法解码或内部 EV/IV/nature 不合法时抛出。
    """
    if not value.startswith(SNAPSHOT_PREFIX):
        return None
    encoded = value[len(SNAPSHOT_PREFIX) :]
    padded = encoded + ("=" * (-len(encoded) % 4))
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid stat configuration snapshot") from exc
    nature_id = str(payload.get("nature_id", ""))
    if nature_id not in NATURES:
        raise ValueError(f"unsupported nature: {nature_id}")
    evs = StatSpread.evs(**_spread_payload(payload.get("evs")))
    ivs = StatSpread.ivs(**_spread_payload(payload.get("ivs")))
    return {"nature_id": nature_id, "evs": evs, "ivs": ivs, "label": str(payload.get("label", "自定义配置"))}


def stat_profile_from_snapshot(value: str, base_stats: StatValues) -> StatProfile | None:
    """将快照引用转换为 domain StatProfile；非快照输入返回 None。"""
    payload = stat_configuration_from_snapshot(value)
    if payload is None:
        return None
    return StatProfile(
        base_stats=base_stats,
        evs=payload["evs"].to_stat_values(),
        ivs=payload["ivs"].to_stat_values(),
        nature_modifier=NATURES[payload["nature_id"]].modifier(),
    )


def _spread_payload(value: object) -> dict[str, int]:
    """从 JSON payload 中抽取六项能力字典，拒绝缺失字段造成的偶然默认。"""
    if not isinstance(value, dict):
        raise ValueError("stat spread payload must be an object")
    result: dict[str, int] = {}
    for field in STAT_FIELDS:
        raw_value = value.get(field.value)
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise ValueError(f"{field.value} must be an integer")
        result[field.value] = raw_value
    return result


__all__ = [
    "MAX_PRESET_NAME_LENGTH",
    "NATURES",
    "SNAPSHOT_PREFIX",
    "PokemonBindingKind",
    "STAT_FIELDS",
    "StatConfiguration",
    "StatConfigurationRole",
    "StatConfigurationSource",
    "StatSpread",
    "TenantScope",
    "stat_configuration_from_snapshot",
    "stat_profile_from_snapshot",
]
