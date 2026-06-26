from __future__ import annotations

from dataclasses import dataclass, replace
from math import floor

from pokeop.domain.models.pokemon_fields import StatField


def _field_name(field: StatField | str) -> str:
    """把 StatField 枚举或字符串统一转换成 StatValues/NatureModifier 的字段名。"""
    return field.value if isinstance(field, StatField) else field


@dataclass(frozen=True)
class StatValues:
    """
    表示一组完整的六项宝可梦能力值。

    这个对象既可以表达种族值、努力值、个体值，也可以表达最终实际能力值；
    具体语义由外层的 StatProfile 或调用方决定。
    """

    hp: int = 0
    attack: int = 0
    defense: int = 0
    special_attack: int = 0
    special_defense: int = 0
    speed: int = 0

    @classmethod
    def zero(cls) -> "StatValues":
        """创建全部字段为 0 的能力值，用于默认努力值或空能力模板。"""
        return cls()

    @classmethod
    def perfect_ivs(cls) -> "StatValues":
        """创建默认 6V 个体值，即六项能力的 IV 都是 31。"""
        return cls(31, 31, 31, 31, 31, 31)

    def value_for(self, field: StatField | str) -> int:
        """按能力字段读取对应数值，调用方可以传 StatField 或字段名字符串。"""
        return getattr(self, _field_name(field))

    def with_value(self, field: StatField | str, value: int) -> "StatValues":
        """返回一个只替换指定能力字段的新 StatValues，原对象保持不变。"""
        return replace(self, **{_field_name(field): value})


@dataclass(frozen=True)
class NatureModifier:
    """
    表示性格对非 HP 能力的倍率修正。

    宝可梦性格不会修正 HP，因此 HP 始终按 1.0 处理；
    攻击、防御、特攻、特防、速度可以分别是 1.1、1.0 或 0.9。
    """

    attack: float = 1.0
    defense: float = 1.0
    special_attack: float = 1.0
    special_defense: float = 1.0
    speed: float = 1.0

    @classmethod
    def neutral(cls) -> "NatureModifier":
        """创建不修正任何能力的中性性格倍率。"""
        return cls()

    @classmethod
    def increase(cls, field: StatField | str) -> "NatureModifier":
        """创建提高指定非 HP 能力到 1.1 倍的性格倍率。"""
        return cls.neutral().with_modifier(field, 1.1)

    @classmethod
    def decrease(cls, field: StatField | str) -> "NatureModifier":
        """创建降低指定非 HP 能力到 0.9 倍的性格倍率。"""
        return cls.neutral().with_modifier(field, 0.9)

    def value_for(self, field: StatField | str) -> float:
        """读取指定能力的性格倍率；HP 固定返回 1.0。"""
        name = _field_name(field)
        if name == StatField.HP.value:
            return 1.0
        return getattr(self, name)

    def with_modifier(
        self, field: StatField | str, multiplier: float
    ) -> "NatureModifier":
        """返回一个替换指定非 HP 能力倍率的新 NatureModifier。"""
        name = _field_name(field)
        if name == StatField.HP.value:
            raise ValueError("HP cannot be modified by nature")
        return replace(self, **{name: multiplier})


@dataclass(frozen=True)
class StatProfile:
    """
    表示计算实际能力值所需的完整配置。

    base_stats 是种族值，evs 是努力值，ivs 是个体值，nature_modifier 是性格倍率；
    calculate_actual_stats 会基于这个对象和等级算出最终战斗能力值。
    """

    base_stats: StatValues
    evs: StatValues = StatValues.zero()
    ivs: StatValues = StatValues.perfect_ivs()
    nature_modifier: NatureModifier = NatureModifier.neutral()


def calculate_hp_stat(*, base: int, iv: int, ev: int, level: int) -> int:
    """按现代宝可梦 HP 公式计算实际 HP，并保留正确的 floor 位置。"""
    return floor(((2 * base + iv + floor(ev / 4)) * level) / 100) + level + 10


def calculate_non_hp_stat(
    *,
    base: int,
    iv: int,
    ev: int,
    level: int,
    nature_modifier: float,
) -> int:
    """按现代宝可梦非 HP 能力公式计算攻击、防御、特攻、特防或速度。"""
    raw = floor(((2 * base + iv + floor(ev / 4)) * level) / 100) + 5
    return floor(raw * nature_modifier)


def calculate_actual_stats(profile: StatProfile, *, level: int) -> StatValues:
    """
    根据 StatProfile 和等级计算完整六项实际能力值。

    这里集中执行 HP 与非 HP 两套公式，确保 application/use case 不需要理解
    努力值、个体值、性格倍率和 floor 顺序这些细节。
    """
    return StatValues(
        hp=calculate_hp_stat(
            base=profile.base_stats.hp,
            iv=profile.ivs.hp,
            ev=profile.evs.hp,
            level=level,
        ),
        attack=calculate_non_hp_stat(
            base=profile.base_stats.attack,
            iv=profile.ivs.attack,
            ev=profile.evs.attack,
            level=level,
            nature_modifier=profile.nature_modifier.attack,
        ),
        defense=calculate_non_hp_stat(
            base=profile.base_stats.defense,
            iv=profile.ivs.defense,
            ev=profile.evs.defense,
            level=level,
            nature_modifier=profile.nature_modifier.defense,
        ),
        special_attack=calculate_non_hp_stat(
            base=profile.base_stats.special_attack,
            iv=profile.ivs.special_attack,
            ev=profile.evs.special_attack,
            level=level,
            nature_modifier=profile.nature_modifier.special_attack,
        ),
        special_defense=calculate_non_hp_stat(
            base=profile.base_stats.special_defense,
            iv=profile.ivs.special_defense,
            ev=profile.evs.special_defense,
            level=level,
            nature_modifier=profile.nature_modifier.special_defense,
        ),
        speed=calculate_non_hp_stat(
            base=profile.base_stats.speed,
            iv=profile.ivs.speed,
            ev=profile.evs.speed,
            level=level,
            nature_modifier=profile.nature_modifier.speed,
        ),
    )


__all__ = [
    "NatureModifier",
    "StatProfile",
    "StatValues",
    "calculate_actual_stats",
    "calculate_hp_stat",
    "calculate_non_hp_stat",
]
