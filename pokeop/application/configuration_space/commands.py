"""定义配置空间候选池、枚举模式和运行保护 command。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.configuration_space.model_base import (
    ConfigurationSpaceError,
    ConfigurationWeightAssumption,
    StatEnumerationMode,
    _is_integer,
    _is_positive_integer,
)
from pokeop.domain.battle.effects.registry import normalize_effect_identifier
from pokeop.domain.battle.stats import NatureModifier
from pokeop.domain.models.pokemon_fields import StatField


@dataclass(frozen=True, slots=True)
class MoveSpaceCommand:
    """限制一次招式配置枚举允许使用的候选池和槽位数量。

    Args:
        candidate_move_ids: 允许参与枚举的招式 ID；空元组表示使用 profile 中全部候选。
        slot_counts: 需要生成的招式槽数量，每项必须位于 1 到 4。
        max_raw_combinations: 归并前允许生成的合法招式组合原始成员上限。
    """

    candidate_move_ids: tuple[int, ...] = ()
    slot_counts: tuple[int, ...] = (4,)
    max_raw_combinations: int = 10_000

    def __post_init__(self) -> None:
        """规范化候选池，并校验槽位数量和招式组合运行保护。"""
        move_ids = tuple(self.candidate_move_ids)
        slot_counts = tuple(self.slot_counts)
        if any(not _is_positive_integer(value) for value in move_ids):
            raise ConfigurationSpaceError(
                "candidate_move_ids must be positive integers"
            )
        if len(move_ids) != len(set(move_ids)):
            raise ConfigurationSpaceError("candidate_move_ids must be unique")
        if not slot_counts or any(
            not _is_integer(value) or not 1 <= value <= 4
            for value in slot_counts
        ):
            raise ConfigurationSpaceError("slot_counts must contain values from 1 to 4")
        if len(slot_counts) != len(set(slot_counts)):
            raise ConfigurationSpaceError("slot_counts must be unique")
        if not _is_positive_integer(self.max_raw_combinations):
            raise ConfigurationSpaceError(
                "max_raw_combinations must be a positive integer"
            )
        object.__setattr__(self, "candidate_move_ids", tuple(sorted(move_ids)))
        object.__setattr__(self, "slot_counts", tuple(sorted(slot_counts)))


@dataclass(frozen=True, slots=True)
class StatSpaceCommand:
    """声明固定 preset 或受控离散能力配置的枚举边界。

    Args:
        mode: 固定 preset 或受控离散 EV/性格枚举模式。
        preset_keys: PRESET 模式需要应用的 ``StatProfilePreset`` key。
        relevant_fields: CONTROLLED 模式允许分配 EV 的能力字段；其他字段固定为 0。
        ev_values: CONTROLLED 模式每个 relevant field 可取的显式 EV 值。
        nature_modifiers: CONTROLLED 模式允许使用的完整性格倍率快照。
        max_raw_profiles: 归并最终能力值之前允许检查的合法 EV/性格配置上限。
    """

    mode: StatEnumerationMode = StatEnumerationMode.PRESET
    preset_keys: tuple[str, ...] = ("max_atk_plus",)
    relevant_fields: tuple[StatField, ...] = (
        StatField.HP,
        StatField.ATTACK,
        StatField.DEFENSE,
        StatField.SPECIAL_ATTACK,
        StatField.SPECIAL_DEFENSE,
        StatField.SPEED,
    )
    ev_values: tuple[int, ...] = (0, 252)
    nature_modifiers: tuple[NatureModifier, ...] = (NatureModifier.neutral(),)
    max_raw_profiles: int = 4096

    def __post_init__(self) -> None:
        """校验模式对应的 preset、EV、性格和运行保护参数。"""
        if not isinstance(self.mode, StatEnumerationMode):
            raise ConfigurationSpaceError("mode must be a StatEnumerationMode")
        if not _is_positive_integer(self.max_raw_profiles):
            raise ConfigurationSpaceError(
                "max_raw_profiles must be a positive integer"
            )

        preset_keys = tuple(self.preset_keys)
        relevant_fields = tuple(self.relevant_fields)
        ev_values = tuple(self.ev_values)
        nature_modifiers = tuple(self.nature_modifiers)

        if self.mode is StatEnumerationMode.PRESET:
            if not preset_keys or any(not key.strip() for key in preset_keys):
                raise ConfigurationSpaceError(
                    "preset mode requires at least one non-blank preset key"
                )
            if len(preset_keys) != len(set(preset_keys)):
                raise ConfigurationSpaceError("preset_keys must be unique")
        else:
            if not relevant_fields:
                raise ConfigurationSpaceError(
                    "controlled mode requires at least one relevant stat field"
                )
            if any(not isinstance(field, StatField) for field in relevant_fields):
                raise ConfigurationSpaceError(
                    "relevant_fields must contain only StatField values"
                )
            if len(relevant_fields) != len(set(relevant_fields)):
                raise ConfigurationSpaceError("relevant_fields must be unique")
            if not ev_values or any(
                not _is_integer(value) or not 0 <= value <= 252
                for value in ev_values
            ):
                raise ConfigurationSpaceError(
                    "ev_values must contain integers from 0 to 252"
                )
            if len(ev_values) != len(set(ev_values)):
                raise ConfigurationSpaceError("ev_values must be unique")
            if not nature_modifiers or any(
                not isinstance(value, NatureModifier) for value in nature_modifiers
            ):
                raise ConfigurationSpaceError(
                    "nature_modifiers must contain NatureModifier values"
                )
            if len(nature_modifiers) != len(set(nature_modifiers)):
                raise ConfigurationSpaceError("nature_modifiers must be unique")

        object.__setattr__(self, "preset_keys", preset_keys)
        object.__setattr__(self, "relevant_fields", relevant_fields)
        object.__setattr__(self, "ev_values", tuple(sorted(ev_values)))
        object.__setattr__(self, "nature_modifiers", nature_modifiers)


@dataclass(frozen=True, slots=True)
class AbilitySpaceCommand:
    """限制一次特性维度枚举允许保留的合法候选标识。"""

    candidate_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """规范化显式候选集合；空元组表示使用 profile 中全部合法特性。"""
        if any(
            not isinstance(identifier, str)
            for identifier in self.candidate_identifiers
        ):
            raise ConfigurationSpaceError(
                "ability candidate identifiers must be strings"
            )
        identifiers = tuple(
            normalize_effect_identifier(identifier)
            for identifier in self.candidate_identifiers
        )
        if any(not identifier for identifier in identifiers):
            raise ConfigurationSpaceError(
                "ability candidate identifiers must not be blank"
            )
        if len(identifiers) != len(set(identifiers)):
            raise ConfigurationSpaceError(
                "ability candidate identifiers must be unique after normalization"
            )
        object.__setattr__(self, "candidate_identifiers", tuple(sorted(identifiers)))


@dataclass(frozen=True, slots=True)
class ItemSpaceCommand:
    """限制一次道具维度枚举使用的受控候选集合。

    ``None`` 明确表示不携带道具。候选不会从全游戏道具表自动扩张，调用方必须主动
    提供希望覆盖的集合；默认只覆盖无道具和讲究头带。
    """

    candidate_identifiers: tuple[str | None, ...] = (None, "choice-band")

    def __post_init__(self) -> None:
        """规范化道具标识并拒绝重复候选。"""
        if any(
            identifier is not None and not isinstance(identifier, str)
            for identifier in self.candidate_identifiers
        ):
            raise ConfigurationSpaceError(
                "item candidate identifiers must be strings or None"
            )
        identifiers = tuple(
            None
            if identifier is None
            else normalize_effect_identifier(identifier)
            for identifier in self.candidate_identifiers
        )
        if not identifiers:
            raise ConfigurationSpaceError("item candidate identifiers must not be empty")
        if any(identifier == "" for identifier in identifiers):
            raise ConfigurationSpaceError("item identifiers must be non-blank or None")
        if len(identifiers) != len(set(identifiers)):
            raise ConfigurationSpaceError(
                "item candidate identifiers must be unique after normalization"
            )
        object.__setattr__(
            self,
            "candidate_identifiers",
            tuple(sorted(identifiers, key=lambda value: (value is not None, value or ""))),
        )


@dataclass(frozen=True, slots=True)
class PokemonSpaceCommand:
    """组合单只 Pokémon 四个标准配置维度及其运行保护上限。"""

    moves: MoveSpaceCommand = MoveSpaceCommand()
    stats: StatSpaceCommand = StatSpaceCommand()
    abilities: AbilitySpaceCommand = AbilitySpaceCommand()
    items: ItemSpaceCommand = ItemSpaceCommand()
    level: int = 50
    max_raw_configurations: int = 100_000

    def __post_init__(self) -> None:
        """校验战斗等级与单边原始组合上限。"""
        if not _is_integer(self.level) or not 1 <= self.level <= 100:
            raise ConfigurationSpaceError("level must be an integer from 1 to 100")
        if not _is_positive_integer(self.max_raw_configurations):
            raise ConfigurationSpaceError(
                "max_raw_configurations must be a positive integer"
            )


@dataclass(frozen=True, slots=True)
class GenerateConfigurationSpaceCommand:
    """声明双方配置空间、权重语义和配置对运行保护。

    Args:
        attacker: 攻击方单边配置空间限制。
        defender: 防守方单边配置空间限制。
        weight_assumption: 配置覆盖统计采用的均匀假设，不代表真实使用率。
        max_raw_configuration_pairs: 归并前允许生成的双方原始配置对上限。
    """

    attacker: PokemonSpaceCommand
    defender: PokemonSpaceCommand
    weight_assumption: ConfigurationWeightAssumption = (
        ConfigurationWeightAssumption.UNIFORM_RAW_CONFIGURATION
    )
    max_raw_configuration_pairs: int = 1_000_000

    def __post_init__(self) -> None:
        """拒绝未知权重假设和非正配置对上限。"""
        if not isinstance(self.weight_assumption, ConfigurationWeightAssumption):
            raise ConfigurationSpaceError(
                "weight_assumption must be a ConfigurationWeightAssumption"
            )
        if not _is_positive_integer(self.max_raw_configuration_pairs):
            raise ConfigurationSpaceError(
                "max_raw_configuration_pairs must be a positive integer"
            )




__all__ = [
    "AbilitySpaceCommand",
    "GenerateConfigurationSpaceCommand",
    "ItemSpaceCommand",
    "MoveSpaceCommand",
    "PokemonSpaceCommand",
    "StatSpaceCommand",
]
