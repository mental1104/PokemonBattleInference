"""验证 1v1 配置空间的合法枚举、等价归并、覆盖统计和扩展边界。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

import pytest

from pokeop.application.configuration_space import (
    AbilityConfigurationCandidate,
    AbilitySpaceCommand,
    ConfigurationGenerationContext,
    ConfigurationSpaceError,
    ConfigurationWeightAssumption,
    DimensionExpansion,
    GenerateConfigurationSpaceCommand,
    GenerateConfigurationSpaceUseCase,
    ItemSpaceCommand,
    MechanismSupportStatus,
    MoveConfigurationCandidate,
    MoveSpaceCommand,
    OpaqueDimensionValue,
    PokemonConfigurationGenerator,
    PokemonConfigurationProfile,
    PokemonSpaceCommand,
    StatEnumerationMode,
    StatSpaceCommand,
)
from pokeop.application.configuration_space.providers import (
    DEFAULT_DIMENSION_PROVIDERS,
)
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.effects.protocols import (
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
)
from pokeop.domain.battle.effects.registry import normalize_effect_identifier
from pokeop.domain.battle.specs import MoveSpec
from pokeop.domain.battle.stats import NatureModifier, StatValues
from pokeop.domain.models.pokemon_fields import StatField
from pokeop.domain.models.types import Type


@dataclass(frozen=True, slots=True)
class _Effect:
    """提供测试 factory 返回值所需的最小 coverage 接口。"""

    coverage: EffectCoverage


@dataclass(frozen=True, slots=True)
class _FakeEffectFactory:
    """按显式集合模拟当前规则集可创建的招式、特性和道具 effect。"""

    supported_move_effects: frozenset[str] = frozenset()
    supported_abilities: frozenset[str] = frozenset()
    supported_items: frozenset[str] = frozenset({"choice_band"})
    ruleset_id: str = "pokemon-champion"

    def _effect(
        self,
        kind: EffectSourceKind,
        identifier: str,
        status: EffectCoverageStatus,
        reason: str,
    ) -> _Effect:
        """构造带稳定规则集、来源、标识和解释的测试 effect。"""
        return _Effect(
            EffectCoverage(
                ruleset_id=self.ruleset_id,
                source_kind=kind,
                identifier=identifier,
                status=status,
                reason=reason,
            )
        )

    def create_move_effect(self, identifier: str | None) -> _Effect:
        """None 表示纯通用招式行为，其余标识按显式支持集合裁决。"""
        if identifier is None:
            return self._effect(
                EffectSourceKind.MOVE,
                "none",
                EffectCoverageStatus.NO_EFFECT,
                "No additional move effect is required.",
            )
        normalized = normalize_effect_identifier(identifier)
        status = (
            EffectCoverageStatus.SUPPORTED
            if normalized in self.supported_move_effects
            else EffectCoverageStatus.UNSUPPORTED
        )
        return self._effect(
            EffectSourceKind.MOVE,
            normalized,
            status,
            (
                "Move effect is supported."
                if status is EffectCoverageStatus.SUPPORTED
                else "Move effect is unsupported."
            ),
        )

    def create_ability_effect(self, identifier: str | None) -> _Effect:
        """只为显式注册的特性标识返回 supported coverage。"""
        normalized = "none" if identifier is None else normalize_effect_identifier(identifier)
        status = (
            EffectCoverageStatus.SUPPORTED
            if normalized in self.supported_abilities
            else EffectCoverageStatus.UNSUPPORTED
        )
        return self._effect(
            EffectSourceKind.ABILITY,
            normalized,
            status,
            (
                "Ability effect is supported."
                if status is EffectCoverageStatus.SUPPORTED
                else "Ability effect is unsupported."
            ),
        )

    def create_item_effect(self, identifier: str | None) -> _Effect:
        """明确区分无道具 no-effect 与受支持或未支持的实际道具。"""
        if identifier is None:
            return self._effect(
                EffectSourceKind.ITEM,
                "none",
                EffectCoverageStatus.NO_EFFECT,
                "No held item is configured.",
            )
        normalized = normalize_effect_identifier(identifier)
        status = (
            EffectCoverageStatus.SUPPORTED
            if normalized in self.supported_items
            else EffectCoverageStatus.UNSUPPORTED
        )
        return self._effect(
            EffectSourceKind.ITEM,
            normalized,
            status,
            (
                "Item effect is supported."
                if status is EffectCoverageStatus.SUPPORTED
                else "Item effect is unsupported."
            ),
        )


def _move(
    move_id: int,
    name: str,
    move_type: Type,
    power: int,
    *,
    pp: int = 15,
    priority: int = 0,
    category: MoveCategory = MoveCategory.PHYSICAL,
    effect_identifier: str | None = None,
    support_status: MechanismSupportStatus = MechanismSupportStatus.SUPPORTED,
) -> MoveConfigurationCandidate:
    """创建测试使用的 version-aware 招式候选，集中维护 PP、优先级和覆盖字段。"""
    return MoveConfigurationCandidate(
        move_spec=MoveSpec(
            move_id=move_id,
            move=BattleMove(name, move_type, category, power),
            max_pp=pp,
            priority=priority,
            accuracy=100,
        ),
        effect_identifier=effect_identifier,
        support_status=support_status,
        support_reason=f"{name} projection coverage is {support_status.value}.",
    )


def _dragonite_profile() -> PokemonConfigurationProfile:
    """创建快龙在受控 fixture 中使用的合法候选读取模型。"""
    return PokemonConfigurationProfile(
        ruleset_id="pokemon-champion",
        version_group_id=31,
        pokemon_id=149,
        name="dragonite",
        types=(Type.DRAGON, Type.FLYING),
        base_stats=StatValues(91, 134, 95, 100, 100, 80),
        moves=(
            _move(245, "extreme-speed", Type.NORMAL, 80, pp=5, priority=2),
            _move(280, "brick-break", Type.FIGHTING, 75, effect_identifier="break-screens"),
            _move(
                355,
                "roost",
                Type.FLYING,
                0,
                category=MoveCategory.STATUS,
                support_status=MechanismSupportStatus.PARTIAL,
            ),
        ),
        abilities=(
            AbilityConfigurationCandidate("inner-focus"),
            AbilityConfigurationCandidate("multiscale"),
        ),
    )


def _weavile_profile() -> PokemonConfigurationProfile:
    """创建玛纽拉在受控 fixture 中使用的合法候选读取模型。"""
    return PokemonConfigurationProfile(
        ruleset_id="pokemon-champion",
        version_group_id=31,
        pokemon_id=461,
        name="weavile",
        types=(Type.DARK, Type.ICE),
        base_stats=StatValues(70, 120, 65, 45, 85, 125),
        moves=(
            _move(
                252,
                "fake-out",
                Type.NORMAL,
                40,
                pp=10,
                priority=3,
                effect_identifier="fake-out",
            ),
            _move(420, "ice-shard", Type.ICE, 40, pp=30, priority=1),
            _move(8, "ice-punch", Type.ICE, 75),
        ),
        abilities=(
            AbilityConfigurationCandidate("pressure"),
            AbilityConfigurationCandidate("pickpocket"),
        ),
    )


def _generator(factory: _FakeEffectFactory, *, extra_providers=()) -> PokemonConfigurationGenerator:
    """创建包含标准四维和可选扩展维度的单边配置生成器。"""
    return PokemonConfigurationGenerator(
        effect_factory=factory,
        providers=DEFAULT_DIMENSION_PROVIDERS + tuple(extra_providers),
    )


def _single_command(
    *,
    move_ids: tuple[int, ...],
    ability: str,
    item: str | None = None,
    stat_command: StatSpaceCommand | None = None,
) -> PokemonSpaceCommand:
    """创建每个非能力维度只有一个代表值的紧凑测试 command。"""
    return PokemonSpaceCommand(
        moves=MoveSpaceCommand(move_ids, (len(move_ids),)),
        stats=stat_command or StatSpaceCommand(
            mode=StatEnumerationMode.PRESET,
            preset_keys=("max_atk_plus",),
        ),
        abilities=AbilitySpaceCommand((ability,)),
        items=ItemSpaceCommand((item,)),
        max_raw_configurations=10_000,
    )




@dataclass(frozen=True, slots=True)
class _FakeDimensionProvider:
    """模拟未来新增、主循环和标准四维均未知的规则维度。"""

    @property
    def dimension_key(self) -> str:
        """返回测试扩展维度稳定键。"""
        return "fake-rule"

    def expand(self, context: ConfigurationGenerationContext) -> DimensionExpansion:
        """为每一方返回两个行为不同的扩展值，证明无需修改组合主循环。"""
        return DimensionExpansion(
            values=(
                OpaqueDimensionValue("fake-rule", "alpha", "alpha"),
                OpaqueDimensionValue("fake-rule", "beta", "beta"),
            )
        )
