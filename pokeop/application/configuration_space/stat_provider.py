"""实现 preset 与受控离散 EV/性格枚举及最终能力值归并。"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import product

from pokeop.application.configuration_space.model_base import (
    ConfigurationSpaceError,
    StatEnumerationMode,
)
from pokeop.application.configuration_space.provider_core import (
    ConfigurationGenerationContext,
    DimensionExpansion,
    StatDimensionValue,
)
from pokeop.application.presets.stat_profiles import PRESETS
from pokeop.domain.battle.stats import (
    NatureModifier,
    StatProfile,
    StatValues,
    calculate_actual_stats,
)
from pokeop.domain.models.pokemon_fields import StatField


class StatDimensionProvider:
    """生成合法 EV/性格配置，并以 50 级等指定等级最终能力值归并。"""

    @property
    def dimension_key(self) -> str:
        """返回能力配置维度稳定键。"""
        return "stats"

    def expand(self, context: ConfigurationGenerationContext) -> DimensionExpansion:
        """根据 preset 或离散枚举命令生成最终能力值代表类。

        Args:
            context: 当前 Pokémon profile、等级和显式能力枚举边界。

        Returns:
            以最终 ``StatValues`` 为签名的唯一能力配置代表值。

        Raises:
            ConfigurationSpaceError: preset 不存在或合法原始能力配置超过上限时抛出。
        """
        grouped: dict[StatValues, StatDimensionValue] = {}
        raw_profile_count = 0

        for profile, label in self._raw_profiles(context):
            raw_profile_count += 1
            if raw_profile_count > context.command.stats.max_raw_profiles:
                raise ConfigurationSpaceError(
                    "stat enumeration exceeds max_raw_profiles before deduplication"
                )
            actual_stats = calculate_actual_stats(profile, level=context.command.level)
            current = grouped.get(actual_stats)
            if current is None:
                grouped[actual_stats] = StatDimensionValue(
                    stat_profile=profile,
                    actual_stats=actual_stats,
                    label=label,
                )
            else:
                grouped[actual_stats] = StatDimensionValue(
                    stat_profile=current.stat_profile,
                    actual_stats=current.actual_stats,
                    label=current.label,
                    member_count=current.member_count + 1,
                )

        return DimensionExpansion(values=tuple(grouped.values()))

    def _raw_profiles(
        self,
        context: ConfigurationGenerationContext,
    ) -> Iterable[tuple[StatProfile, str]]:
        """惰性生成通过单项 252 和总量 510 约束的原始 StatProfile。

        Args:
            context: 当前 Pokémon 种族值和能力枚举 command。

        Returns:
            逐项产出的 ``(StatProfile, label)``；label 只用于解释 representative。
            采用惰性迭代，确保 ``max_raw_profiles`` 能在组合爆炸前及时中止。
        """
        command = context.command.stats
        if command.mode is StatEnumerationMode.PRESET:
            for key in command.preset_keys:
                preset = PRESETS.get(key)
                if preset is None:
                    raise ConfigurationSpaceError(f"unknown stat profile preset: {key}")
                profile = preset.apply(context.profile.base_stats)
                self._validate_evs(profile.evs)
                yield profile, f"preset:{key}"
            return

        for values in product(command.ev_values, repeat=len(command.relevant_fields)):
            evs = StatValues.zero()
            for field, value in zip(command.relevant_fields, values, strict=True):
                evs = evs.with_value(field, value)
            if self._ev_total(evs) > 510:
                continue
            for nature in command.nature_modifiers:
                profile = StatProfile(
                    base_stats=context.profile.base_stats,
                    evs=evs,
                    nature_modifier=nature,
                )
                label = self._controlled_label(evs, nature, command.relevant_fields)
                yield profile, label

    @staticmethod
    def _ev_total(evs: StatValues) -> int:
        """返回六项 EV 总和，用于执行 510 总量上限。"""
        return (
            evs.hp
            + evs.attack
            + evs.defense
            + evs.special_attack
            + evs.special_defense
            + evs.speed
        )

    @classmethod
    def _validate_evs(cls, evs: StatValues) -> None:
        """校验 preset 也必须遵守单项 252 和总量 510 的游戏约束。

        Args:
            evs: 需要验证的六项努力值。

        Raises:
            ConfigurationSpaceError: 任一单项或总量越界时抛出。
        """
        values = (
            evs.hp,
            evs.attack,
            evs.defense,
            evs.special_attack,
            evs.special_defense,
            evs.speed,
        )
        if any(isinstance(value, bool) or not 0 <= value <= 252 for value in values):
            raise ConfigurationSpaceError("each EV value must be between 0 and 252")
        if cls._ev_total(evs) > 510:
            raise ConfigurationSpaceError("total EVs must not exceed 510")

    @staticmethod
    def _controlled_label(
        evs: StatValues,
        nature: NatureModifier,
        fields: tuple[StatField, ...],
    ) -> str:
        """为受控枚举 representative 生成稳定、可读但不参与判等的说明。"""
        ev_label = ",".join(f"{field.value}={evs.value_for(field)}" for field in fields)
        nature_label = (
            f"atk={nature.attack},def={nature.defense},spa={nature.special_attack},"
            f"spd={nature.special_defense},spe={nature.speed}"
        )
        return f"ev:{ev_label};nature:{nature_label}"




__all__ = ["StatDimensionProvider"]
