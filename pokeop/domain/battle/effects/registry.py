from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Generic, Iterable, Mapping, Protocol, TypeVar

from pokeop.domain.battle.effects.protocols import BattleEffect

EffectT = TypeVar("EffectT", bound=BattleEffect)
EffectCovariantT = TypeVar(
    "EffectCovariantT",
    bound=BattleEffect,
    covariant=True,
)


def normalize_effect_identifier(identifier: str) -> str:
    """把边界字符串规范化为 registry 使用的稳定 identifier。

    Args:
        identifier: 来自 application、测试或数据映射层的机制名称。

    Returns:
        去除首尾空白、统一小写并把连字符和空格转换为下划线的标识。
    """
    return identifier.strip().lower().replace("-", "_").replace(" ", "_")


class EffectProvider(Protocol[EffectCovariantT]):
    """创建一个新的、不可变 battle effect 产品。"""

    def __call__(self) -> EffectCovariantT:
        """返回一次工厂解析使用的 effect 实例。"""
        ...


@dataclass(frozen=True, slots=True)
class EffectRegistration(Generic[EffectT]):
    """把一个规范化 identifier 显式绑定到类型化 effect provider。

    Attributes:
        identifier: registry 对外识别的机制标识。
        provider: 每次解析时创建 effect 产品的零参数 provider。
    """

    identifier: str
    provider: EffectProvider[EffectT]

    def __post_init__(self) -> None:
        """拒绝空 identifier，避免注册项只能通过隐式默认分支访问。"""
        if not normalize_effect_identifier(self.identifier):
            raise ValueError("effect registration identifier must not be blank")


class EffectRegistry(Generic[EffectT]):
    """维护显式、类型安全且不可变的 effect provider 映射。

    registry 只负责“已注册标识到实现”的映射。no-op 与 unsupported 的语义由
    抽象工厂根据输入来源决定，避免 registry 把未知机制静默吞成默认实现。
    """

    def __init__(
        self,
        registrations: Iterable[EffectRegistration[EffectT]] = (),
    ) -> None:
        """构建不可变 registry，并在发现重复标识时立即失败。

        Args:
            registrations: 显式注册项序列；同一规范化 identifier 只能出现一次。

        Raises:
            ValueError: 存在重复 identifier 时抛出。
        """
        providers: dict[str, EffectProvider[EffectT]] = {}
        for registration in registrations:
            identifier = normalize_effect_identifier(registration.identifier)
            if identifier in providers:
                raise ValueError(f"duplicate effect registration: {identifier}")
            providers[identifier] = registration.provider
        self._providers: Mapping[str, EffectProvider[EffectT]] = MappingProxyType(
            providers
        )

    def create(self, identifier: str) -> EffectT | None:
        """按 identifier 创建 effect；未注册时返回 None 交由工厂判定覆盖状态。

        Args:
            identifier: 已知或候选机制标识。

        Returns:
            已注册时返回 provider 创建的新 effect；否则返回 None。
        """
        provider = self._providers.get(normalize_effect_identifier(identifier))
        if provider is None:
            return None
        return provider()

    def with_registration(
        self,
        registration: EffectRegistration[EffectT],
    ) -> "EffectRegistry[EffectT]":
        """返回追加一个注册项的新 registry，原 registry 保持不变。

        Args:
            registration: 要追加的 identifier 与 provider。

        Returns:
            包含原有注册项和新增注册项的新 registry。

        Raises:
            ValueError: 新 identifier 与原有注册项重复时抛出。
        """
        identifier = normalize_effect_identifier(registration.identifier)
        if identifier in self._providers:
            raise ValueError(f"duplicate effect registration: {identifier}")
        registrations = tuple(
            EffectRegistration(existing_identifier, provider)
            for existing_identifier, provider in self._providers.items()
        ) + (registration,)
        return EffectRegistry(registrations)

    @property
    def identifiers(self) -> tuple[str, ...]:
        """返回按注册顺序保存的所有规范化 identifier。"""
        return tuple(self._providers)


__all__ = [
    "EffectProvider",
    "EffectRegistration",
    "EffectRegistry",
    "normalize_effect_identifier",
]
