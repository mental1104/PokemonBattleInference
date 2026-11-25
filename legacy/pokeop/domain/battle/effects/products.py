from __future__ import annotations

from dataclasses import dataclass

from pokeop.domain.battle.effects.protocols import EffectCoverage


@dataclass(frozen=True, slots=True)
class NoOpMoveEffect:
    """表示当前规则集没有配置招式 effect，且该情况不属于能力缺失。"""

    coverage: EffectCoverage


@dataclass(frozen=True, slots=True)
class UnsupportedMoveEffect:
    """表示输入了当前规则集尚未实现的招式机制。"""

    coverage: EffectCoverage


@dataclass(frozen=True, slots=True)
class NoOpAbilityEffect:
    """表示当前宝可梦没有可参与回合阶段的特性 effect。"""

    coverage: EffectCoverage


@dataclass(frozen=True, slots=True)
class UnsupportedAbilityEffect:
    """表示输入了当前规则集尚未实现的特性机制。"""

    coverage: EffectCoverage


@dataclass(frozen=True, slots=True)
class NoOpItemEffect:
    """表示当前宝可梦没有可参与回合阶段的道具 effect。"""

    coverage: EffectCoverage


@dataclass(frozen=True, slots=True)
class UnsupportedItemEffect:
    """表示输入了当前规则集尚未实现的道具机制。"""

    coverage: EffectCoverage


__all__ = [
    "NoOpAbilityEffect",
    "NoOpItemEffect",
    "NoOpMoveEffect",
    "UnsupportedAbilityEffect",
    "UnsupportedItemEffect",
    "UnsupportedMoveEffect",
]
